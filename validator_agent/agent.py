"""학생 검증 agent: 페르소나마다 학생 agent를 따로(병렬로) 돌리고, 코드가 충실도 검사·집계·판정을 한다.

AI 공급자: openai (VALIDATOR_MODEL → GENERATOR_MODEL → OPENAI_MODEL 순) | mock (시연용 정책)
LangSmith: .env에 LANGSMITH_TRACING=true와 키가 있으면 페르소나별 실행 흐름이 기록된다.
"""
import contextvars
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable, Dict, List, Optional

from generator_agent.pricing import cost_krw

from . import judge, prompts
from .schemas import PersonaCard, RunResult, ValidationInput, load_personas
from .tools import TOOL_SPECS, PersonaToolBox

try:
    from langsmith import traceable
except ImportError:
    def traceable(*_a, **_k):
        return lambda f: f


class StudentValidator:
    def __init__(self, inp: ValidationInput, provider: str = "openai", on_event: Optional[Callable[[str], None]] = None):
        if not inp.personas:
            inp.personas = load_personas()
        self.inp = inp
        self.provider = provider
        self.model = os.getenv("VALIDATOR_MODEL") or os.getenv("GENERATOR_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
        self.on_event = on_event or (lambda m: None)
        self.lock = threading.Lock()
        self.cost = 0.0
        self.usage = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}
        self.runs: List[RunResult] = []
        self.stopped_by_budget = False

    # ---------- 전체 흐름 ----------

    def run(self) -> Dict:
        traced = traceable(name="학생 검증 agent", run_type="chain",
                           metadata={"provider": self.provider, "personas": len(self.inp.personas)})(self._run)
        return traced({"field": self.inp.view.field, "subjects": len(self.inp.view.subjects),
                       "non_major_ratio": self.inp.non_major_ratio, "pass_score": self.inp.pass_score})

    def _run(self, request: Dict) -> Dict:  # request는 LangSmith 화면에 입력으로 보이도록 받는다
        started = time.time()
        rounds = 0
        result: Dict = {}
        while True:
            rounds += 1
            self.on_event(f"{rounds}회차 평가: 학생 {len(self.inp.personas)}명")
            self._round(rounds)
            result = judge.aggregate(self.inp, self.runs)
            if self.stopped_by_budget or not judge.needs_more_rounds(result, rounds):
                break
            self.on_event(f"점수 {result['weighted_score']}가 합격 기준 {self.inp.pass_score} 근처라 한 번 더 평가해요")
        result["meta"] = {
            "provider": self.provider, "model": self.model if self.provider != "mock" else "",
            "rounds": rounds, "runs": len(self.runs), "seconds": round(time.time() - started, 1),
            "cost_krw": round(self.cost, 1), "budget_krw": self.inp.budget_krw, "usage": self.usage,
            "stopped_by_budget": self.stopped_by_budget, "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
        result["persona_feedback"] = judge.to_persona_feedback(result)
        result["app_validation"] = judge.to_app_validation(result, self.runs, self.inp.personas)
        return result

    def _round(self, round_no: int):
        tasks = list(self.inp.personas)
        with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
            futures = [ex.submit(contextvars.copy_context().run, self._persona_with_retry, p, round_no) for p in tasks]
            for f in futures:
                f.result()

    def _persona_with_retry(self, persona: PersonaCard, round_no: int):
        r = self._run_persona(persona, round_no)
        if r.fidelity.get("excluded") and not self.stopped_by_budget:
            self.on_event(f"{persona.name}: 설정과 다른 답이 많아 다시 평가해요 ({'; '.join(r.fidelity['issues'][:2])})")
            self._run_persona(persona, round_no, retry=True)

    # ---------- 페르소나 1명 실행 ----------

    def _run_persona(self, persona: PersonaCard, round_no: int, retry: bool = False) -> RunResult:
        name = f"{persona.name} · {round_no}회차" + (" (재평가)" if retry else "")
        return traceable(name=name, run_type="chain", metadata={"persona": persona.id})(self._persona)(persona, round_no)

    def _persona(self, persona: PersonaCard, round_no: int) -> RunResult:
        tb = PersonaToolBox(self.inp.view, persona)
        run = RunResult(persona_id=persona.id, run=round_no)

        def act(name: str, args: Optional[Dict] = None, why: str = "") -> Dict:
            args = dict(args or {})
            why = args.pop("why", "") or why
            result = traceable(run_type="tool", name=name, metadata={"why": why, "persona": persona.id})(
                lambda n, a: tb.call(n, a))(name, args)
            run.trace.append({"step": len(run.trace) + 1, "tool": name, "why": why, "args": args, "result": result})
            return result

        if self.provider == "mock":
            from .mock_policy import run_mock
            run_mock(tb, act)
        else:
            self._loop_openai(tb, act, run)

        run.finished = tb.finished
        run.journal = list(tb.journal.values())
        run.gaps = tb.gaps
        run.scores = tb.result.get("scores", {})
        run.completion = tb.result.get("completion", "")
        run.summary = tb.result.get("summary", "")
        run.steps = len(run.trace)
        run.fidelity = judge.fidelity(run, tb) if tb.finished else {"issues": ["끝내지 못함"], "excluded": True}
        with self.lock:
            self.runs.append(run)
        self.on_event(f"{persona.name}: {'완료' if run.finished else '미완료'} · {run.steps}단계"
                      + (f" · 수료 {run.completion}" if run.completion else "")
                      + (" · 판정 제외" if run.fidelity.get("excluded") else ""))
        return run

    def _loop_openai(self, tb: PersonaToolBox, act, run: RunResult):
        from openai import OpenAI

        client = OpenAI(timeout=float(os.getenv("OPENAI_TIMEOUT", "120")), max_retries=2)  # 멈춘 요청이 10분씩 기다리지 않게
        try:
            from langsmith.wrappers import wrap_openai
            client = wrap_openai(client)
        except ImportError:
            pass
        max_steps = len(tb.order) * 4 + 12
        messages: List[Dict] = [{"role": "system", "content": prompts.SYSTEM},
                                {"role": "user", "content": prompts.KICKOFF}]
        nudges = 0
        while len(run.trace) < max_steps and not tb.finished:
            with self.lock:
                if self.cost >= self.inp.budget_krw:
                    self.stopped_by_budget = True
                    return
            resp = client.chat.completions.create(model=self.model, messages=messages, tools=TOOL_SPECS,
                                                  tool_choice="auto", parallel_tool_calls=False)
            if resp.usage:
                details = getattr(resp.usage, "prompt_tokens_details", None)
                cached = (getattr(details, "cached_tokens", 0) or 0) if details else 0
                c = cost_krw(self.model, resp.usage.prompt_tokens, resp.usage.completion_tokens, cached)
                with self.lock:
                    self.cost += c
                    self.usage["input_tokens"] += resp.usage.prompt_tokens
                    self.usage["output_tokens"] += resp.usage.completion_tokens
                    self.usage["cached_input_tokens"] += cached
                run.cost_krw += c
            msg = resp.choices[0].message
            if not msg.tool_calls:
                nudges += 1
                if nudges > 3:
                    return
                messages.append({"role": "assistant", "content": msg.content or ""})
                messages.append({"role": "user", "content": prompts.NUDGE})
                continue
            messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    result = act(tc.function.name, args)
                except json.JSONDecodeError:
                    result = {"ok": False, "error": "arguments가 올바른 JSON이 아님"}
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, ensure_ascii=False)})
