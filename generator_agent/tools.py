"""생성 agent가 고를 수 있는 tool 목록과 실행기.

AI는 각 tool의 description을 읽고 언제 쓸지 판단한다. 그래서 description에는 '언제 쓰는지'를 적는다.
"""
import json
from typing import Any, Callable, Dict, List

from . import checks, regulation_judge, rulebook
from .announcement import make_announcement_search
from .profiles import course_example_ids, load_course_example, load_portfolios, load_profile
from .workspace import Workspace

MAX_FINISH_OVERRIDE = 2  # 점검을 통과하지 못해도 이유를 적고 끝낼 수 있게 되기까지 실패한 finish 횟수

_SUBJECT = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "category": {"type": "string", "enum": ["이론", "실습", "프로젝트"]},
        "theory_hours": {"type": "number"},
        "practice_hours": {"type": "number"},
        "project_hours": {"type": "number"},
        "mode": {"type": "string", "enum": ["집체", "원격"]},
        "goals": {"type": "array", "items": {"type": "string"}, "description": "교과목 학습목표"},
        "topics": {"type": "array", "items": {"type": "string"}},
        "concepts_taught": {"type": "array", "items": {"type": "string"},
                            "description": "이 교과목에서 가르치는 개념 태그 (뒤 교과목의 선수 개념 검사에 쓰임)"},
        "prerequisites": {"type": "array", "items": {"type": "string"},
                          "description": "이 교과목을 듣기 전에 알아야 하는 개념 태그"},
        "assessment": {"type": "string", "description": "평가 방법"},
        "linked_goals": {"type": "array", "items": {"type": "string"}, "description": "연결된 학습 목표 id (G1…)"},
        "company_task_ids": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string", "description": "이 교과목을 이 위치·시간으로 둔 이유"},
    },
    "required": ["title", "category", "theory_hours", "practice_hours", "project_hours"],
}

_UNIT = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "hours": {"type": "number"},
                   "activities": {"type": "array", "items": {"type": "string"}},
                   "deliverable": {"type": "string"}},
    "required": ["title", "hours"],
}


_WHY = {"type": "string", "description": "지금 이 tool을 부르는 이유 한 줄 (무엇을 보고 무엇을 하려는지)"}


def _fn(name: str, description: str, properties: Dict, required: List[str] = ()) -> Dict:
    # 모든 tool에 '이유(why)'를 필수로 받아 실행 기록·LangSmith에서 판단 흐름을 볼 수 있게 한다
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": {"why": _WHY, **properties},
                       "required": ["why"] + list(required)}}}


TOOL_SPECS = [
    _fn("get_brief", "과정 정보·교육 목적·훈련 대상·협약 기업 과제·만들 결과물을 본다. 작업을 시작할 때 먼저 쓴다.", {}),
    _fn("get_rules", "사업 프로필 규정, 확인된 규정, 그리고 코드가 계산한 목표치(필요 프로젝트 시간, 총 주차)를 본다. 시간 배분을 정하기 전에 쓴다.", {}),
    _fn("search_regulations", "운영 규정집 PDF에서 관련 조문을 찾는다. 규정 근거가 필요하거나 규정 내용이 궁금할 때 쓴다.",
        {"query": {"type": "string", "description": "찾을 주제 (예: 훈련시간, 프로젝트, 평가)"}}, ["query"]),
    _fn("search_announcement", "업로드한 공고문에서 관련 부분을 찾는다. 공고의 요구사항·심사 기준·편성 조건을 확인할 때 쓴다. 공고가 없으면 빈 결과.",
        {"query": {"type": "string", "description": "찾을 단어 (예: 훈련시간, 프로젝트, 심사)"}}, ["query"]),
    _fn("get_course_example", "참고할 과정 예시를 본다. id 없이 부르면 목록을 돌려준다. 교과목 구성과 순서를 잡을 때 참고한다.",
        {"example_id": {"type": "string"}}),
    _fn("get_portfolio_examples", "포트폴리오 예시를 본다. 프로젝트 산출물을 정할 때 쓴다.",
        {"keyword": {"type": "string", "description": "분야 키워드 (예: 게임, LLM). 비우면 전부"}}),
    _fn("get_persona_feedback", "수정 모드에서 학생 페르소나별 점수와 기준 미만 교과목을 본다. 수정을 시작할 때 쓴다.", {}),
    _fn("get_draft", "지금까지 쓴 초안을 본다. scope='summary'는 전체 요약, 교과목 id를 넣으면 그 교과목 상세.",
        {"scope": {"type": "string"}}),
    _fn("set_plan", "교육 목적을 어떻게 해석했는지 한 줄과 학습 목표를 정한다. 교과목을 쓰기 전에 쓴다.",
        {"intent_summary": {"type": "string", "description": "교육 목적을 이 과정 구조로 어떻게 풀지 한 줄"},
         "learning_goals": {"type": "array", "items": {"type": "object", "properties": {
             "id": {"type": "string"}, "text": {"type": "string"}}, "required": ["text"]}}},
        ["intent_summary", "learning_goals"]),
    _fn("add_subject", "교과목 하나를 편성표에 추가한다. position을 주면 그 자리(0부터)에 넣는다.",
        {"subject": _SUBJECT, "position": {"type": "integer"}}, ["subject"]),
    _fn("update_subject", "교과목 일부를 고친다. 바꿀 항목만 fields에 넣는다. 점검 위반이나 페르소나 피드백을 반영할 때 쓴다.",
        {"subject_id": {"type": "string"}, "fields": {"type": "object"},
         "reason": {"type": "string"}, "source": {"type": "string", "description": "점검 위반 | 페르소나 피드백 | 설계"}},
        ["subject_id", "fields", "reason"]),
    _fn("remove_subject", "교과목을 뺀다.", {"subject_id": {"type": "string"}, "reason": {"type": "string"}},
        ["subject_id", "reason"]),
    _fn("move_subject", "교과목 순서를 바꾼다. 선수 개념 순서가 어긋날 때 쓴다.",
        {"subject_id": {"type": "string"}, "position": {"type": "integer"}, "reason": {"type": "string"}},
        ["subject_id", "position", "reason"]),
    _fn("allocate_hours", "교과목별 비중만 정하면 코드가 총 훈련시간·프로젝트 비율에 맞춰 시간을 나눈다. "
        "시간 합계나 프로젝트 비율이 맞지 않을 때는 시간을 직접 고치지 말고 이 tool을 쓴다. 모든 교과목의 비중이 필요하다.",
        {"weights": {"type": "object", "description": "교과목 id → 상대 비중 (예: {\"S01\": 3, \"S02\": 2})",
                     "additionalProperties": {"type": "number"}},
         "theory_share": {"type": "object", "description": "선택: 일반 교과목 id → 이론 시간 비율 0~1",
                          "additionalProperties": {"type": "number"}},
         "reason": {"type": "string", "description": "비중을 이렇게 정한 이유"}},
        ["weights", "reason"]),
    _fn("set_project","프로젝트를 정한다(같은 id면 덮어씀). 협약 기업 과제마다 하나씩 연결한다.",
        {"project": {"type": "object", "properties": {
            "id": {"type": "string"}, "title": {"type": "string"}, "company_task_id": {"type": "string"},
            "subject_ids": {"type": "array", "items": {"type": "string"}},
            "description": {"type": "string"}, "portfolio_output": {"type": "string"}},
            "required": ["title", "subject_ids"]}}, ["project"]),
    _fn("write_units", "교과목의 단원 설계를 쓴다. 결과물에 '단원 설계'가 있을 때만 쓴다. "
        "단원의 hours는 대략적인 비중으로 적으면 코드가 교과목 시간에 맞춰 나눈다. 시간 배분(allocate_hours)이 끝난 뒤에 쓴다.",
        {"subject_id": {"type": "string"}, "units": {"type": "array", "items": _UNIT}}, ["subject_id", "units"]),
    _fn("set_skill_targets", "숙련목표를 정한다(전체를 덮어씀). 수료할 때 무엇을 어느 수준까지 할 수 있어야 하는지, 교육 목적·설계 의도와 "
        "학습자 목표를 참고해 확인 가능한 문장으로 쓴다. 교과목 구성이 정해진 뒤에 쓴다.",
        {"targets": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string", "description": "K1, K2 …"}, "text": {"type": "string"},
            "level": {"type": "string", "description": "안내를 받아 수행 | 독립 수행 | 응용"},
            "subject_ids": {"type": "array", "items": {"type": "string"}, "description": "이 목표를 기르는 교과목 id"}},
            "required": ["text", "subject_ids"]}}}, ["targets"]),
    _fn("write_quiz", "교과목의 이해도 평가용 객관식 퀴즈를 쓴다. 프로젝트가 아닌 교과목마다 3문항 이상. 보기는 4개, answer는 정답 보기 번호(1~4). "
        "교과목의 학습목표·주요 내용 범위에서 내고, 문항마다 확인하는 숙련목표 id를 연결한다. week를 비우면 교과목이 끝나는 주차에 본다. "
        "긴 교과목은 week를 정해 중간 퀴즈를 하나 더 쓸 수 있다(같은 교과목·주차면 덮어씀). 정답 위치는 코드가 고르게 섞으니 '위 보기 모두'처럼 순서에 기대는 보기는 쓰지 않는다.",
        {"subject_id": {"type": "string"}, "week": {"type": "integer", "description": "선택: 퀴즈를 보는 주차"},
         "questions": {"type": "array", "items": {"type": "object", "properties": {
             "question": {"type": "string"}, "choices": {"type": "array", "items": {"type": "string"}},
             "answer": {"type": "integer"}, "explanation": {"type": "string", "description": "정답 해설 한두 문장"},
             "skill_target_ids": {"type": "array", "items": {"type": "string"}}},
             "required": ["question", "choices", "answer", "skill_target_ids"]}}}, ["subject_id", "questions"]),
    _fn("set_proficiency_methods", "숙련도를 높이는 방법을 정한다(전체를 덮어씀). 퀴즈·프로젝트 결과를 보고 숙련목표에 못 미친 훈련생을 "
        "어떻게 끌어올릴지(보충학습, 복습 과제, 코드 리뷰, 멘토링 등) 언제·누구에게·무엇을 하는지 구체적으로 쓴다.",
        {"methods": {"type": "array", "items": {"type": "object", "properties": {
            "method": {"type": "string"}, "description": {"type": "string"}, "timing": {"type": "string"},
            "subject_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["method", "description"]}}},
        ["methods"]),
    _fn("check_draft", "코드가 초안을 점검한다: 시간 합계, 프로젝트 비율, 훈련 방식, 선수 개념 순서, 기업 과제 연결, 단원 시간, "
        "숙련목표·퀴즈·숙련도 향상 방법, 운영 규정의 계산·구조 조항. 고친 뒤마다 쓴다.", {}),
    _fn("check_regulations", "운영 규정의 판단 조항(문장형)을 별도 심사 AI가 판정한다. 조항마다 지킴/위반/확인 필요와 근거 위치를 돌려준다. "
        f"실행마다 최대 {regulation_judge.MAX_RUNS}번이고, finish 때 판정이 없거나 그 뒤 고친 내용이 있으면 자동으로 실행된다.", {}),
    _fn("finish", "작업을 끝낸다. check_draft에 FAIL이 없어야 끝난다. 끝까지 못 고친 FAIL은 unresolved에 이유를 적는다.",
        {"summary": {"type": "string", "description": "무엇을 어떻게 만들었는지 2~3문장"},
         "unresolved": {"type": "string", "description": "고치지 못한 문제와 이유 (없으면 비움)"}},
        ["summary"]),
]


class ToolBox:
    def __init__(self, ws: Workspace, regulation_search: Callable[[str], List[Dict]], judge: Callable = None):
        self.ws = ws
        self.inp = ws.inp
        self.search = regulation_search
        self.judge = judge or regulation_judge.mock_judge
        self.rules = rulebook.load_rules(self.inp.course.business_profile, self.inp.course.training_mode)
        self.judge_rules = [r for r in self.rules if r["type"] == "판단"]
        self.judge_runs = 0
        self.judge_result: List[Dict] = []
        self.judged_at = ""  # 판정한 커리큘럼의 지문
        self.judge_warned_at = ""  # 위반 의견으로 finish를 한 번 돌려보낸 커리큘럼의 지문
        self.finished = False
        self.summary = ""
        self.unresolved = ""
        self.failed_finish = 0
        self.reg_notes: List[Dict] = []
        self.ann_search = make_announcement_search(self.inp.announcement_text)

    def call(self, name: str, args: Dict[str, Any]) -> Dict:
        fn = getattr(self, "t_" + name, None)
        if not fn:
            return {"ok": False, "error": f"없는 tool: {name}"}
        try:
            return fn(**args)
        except TypeError as e:
            return {"ok": False, "error": f"인자 오류: {e}"}
        except Exception as e:  # tool 오류는 AI에게 돌려줘 스스로 고치게 한다
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ---------- 자료 ----------

    def t_get_brief(self) -> Dict:
        i = self.inp
        return {
            "mode": "수정" if i.revise_mode else "생성",
            "draft": i.draft.model_dump(), "outputs": i.outputs,
            "course": {**i.course.model_dump(), "weeks": i.weeks},
            "learners": {"target": i.target_learners, "non_major_ratio": i.non_major_ratio,
                         "prior_experience": i.prior_experience, "goal": i.learner_goal},
            "purpose": i.purpose,
            "composition": {"project_ratio_min": i.project_ratio, "required_subjects": i.required_subjects,
                            "company_tasks": [t.model_dump() for t in i.company_tasks]},
            "announcement": {"uploaded": bool(i.announcement_text.strip()),
                             "chars": len(i.announcement_text)},
            "revision": {"request": i.revision_request, "selected_gaps": i.revision_items,
                         "must_fix_subjects": i.revision_targets} if i.revise_mode else None,
        }

    def t_get_rules(self) -> Dict:
        c = self.inp.course
        per_week = c.daily_hours * c.days_per_week
        return {
            "targets": {"total_hours": c.total_hours,
                        "project_hours_min": round(self.inp.project_ratio * c.total_hours, 1),
                        "hours_per_week": per_week,
                        "total_weeks": -(-c.total_hours // per_week) if per_week else None,
                        "period_weeks_max": self.inp.weeks or None,
                        "period_hours_max": round(self.inp.weeks * per_week) if self.inp.weeks else None,
                        "training_mode": c.training_mode,
                        "required_subjects": self.inp.required_subjects},
            "business_profile": load_profile(c.business_profile),
            "regulation_rules": [rulebook.brief(r) for r in self.rules],
            "regulation_note": "계산·구조 조항은 check_draft가, 판단 조항은 finish 때 별도 심사 AI가 확인합니다. "
                               "confirmed=false 조항은 팀 확인 전이라 어겨도 막지 않지만 지키도록 편성하세요.",
            "confirmed_rules": [r.model_dump() for r in self.inp.confirmed_rules],
        }

    def t_search_regulations(self, query: str) -> Dict:
        hits = self.search(query)
        for h in hits:
            note = {"source": h["source"], "article": h["article"]}
            if note not in self.reg_notes:
                self.reg_notes.append(note)
        return {"count": len(hits), "articles": hits}

    def t_search_announcement(self, query: str) -> Dict:
        if not self.inp.announcement_text.strip():
            return {"uploaded": False, "message": "업로드한 공고가 없음. 규정은 confirmed_rules를 보세요"}
        hits = self.ann_search(query)
        return {"uploaded": True, "count": len(hits), "passages": hits}

    def t_get_course_example(self, example_id: str = "") -> Dict:
        if not example_id:
            return {"examples": course_example_ids(), "selected_in_draft": self.inp.draft.course_examples}
        ex = load_course_example(example_id)
        return ex or {"ok": False, "error": f"과정 예시 {example_id} 없음", "examples": course_example_ids()}

    def t_get_portfolio_examples(self, keyword: str = "") -> Dict:
        items = load_portfolios()
        if keyword:
            items = [p for p in items if keyword.lower() in json.dumps(p, ensure_ascii=False).lower()] or items
        return {"portfolios": items}

    def t_get_persona_feedback(self) -> Dict:
        fb = self.inp.persona_feedback
        if not fb or not self.inp.revise_mode:
            return {"available": False, "message": "생성 모드라 페르소나 피드백이 없음"}
        return {"available": True, "scale_max": fb.scale_max, "pass_score": fb.pass_score,
                "personas": [{"persona": p.persona, "avg_score": p.avg_score} for p in fb.personas],
                "weak_subjects": checks.weak_subjects(self.inp)}

    # ---------- 작업 공간 ----------

    def t_get_draft(self, scope: str = "summary") -> Dict:
        if scope in ("", "summary"):
            return self.ws.summary()
        s = self.ws.subject(scope)
        return s.model_dump() if s else {"ok": False, "error": f"교과목 {scope} 없음"}

    def t_set_plan(self, intent_summary: str, learning_goals: List[Dict]) -> Dict:
        return self.ws.set_plan(intent_summary, learning_goals)

    def t_add_subject(self, subject: Dict, position: int = None) -> Dict:
        return self.ws.add_subject(subject, position)

    def t_update_subject(self, subject_id: str, fields: Dict, reason: str, source: str = "설계") -> Dict:
        return self.ws.update_subject(subject_id, fields, reason, source)

    def t_remove_subject(self, subject_id: str, reason: str) -> Dict:
        return self.ws.remove_subject(subject_id, reason)

    def t_move_subject(self, subject_id: str, position: int, reason: str) -> Dict:
        return self.ws.move_subject(subject_id, position, reason)

    def t_allocate_hours(self, weights: Dict, reason: str, theory_share: Dict = None) -> Dict:
        return self.ws.allocate_hours({k: float(v) for k, v in weights.items()},
                                      {k: float(v) for k, v in (theory_share or {}).items()}, reason)

    def t_set_project(self, project: Dict) -> Dict:
        return self.ws.set_project(project)

    def t_write_units(self, subject_id: str, units: List[Dict]) -> Dict:
        if not self.inp.wants_units:
            return {"ok": False, "error": "이번 결과물에는 단원 설계가 없음"}
        return self.ws.write_units(subject_id, units)

    def t_set_skill_targets(self, targets: List[Dict]) -> Dict:
        return self.ws.set_skill_targets(targets)

    def t_write_quiz(self, subject_id: str, questions: List[Dict], week: int = None) -> Dict:
        return self.ws.write_quiz(subject_id, questions, week)

    def t_set_proficiency_methods(self, methods: List[Dict]) -> Dict:
        return self.ws.set_proficiency_methods(methods)

    # ---------- 점검과 종료 ----------

    def t_check_draft(self) -> Dict:
        report = checks.check(self.ws)
        self.ws.cur.check_report = report
        fails = [i for i in report["issues"] if i["level"] == "FAIL"]
        return {"pass": report["pass"], "fail_count": len(fails), "metrics": report["metrics"],
                "issues": report["issues"]}

    def t_check_regulations(self) -> Dict:
        if not self.judge_rules:
            return {"ok": True, "message": "이 사업 프로필에는 판단 조항이 없음", "results": []}
        if self.judge_runs >= regulation_judge.MAX_RUNS:
            return {"ok": False, "error": f"판단 조항 판정은 실행마다 최대 {regulation_judge.MAX_RUNS}번. 마지막 판정 결과를 돌려줌",
                    "results": self.judge_result}
        return {"ok": True, "runs_left": regulation_judge.MAX_RUNS - self._judge(), "results": self.judge_result}

    def _judge(self) -> int:
        self.judge_result, _ = regulation_judge.run(self.judge, self.judge_rules, self.ws)
        self.judge_runs += 1
        self.judged_at = self.ws.fingerprint()
        return self.judge_runs

    def t_finish(self, summary: str, unresolved: str = "") -> Dict:
        report = checks.check(self.ws)
        self.ws.cur.check_report = report
        if not report["pass"]:
            self.failed_finish += 1
            if not (unresolved and self.failed_finish > MAX_FINISH_OVERRIDE):
                fails = [i for i in report["issues"] if i["level"] == "FAIL"]
                return {"ok": False, "error": "FAIL이 남아 있어 끝낼 수 없음. 고친 뒤 다시 finish 하세요."
                        + (" 정말 고칠 수 없으면 unresolved에 이유를 적으세요." if self.failed_finish >= MAX_FINISH_OVERRIDE else ""),
                        "fails": fails}
        # 판단 조항: 판정이 없거나 그 뒤 고쳤으면 다시 판정(최대 횟수 안에서). 위반 의견은 한 번 돌려보내 고칠 기회를 준다
        now = self.ws.fingerprint()
        if self.judge_rules and self.judged_at != now and self.judge_runs < regulation_judge.MAX_RUNS:
            self._judge()
        bad = [r for r in self.judge_result if r["verdict"] == "위반"]
        if bad and self.judge_warned_at != now and self.judged_at == now:
            self.judge_warned_at = now
            return {"ok": False, "error": "별도 심사 AI가 판단 조항 위반 의견을 냈음. 고칠 수 있으면 고친 뒤 다시 finish 하세요. "
                    "고치지 않고 다시 finish 하면 대조표에 '위반'으로 남아 강사가 확인합니다.", "violations": bad}
        self.finished, self.summary, self.unresolved = True, summary, unresolved
        return {"ok": True}

    def compliance(self) -> List[Dict]:
        """운영 규정 대조표: 코드 판정(계산·구조) + 심사 AI 판정(판단)."""
        rows = checks.check(self.ws)["regulations"]
        judged = {r["rule_id"]: r for r in self.judge_result}
        stale = self.judged_at and self.judged_at != self.ws.fingerprint()
        for row in rows:
            j = judged.get(row["id"])
            if row["by"] != "AI" or not j:
                continue
            ev = "; ".join(f"{e['location']} \"{e['quote']}\"" if e.get("quote") else e["location"] for e in j["evidence"])
            row["verdict"] = j["verdict"]
            row["evidence"] = " — ".join(filter(None, [ev, j["reason"], "판정 뒤 내용이 바뀜" if stale else ""]))
        return rows
