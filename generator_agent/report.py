"""생성 결과를 사람이 읽기 쉬운 Markdown으로 바꾼다."""
from typing import Dict


def _h(x) -> str:
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


def _weeks(w: Dict) -> str:
    if not w:
        return ""
    a, b = w["week_start"], w["week_end"]
    return f"{a}" if a == b else f"{a}~{b}"


def to_markdown(cur: Dict) -> str:
    m, sch, rep = cur["meta"], cur["schedule"], cur["check_report"]
    weeks = {w["id"]: w for w in sch.get("weeks", [])}
    L = [f"# {m['course_title']}", "",
         f"- 초안: {m['draft_name']} · 담당자: {m['owner']} · 사업: {m['business_profile']} · 분야: {m.get('field', '')}",
         f"- 모드: {m['mode']} · 실행: {m['provider']} · {m['generated_at']} · {m['steps']}단계 · 종료: {m.get('stop_reason', '')}",
         f"- 비용: {m.get('cost_krw', 0):g}원 / 상한 {m.get('budget_krw', 0):g}원 · 검증 agent로 넘길 합격 기준: {cur.get('validation_criteria', {}).get('pass_score', '-')}점",
         f"- 총 {_h(sch.get('total_hours', 0))}시간 · {sch.get('total_weeks')}주 · 주 {_h(sch.get('hours_per_week', 0))}시간",
         f"- 점검: {'통과' if rep.get('pass') else '미통과'} · 프로젝트 비율 {rep.get('metrics', {}).get('project_ratio', 0):.1%}",
         "", f"**교육 목적 해석**: {cur['intent_summary']}", "", "## 학습 목표", ""]
    L += [f"- {g['id']} {g['text']}" for g in cur["learning_goals"]]
    L += ["", "## 편성표", "", "| ID | 주차 | 교과목 | 구분 | 이론 | 실습 | 프로젝트 | 합계 | 선수 개념 | 평가 |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in cur["subjects"]:
        w = weeks.get(s["id"], {})
        total = s["theory_hours"] + s["practice_hours"] + s["project_hours"]
        L.append(f"| {s['id']} | {_weeks(w)} | {s['title']} | {s['category']} | "
                 f"{_h(s['theory_hours'])} | {_h(s['practice_hours'])} | {_h(s['project_hours'])} | {_h(total)} | "
                 f"{', '.join(s['prerequisites']) or '-'} | {s['assessment'] or '-'} |")
    L += ["", "## 프로젝트", ""]
    for p in cur["projects"]:
        L.append(f"- **{p['title']}** (기업 과제 {p['company_task_id'] or '-'} · 교과목 {', '.join(p['subject_ids'])}) → 산출물: {p['portfolio_output']}")
    if any(s["units"] for s in cur["subjects"]):
        L += ["", "## 단원 설계", ""]
        for s in cur["subjects"]:
            if s["units"]:
                L.append(f"### {s['id']} {s['title']}")
                L += [f"- {u['title']} ({_h(u['hours'])}시간){' → ' + u['deliverable'] if u['deliverable'] else ''}" for u in s["units"]]
                L.append("")
    if cur.get("skill_targets"):
        L += ["", "## 숙련목표", ""]
        L += [f"- {t['id']} {t['text']} ({t['level'] or '-'} · 교과목 {', '.join(t['subject_ids'])})" for t in cur["skill_targets"]]
    if cur.get("quizzes"):
        L += ["", "## 이해도 평가 (객관식 퀴즈)", ""]
        for q in cur["quizzes"]:
            w = q["week"] or weeks.get(q["subject_id"], {}).get("week_end", "")
            L.append(f"### {q['id']} · {q['subject_id']} {next((s['title'] for s in cur['subjects'] if s['id'] == q['subject_id']), '')} · {w}주차")
            for n, qq in enumerate(q["questions"], 1):
                L.append(f"{n}. {qq['question']} ({', '.join(qq['skill_target_ids'])})")
                L += [f"   {'①②③④'[i]} {c}" for i, c in enumerate(qq["choices"])]
                L.append(f"   - 정답 {'①②③④'[qq['answer'] - 1]}{' · ' + qq['explanation'] if qq['explanation'] else ''}")
            L.append("")
    if cur.get("proficiency_methods"):
        L += ["", "## 숙련도 향상 방법", ""]
        L += [f"- **{m['method']}** ({m['timing'] or '-'}): {m['description']}" for m in cur["proficiency_methods"]]
    if cur.get("compliance"):
        L += ["", "## 운영 규정 대조표", "", "| 조항 | 내용 | 종류 | 결과 | 근거 | 확인 |", "| --- | --- | --- | --- | --- | --- |"]
        L += [f"| {r['article']} | {r['text']} | {r['type']} | {r['verdict']} | {r['evidence']} | {r['by']}{'' if r['confirmed'] else ' (팀 확인 전 조항)'} |"
              for r in cur["compliance"]]
    if rep.get("issues"):
        L += ["", "## 점검 결과", "", "| 단계 | 위치 | 내용 |", "| --- | --- | --- |"]
        L += [f"| {i['level']} | {i['where']} | {i['message']} |" for i in rep["issues"]]
    if cur["change_log"]:
        L += ["", "## 변경 기록", "", "| 대상 | 작업 | 근거 | 이유 |", "| --- | --- | --- | --- |"]
        L += [f"| {c['target']} | {c['action']} | {c['source']} | {c['reason']} |" for c in cur["change_log"]]
    if cur["regulation_notes"]:
        L += ["", "## 참고한 규정 조문", ""]
        L += [f"- {r['source']} {r['article']}" for r in cur["regulation_notes"]]
    if cur["open_items"] or m.get("unresolved"):
        L += ["", "## 남은 일", ""] + [f"- {x}" for x in cur["open_items"]]
        if m.get("unresolved"):
            L.append(f"- {m['unresolved']}")
    L += ["", f"> {m.get('summary', '')}"]
    return "\n".join(L) + "\n"
