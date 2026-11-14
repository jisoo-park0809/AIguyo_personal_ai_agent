"""시연용 정책: API 없이 실제 학생 agent와 같은 tool을 같은 방식으로 부른다. 페르소나별로 정해진 규칙으로 움직인다."""
from typing import Callable, Dict

Act = Callable[..., Dict]


def run_mock(tb, act: Act):
    p = tb.persona
    act("get_my_profile", why="내가 누구인지 확인한다.")
    act("view_course", why="과정 전체를 훑어본다.")
    lows = 0
    for sid in tb.order:
        s = act("view_subject", {"subject_id": sid}, why="이번 교과목 내용을 본다.")
        facts = act("check_prerequisites", {"subject_id": sid}, why="선수 지식이 걱정돼 확인한다.")
        project = s["category"] == "프로젝트" or "프로젝트" in s["title"]
        und, reason, gap = "상", "", None
        if facts["i_dont_know"]:
            und, reason = "하", f"선수 지식 {facts['i_dont_know']}을 배운 적이 없음"
            gap = ("높음" if p.id == "P4" else "중간", f"선수 지식 {facts['i_dont_know']} 공백",
                   f"이 내용을 다루는 보충 시간을 {s['title']} 앞에 추가")
        elif p.id == "P1" and s["week_start"] <= 4 and not project:
            und, reason = "중", "이미 아는 기초 내용이 반복됨"
            if sid == tb.order[0]:
                gap = ("낮음", "기초 내용 반복으로 지루함", "기초 교과에 선택 과제나 심화 과제를 둠")
        elif p.id == "P2" and project:
            und, reason = "중", "팀 프로젝트 경험이 없어 시작이 막막함"
            gap = ("중간", "프로젝트 시작 안내 부족", "프로젝트 초반에 작은 팀 실습과 역할 분담 안내를 둠")
        elif p.id == "P3":
            und = "상" if s["week_start"] <= 4 else "중"
        elif p.id == "P4":
            heavy = len(s["prerequisites"]) >= 3 or "수학" in s["title"] or project
            und, reason = ("하", "처음 보는 개념이 한꺼번에 나옴") if heavy else ("중", "")
            if heavy:
                gap = ("높음", "처음 배우는 학생에게 내용이 많음", f"{s['title']}의 기초 실습 시간을 늘림")
        if s["week_start"] >= 2 and und == "하":
            act("estimate_workload", {"week": s["week_start"]}, why="이 주 학습량이 걱정된다.")
        lows += und == "하"
        quiz = {}
        if s.get("quiz_questions"):
            act("view_quiz", {"subject_id": sid}, why="이 교과목 퀴즈를 내 수준에서 풀 수 있을지 본다.")
            fit = "어려움" if und == "하" else "쉬움" if p.id == "P1" and und != "하" else "적절"
            quiz = {"quiz_fit": fit, "quiz_note": "수업을 따라가지 못해 문항이 낯섦" if fit == "어려움" else ""}
        act("write_journal", {"subject_id": sid, "understanding": und, "workload": "많음" if und == "하" else "적정",
                              "blocked_reason": reason, "feeling": "막막하다" if und == "하" else "따라갈 만하다", **quiz},
            why="수강 일지를 쓴다.")
        if gap:
            act("report_gap", {"subject_id": sid, "issue": gap[1], "reason": reason or p.cares_about,
                               "severity": gap[0], "suggestion": gap[2]}, why="이 학생에게 문제가 되는 부분을 보고한다.")
    share = lows / max(len(tb.order), 1)
    base = max(1, min(5, 5 - round(4 * share)))
    scores = {"difficulty": base, "workload": base, "flow": base,
              "career": 3 if p.id in ("P2", "P4") else 4, "motivation": base if p.id != "P1" else 3}
    completion = "불가" if share > 0.5 else "위험" if share > 0.25 else "가능"
    act("finish", {"scores": scores, "completion": completion,
                   "summary": f"이해도 '하' 교과목 {lows}개. 수료 {completion}."}, why="모든 교과목을 들었으니 평가를 끝낸다.")
