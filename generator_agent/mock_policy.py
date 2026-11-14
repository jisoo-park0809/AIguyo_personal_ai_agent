"""시연용 정책: API 없이 실제 agent와 같은 tool을 같은 방식으로 부른다.

AI처럼 판단하지는 않고, 과정 예시를 시간에 맞춰 늘이고 줄이는 정해진 규칙으로 움직인다.
화면·저장·점검 흐름을 확인하거나 tool을 고칠 때 비용 없이 돌려 보는 용도다.
"""
from typing import Callable, Dict, List

from .checks import matches_required

Act = Callable[..., Dict]


def _round_to(x: float, step: float) -> float:
    return max(step, round(x / step) * step)


def _split_units(template: List[Dict], hours: float, step: float) -> List[Dict]:
    units, used = [], 0.0
    for i, u in enumerate(template):
        h = hours - used if i == len(template) - 1 else _round_to(hours * u["share"], step)
        h = max(h, 0)
        used += h
        units.append({"title": u["title"], "hours": h, "activities": u.get("activities", []),
                      "deliverable": u.get("deliverable", "")})
    return [u for u in units if u["hours"] > 0]


PROJECT_UNITS = [
    {"title": "과제 분석과 기획 (요구사항·일정)", "share": 0.15, "activities": ["기업 과제 브리핑", "기획서 작성"], "deliverable": "기획서"},
    {"title": "구현 스프린트", "share": 0.6, "activities": ["스프린트 계획", "기능 구현", "코드 리뷰"], "deliverable": "스프린트 빌드"},
    {"title": "QA·출시 준비", "share": 0.15, "activities": ["테스트", "버그 수정", "빌드·배포"], "deliverable": "QA 리포트"},
    {"title": "기업 발표와 회고", "share": 0.1, "activities": ["기업 멘토 발표", "회고"], "deliverable": "발표 자료"},
]


GENERIC_UNITS = [
    {"title": "개념 이해", "share": 0.3, "activities": ["강의", "예제 따라 하기"], "deliverable": "개념 정리 노트"},
    {"title": "실습", "share": 0.5, "activities": ["실습 과제"], "deliverable": "실습 결과물"},
    {"title": "정리와 점검", "share": 0.2, "activities": ["형성평가", "회고"], "deliverable": "형성평가 결과"},
]


def run_mock(inp, act: Act):
    if inp.revise_mode and not inp.persona_feedback:
        _revise_request(inp, act)
    elif inp.revise_mode:
        _revise(inp, act)
    else:
        _generate(inp, act)


def _revise_request(inp, act: Act):
    """말로 하는 수정 요청·고른 보완점: 대상 교과목에 요청 내용을 주제로 더한다 (시연용)."""
    brief = act("get_brief", thought="수정 요청을 확인한다.")
    draft = act("get_draft", {"scope": "summary"}, thought="지금 편성을 본다.")
    targets = inp.revision_targets or [draft["subjects"][0]["id"]]
    note = inp.revision_request or "; ".join(inp.revision_items)
    for sid in targets:
        s = act("get_draft", {"scope": sid}, thought=f"{sid}의 상세를 본다.")
        if not s.get("title"):
            continue
        act("update_subject", {"subject_id": sid, "fields": {"topics": s["topics"] + [f"요청 반영: {note[:60]}"]},
                               "reason": f"강사 요청 반영: {note[:80]}", "source": "강사 요청"},
            thought=f"{sid}에 요청 내용을 반영한다.")
    report = act("check_draft", thought="반영 후 점검한다.")
    act("finish", {"summary": f"요청한 교과목 {len(targets)}개를 고쳤어요.",
                   "unresolved": "" if report["pass"] else "자동으로 해결하지 못한 FAIL이 있어요."}, thought="끝낸다.")


def _generate(inp, act: Act):
    brief = act("get_brief", thought="과정 정보부터 확인한다.")
    rules = act("get_rules", thought="시간 배분 전에 목표치와 규정을 확인한다.")
    act("search_regulations", {"query": "훈련시간 편성"}, thought="편성 관련 규정 근거를 찾는다.")
    act("search_regulations", {"query": "프로젝트 평가"}, thought="프로젝트·평가 관련 규정을 찾는다.")
    if brief["announcement"]["uploaded"]:
        act("search_announcement", {"query": "훈련시간 프로젝트"}, thought="업로드한 공고의 편성 요구사항을 확인한다.")
    ex_id = (inp.draft.course_examples or act("get_course_example")["examples"])[0]
    ex = act("get_course_example", {"example_id": ex_id}, thought="초안에 지정된 과정 예시로 구성을 잡는다.")
    pf = act("get_portfolio_examples", {"keyword": ex.get("track", "")}, thought="프로젝트 산출물 예시를 본다.")

    c = brief["course"]
    step = c["daily_hours"]  # 하루 단위로 시간을 나눈다
    act("set_plan", {
        "intent_summary": f"교육 목적({inp.purpose})을 '{ex['flow']}' 흐름으로 풀고, 협약 기업 과제를 후반 프로젝트로 배치",
        "learning_goals": ex["goals"],
    }, thought="교육 목적의 해석과 학습 목표를 먼저 정한다.")

    # 1) 일반 교과목: 프로젝트 몫을 뺀 시간을 예시의 비중대로 나눈다
    project_total = _round_to(rules["targets"]["project_hours_min"], step)
    rest = c["total_hours"] - project_total
    weight_sum = sum(s["weight"] for s in ex["subjects"])
    ids = []
    for s in ex["subjects"]:
        hours = _round_to(rest * s["weight"] / weight_sum, step)
        theory = _round_to(hours * s["theory_share"], step / 2)
        r = act("add_subject", {"subject": {
            "title": s["title"], "category": s["category"], "theory_hours": theory,
            "practice_hours": hours - theory, "project_hours": 0, "mode": c["training_mode"] if c["training_mode"] != "혼합" else "집체",
            "goals": s.get("goals", []), "topics": s["topics"], "concepts_taught": s["concepts_taught"],
            "prerequisites": s["prerequisites"], "assessment": s["assessment"], "linked_goals": s["linked_goals"],
            "rationale": s.get("rationale", "과정 예시 구성"),
        }}, thought=f"'{s['title']}'을 예시 비중({s['weight']})대로 {hours:g}시간 배정한다.")
        ids.append((r["id"], s))

    # 1-2) 필수 교과목이 예시에 없으면 추가 (선수 개념 없이, 프로젝트 앞에)
    for req in brief["composition"]["required_subjects"]:
        if not matches_required(req, [s["title"] for _, s in ids]):
            hours = _round_to(rest / max(len(ex["subjects"]), 1), step)
            r = act("add_subject", {"subject": {
                "title": req, "category": "실습", "theory_hours": _round_to(hours * 0.3, step / 2),
                "practice_hours": hours - _round_to(hours * 0.3, step / 2), "project_hours": 0,
                "mode": c["training_mode"] if c["training_mode"] != "혼합" else "집체",
                "topics": [req], "concepts_taught": [req], "prerequisites": [], "linked_goals": [ex["goals"][0]["id"]],
                "assessment": "실습 과제", "rationale": "입력의 필수 교과목",
            }}, thought=f"필수 교과목 '{req}'이 예시에 없어 추가한다.")
            ids.append((r["id"], {"title": req}))

    # 2) 협약 기업 과제마다 프로젝트 교과목 하나
    tasks = brief["composition"]["company_tasks"] or [
        {"id": "", "company": "", "title": "최종 팀 프로젝트", "description": "배운 내용을 종합한 팀 프로젝트", "deliverable": ""}]
    tpl = ex["project_template"]
    per_task = _round_to(project_total / max(len(tasks), 1), step)
    portfolios = pf["portfolios"]
    for i, t in enumerate(tasks):
        r = act("add_subject", {"subject": {
            "title": f"협약 프로젝트 {i + 1}: {t['title']}" if t["id"] else t["title"], "category": "프로젝트", "theory_hours": 0,
            "practice_hours": 0, "project_hours": per_task, "mode": c["training_mode"] if c["training_mode"] != "혼합" else "집체",
            "goals": [f"{t['company']} 과제의 요구사항을 실제 업무 흐름으로 수행"],
            "topics": ["요구사항 분석", "스프린트 개발", "QA", "기업 발표"],
            "concepts_taught": tpl["concepts_taught"], "prerequisites": tpl["prerequisites"],
            "assessment": "기업 멘토 평가 + 산출물 루브릭", "linked_goals": tpl["linked_goals"],
            "company_task_ids": [t["id"]] if t["id"] else [], "rationale": "후반에 프로젝트를 배치해 앞 교과목을 종합",
        }}, thought=f"기업 과제 '{t['title']}'를 프로젝트 교과목으로 넣는다.")
        p = portfolios[i % len(portfolios)] if portfolios else {}
        act("set_project", {"project": {
            "title": t["title"], "company_task_id": t["id"],
            "subject_ids": [r["id"]] + [sid for sid, s in ids if s.get("feeds_project")],
            "description": t.get("description", ""),
            "portfolio_output": t.get("deliverable") or p.get("title", "[작성 필요: 산출물]"),
        }}, thought="프로젝트와 기업 과제, 포트폴리오 산출물을 연결한다.")

    # 3) 비중만 정해 코드에 시간 배분을 맡기고(예시 비중, 필수 교과목 2, 프로젝트 1), 남은 차이는 점검하며 맞춘다
    draft = act("get_draft", {"scope": "summary"}, thought="시간을 나누기 전에 교과목 목록을 본다.")
    weight_of = {s["title"]: s["weight"] for s in ex["subjects"]}
    act("allocate_hours", {
        "weights": {d["id"]: (1 if d["category"] == "프로젝트" else weight_of.get(d["title"], 2)) for d in draft["subjects"]},
        "reason": "과정 예시의 비중을 따르고, 필수 교과목은 2, 기업 과제 프로젝트는 같은 비중",
    }, thought="시간 합계와 프로젝트 비율은 코드가 맞추도록 비중만 넘긴다.")
    _fix_until_pass(act)

    # 4) 단원 설계
    if inp.wants_units:
        draft = act("get_draft", {"scope": "summary"}, thought="단원을 쓰기 전에 확정된 시간을 본다.")
        templates = {s["title"]: s.get("units", []) for s in ex["subjects"]}
        for s in draft["subjects"]:
            tpl_units = templates.get(s["title"]) or (PROJECT_UNITS if s["category"] == "프로젝트" else GENERIC_UNITS)
            act("write_units", {"subject_id": s["id"], "units": _split_units(tpl_units, s["hours"], step / 2)},
                thought=f"{s['id']} 단원을 시간에 맞춰 나눈다.")
        _fix_until_pass(act)

    _assessment(act)
    report = act("check_draft", thought="마지막으로 점검한다.")
    unverified = [i["where"] for i in report["issues"] if i["level"] == "UNVERIFIED"]
    act("finish", {"summary": f"'{ex['title']}' 예시를 바탕으로 교과목 {report['metrics']['subject_count']}개, "
                              f"프로젝트 비율 {report['metrics']['project_ratio']:.0%}로 편성했어요."
                              + (f" 팀 확인 전 규정 조항 {unverified}을 확인해 주세요." if unverified else "")},
        thought="FAIL이 없으니 끝낸다.")


def _assessment(act: Act):
    """숙련목표·퀴즈·숙련도 향상 방법 (시연용: 학습 목표와 교과목 주제로 정해진 틀에 맞춰 만든다)."""
    draft = act("get_draft", {"scope": "summary"}, thought="숙련목표를 정하려고 학습 목표와 교과목을 본다.")
    subs = [act("get_draft", {"scope": d["id"]}) for d in draft["subjects"]]
    targets = []
    for i, g in enumerate(draft["learning_goals"], 1):
        linked = [s["id"] for s in subs if g["id"] in s.get("linked_goals", [])] or [subs[0]["id"]]
        targets.append({"id": f"K{i}", "text": f"{g['text']} — 과제를 혼자 수행할 수 있다", "level": "독립 수행",
                        "subject_ids": linked})
    act("set_skill_targets", {"targets": targets}, thought="학습 목표를 수료 시 할 수 있는 일로 바꿔 숙련목표를 정한다.")
    pool = [(s["id"], t) for s in subs for t in s["topics"]]
    for s in subs:
        if s["category"] == "프로젝트":
            continue
        k = next((t["id"] for t in targets if s["id"] in t["subject_ids"]), targets[0]["id"])
        others = [t for sid, t in pool if sid != s["id"] and t not in s["topics"] + s.get("concepts_taught", [])]
        questions = []
        items = list(dict.fromkeys(s["topics"] + s.get("concepts_taught", []) + s.get("goals", [])
                                   + [f"{s['title']} 핵심 개념", f"{s['title']} 실습 과제", f"{s['title']} 활용 사례"]))
        for n, topic in enumerate(items[:3]):
            wrong = list(dict.fromkeys(others[n * 3:]))[:3]
            if len(wrong) < 3:
                continue
            choices = [topic] + wrong
            questions.append({"question": f"다음 중 '{s['title']}' 교과목에서 다루는 내용은?", "choices": choices,
                              "answer": 1, "explanation": f"{topic}은 이 교과목의 주요 내용이에요.", "skill_target_ids": [k]})
        if questions:
            act("write_quiz", {"subject_id": s["id"], "questions": questions}, thought=f"{s['id']} 이해도 퀴즈를 쓴다.")
    act("set_proficiency_methods", {"methods": [
        {"method": "퀴즈 결과 기반 보충 실습", "description": "퀴즈에서 기준(3문항 중 2문항)에 못 미친 훈련생에게 같은 주에 보충 실습 과제를 준다",
         "timing": "퀴즈 다음 날"},
        {"method": "코드 리뷰와 멘토링", "description": "프로젝트 기간 중 주 1회 강사·멘토가 팀별 코드를 리뷰하고 개인별 보완점을 정리해 준다",
         "timing": "프로젝트 기간 매주"},
    ]}, thought="숙련목표에 못 미친 훈련생을 끌어올리는 방법을 정한다.")


def _fix_until_pass(act: Act, tries: int = 3):
    for _ in range(tries):
        report = act("check_draft", thought="고친 내용을 점검한다.")
        total_issue = next((i for i in report["issues"] if i["code"] == "total_hours"), None)
        if not total_issue:
            return report
        draft = act("get_draft", {"scope": "summary"}, thought="시간 합계가 다르다. 조정할 교과목을 고른다.")
        target_total = act("get_rules")["targets"]["total_hours"]
        diff = target_total - report["metrics"]["total_hours"]
        big = max((s for s in draft["subjects"] if s["category"] != "프로젝트"), key=lambda s: s["hours"])
        detail = act("get_draft", {"scope": big["id"]})
        act("update_subject", {"subject_id": big["id"], "fields": {"practice_hours": detail["practice_hours"] + diff},
                               "reason": f"총 훈련시간과 {diff:+g}시간 차이를 가장 긴 교과목 실습 시간으로 보정",
                               "source": "점검 위반"},
            thought=f"가장 긴 일반 교과목 {big['id']}의 실습 시간을 {diff:+g}시간 조정한다.")
    return report


def _revise(inp, act: Act):
    act("get_brief", thought="수정 모드다. 과정 정보를 확인한다.")
    fb = act("get_persona_feedback", thought="어느 교과목이 기준 점수 미만인지 본다.")
    draft = act("get_draft", {"scope": "summary"}, thought="지금 편성을 본다.")
    weak = fb.get("weak_subjects", {})
    step = inp.course.daily_hours
    for sid, info in weak.items():
        s = act("get_draft", {"scope": sid}, thought=f"{sid}의 상세를 본다: {info['detail']}")
        if not s.get("title"):
            continue
        notes = [i["note"] for i in info["items"] if i["note"]]
        add = step  # 하루 보충
        # 시간을 내줄 교과목: 약점이 아니고 프로젝트가 아닌 교과목 중 가장 긴 것
        donors = [d for d in act("get_draft", {"scope": "summary"})["subjects"]
                  if d["id"] not in weak and d["category"] != "프로젝트"]
        donor = max(donors, key=lambda d: d["hours"]) if donors else None
        if not donor:
            continue
        dd = act("get_draft", {"scope": donor["id"]})
        act("update_subject", {"subject_id": donor["id"],
                               "fields": {"practice_hours": dd["practice_hours"] - add,
                                          "units": _shrink_units(dd["units"], add)},
                               "reason": f"{sid} 보충 시간 {add:g}시간 확보 (가장 긴 일반 교과목에서 이동)",
                               "source": "페르소나 피드백"},
            thought=f"총 시간을 지키려고 {donor['id']}에서 {add:g}시간을 가져온다.")
        topics = s["topics"] + [f"보충: {n}" for n in notes]
        units = s["units"] + ([{"title": "보충 실습 (페르소나 피드백 반영)", "hours": add,
                                "activities": [f"{n} 보완" for n in notes] or ["기초 개념 보충"],
                                "deliverable": "보충 실습 결과물"}] if s["units"] else [])
        act("update_subject", {"subject_id": sid,
                               "fields": {"practice_hours": s["practice_hours"] + add, "topics": topics, "units": units},
                               "reason": f"{info['detail']} → 실습 {add:g}시간 보충: " + "; ".join(notes),
                               "source": "페르소나 피드백"},
            thought=f"{sid}에 보충 실습을 넣는다.")
    report = act("check_draft", thought="반영 후 점검한다.")
    act("finish", {"summary": f"기준 미만 교과목 {len(weak)}개에 보충 실습을 넣고, 같은 시간을 다른 교과목에서 가져와 총 시간을 유지했어요.",
                   "unresolved": "" if report["pass"] else "자동 보정으로 해결하지 못한 FAIL이 있어요."},
        thought="끝낸다.")


def _shrink_units(units: List[Dict], hours: float) -> List[Dict]:
    if not units:
        return units
    units = [dict(u) for u in units]
    big = max(units, key=lambda u: u["hours"])
    big["hours"] -= hours
    return [u for u in units if u["hours"] > 0]
