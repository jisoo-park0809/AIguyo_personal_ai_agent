"""생성 agent 실행기: AI가 tool을 고르고 → 코드가 실행하고 → 결과를 돌려주는 반복.

AI 공급자
- openai: OpenAI tool 호출 (OPENAI_API_KEY, 모델은 GENERATOR_MODEL 또는 OPENAI_MODEL)
- mock: API 없이 정해진 규칙으로 tool을 부르는 시연용 정책 (mock_policy.py)

LangSmith: .env에 LANGSMITH_TRACING=true와 LANGSMITH_API_KEY가 있으면 실행 흐름(AI 호출, tool 호출, 고른 이유)이
LangSmith 화면에 기록된다. 없으면 기록하지 않고 그대로 동작한다.
"""
import json
import os
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional

from . import prompts, regulation_judge
from .precheck import precheck
from .pricing import cost_krw
from .regulation_search import make_search
from .schemas import GenerationInput
from .tools import TOOL_SPECS, ToolBox
from .workspace import Workspace

try:
    from langsmith import traceable
except ImportError:  # langsmith가 없으면 기록 없이 동작
    def traceable(*_a, **_k):
        return lambda f: f

DEFAULT_MAX_STEPS = int(os.getenv("GENERATOR_MAX_STEPS", "90"))  # 퀴즈·숙련목표 작성으로 단계가 늘어 60 → 90


class GeneratorAgent:
    def __init__(self, inp: GenerationInput, provider: str = "openai", max_steps: int = DEFAULT_MAX_STEPS,
                 on_step: Optional[Callable[[Dict], None]] = None):
        self.inp = inp
        self.provider = provider
        self.max_steps = max_steps
        self.ws = Workspace(inp)
        self.tools = ToolBox(self.ws, make_search(inp))
        self.trace: List[Dict] = []
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self.cost_krw = 0.0
        self.stop_reason = ""
        self.on_step = on_step or (lambda s: None)

    # 한 번의 tool 실행을 기록한다 (AI와 시연 정책이 같이 쓴다)
    def act(self, name: str, args: Optional[Dict] = None, thought: str = "") -> Dict:
        args = dict(args or {})
        why = args.pop("why", "") or thought  # AI가 이 tool을 고른 이유 (모든 tool의 필수 칸)
        result = traceable(run_type="tool", name=name, metadata={"why": why})(self._call_tool)(name, args, why)
        step = {"step": len(self.trace) + 1, "thought": why, "tool": name, "args": args, "result": result}
        self.trace.append(step)
        self.on_step(step)
        return result

    def _call_tool(self, name: str, args: Dict, why: str) -> Dict:
        return self.tools.call(name, args)

    @property
    def course_name(self) -> str:
        return self.inp.course.title or self.inp.course.field

    def run(self) -> Dict:
        mode = "수정" if self.inp.revise_mode else "생성"
        traced = traceable(name=f"생성 agent ({mode})", run_type="chain",
                           metadata={"provider": self.provider, "course": self.course_name,
                                     "owner": self.inp.draft.owner})(self._run)
        return traced(self.inp.model_dump(exclude={"previous_curriculum"}))

    def _run(self, request: Dict) -> Dict:  # request는 LangSmith 화면에 입력으로 보이도록 받는다
        started = time.time()
        mode = "수정" if self.inp.revise_mode else "생성"
        errors = precheck(self.inp)  # ⓪ AI를 부르기 전에 입력 점검
        if errors:
            return {"rejected": errors, "curriculum": None, "trace": []}
        if self.provider == "mock":
            from .mock_policy import run_mock
            run_mock(self.inp, self.act)
        else:
            self._run_openai(mode)
        return self._result(mode, time.time() - started)

    def _run_openai(self, mode: str):
        from openai import OpenAI

        client = OpenAI(timeout=float(os.getenv("OPENAI_TIMEOUT", "120")), max_retries=2)  # 멈춘 요청이 10분씩 기다리지 않게
        try:
            from langsmith.wrappers import wrap_openai
            client = wrap_openai(client)  # AI 호출(프롬프트·응답·토큰)도 LangSmith에 기록
        except ImportError:
            pass
        model = os.getenv("GENERATOR_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.model = model
        # 판단 조항 심사 AI: 같은 모델이지만 생성 대화와 분리된 별도 호출 (생성 AI가 자기 답안을 채점하지 않게)
        judge_model = os.getenv("JUDGE_MODEL") or model
        self.tools.judge = traceable(run_type="chain", name="규정 심사 AI")(
            regulation_judge.openai_judge(client, judge_model, lambda u: self._charge(judge_model, u)))
        messages: List[Dict] = [{"role": "system", "content": prompts.SYSTEM},
                                {"role": "user", "content": prompts.kickoff(mode, self.inp)}]
        nudges = 0
        while len(self.trace) < self.max_steps and not self.tools.finished:
            resp = client.chat.completions.create(model=model, messages=messages, tools=TOOL_SPECS,
                                                  tool_choice="auto", parallel_tool_calls=False)
            if resp.usage:
                self._charge(model, resp.usage)
            msg = resp.choices[0].message
            if self.cost_krw >= self.inp.budget_krw:  # ⑤ 예산 상한: 멈추고 그때까지 결과를 저장
                self.stop_reason = "예산 상한"
                break
            if not msg.tool_calls:
                nudges += 1
                if nudges > 3:
                    self.stop_reason = "AI가 tool을 더 부르지 않음"
                    break
                messages.append({"role": "assistant", "content": msg.content or ""})
                messages.append({"role": "user", "content": prompts.NUDGE})
                continue
            messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args, result = {}, {"ok": False, "error": "arguments가 올바른 JSON이 아님"}
                else:
                    result = self.act(tc.function.name, args, thought=msg.content or "")
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(result, ensure_ascii=False)})

    def _charge(self, model: str, usage):
        details = getattr(usage, "prompt_tokens_details", None)
        cached = (getattr(details, "cached_tokens", 0) or 0) if details else 0
        self.usage["input_tokens"] += usage.prompt_tokens
        self.usage["output_tokens"] += usage.completion_tokens
        self.usage["cached_input_tokens"] = self.usage.get("cached_input_tokens", 0) + cached
        self.cost_krw += cost_krw(model, usage.prompt_tokens, usage.completion_tokens, cached)

    def _result(self, mode: str, seconds: float) -> Dict:
        cur = self.ws.cur
        if not cur.check_report:
            from . import checks
            cur.check_report = checks.check(self.ws)
        if self.tools.finished:
            self.stop_reason = "finish (점검 통과)" if cur.check_report.get("pass") else "finish (못 고친 문제 있음)"
        elif not self.stop_reason:
            self.stop_reason = "최대 단계" if len(self.trace) >= self.max_steps else "중단"
        cur.meta = {
            "draft_name": self.inp.draft.name, "owner": self.inp.draft.owner, "memo": self.inp.draft.memo,
            "course_title": self.course_name, "field": self.inp.course.field,
            "business_profile": self.inp.course.business_profile,
            "outputs": self.inp.outputs, "mode": mode, "provider": self.provider,
            "model": getattr(self, "model", "") if self.provider != "mock" else "",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "finished": self.tools.finished, "stop_reason": self.stop_reason,
            "summary": self.tools.summary, "unresolved": self.tools.unresolved,
            "steps": len(self.trace), "seconds": round(seconds, 1), "usage": self.usage,
            "cost_krw": round(self.cost_krw, 1), "budget_krw": self.inp.budget_krw,
        }
        cur.validation_criteria = {"pass_score": self.inp.pass_score}  # 검증 agent로 넘기는 합격 기준
        cur.schedule = self.ws.schedule()
        cur.regulation_notes = self.tools.reg_notes
        cur.compliance = self.tools.compliance()
        cur.meta["regulation_judge_runs"] = self.tools.judge_runs
        if not self.tools.finished:
            cur.open_items.append(f"[작성 필요: agent가 끝내지 못함 ({self.stop_reason}). 점검 결과 확인]")
        return {"curriculum": cur.model_dump(), "trace": self.trace}
