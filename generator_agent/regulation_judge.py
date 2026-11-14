"""판단 조항 심사: 생성 AI와 따로 부르는 심사 AI가 조항마다 판정하고, 코드가 근거 위치·인용을 확인한다.

생성 AI는 판정을 바꿀 수 없다. 커리큘럼을 고친 뒤 다시 판정받아야 한다(최대 MAX_RUNS번).
근거를 대지 못하거나 인용이 커리큘럼에 없으면 판정을 버리고 '확인 필요'로 바꾼다.
"""
import json
from typing import Callable, Dict, List, Tuple

MAX_RUNS = 2  # 한 번 실행에서 판단 조항을 판정하는 최대 횟수

SYSTEM = """당신은 직업훈련 과정의 운영 규정 심사자입니다. 커리큘럼을 만든 사람이 아니며, 규정 위반을 찾는 역할입니다.
조항마다 아래 커리큘럼 요소만 보고 판정하세요.
- verdict: "지킴" | "위반" | "확인 필요"
- 지킴: evidence에 근거 요소 id와, 그 요소 텍스트에 실제로 있는 문장을 글자 그대로 quote로 적으세요(20~80자). 바꿔 쓰면 근거로 인정되지 않습니다.
- 위반: evidence에 문제가 있는 요소 id를 적고, reason에 무엇이 부족한지 적으세요. quote는 비워도 됩니다.
- 커리큘럼만으로 판단할 수 없으면(기관 운영·협약서 등) "확인 필요"로 하고 reason에 사람이 확인할 점을 적으세요.
- 요소에 없는 내용을 추측해 지킴으로 판정하지 마세요. 인용한 문장이 조항이 요구하는 내용을 직접 보여줄 때만 지킴입니다.
  예: '팀을 이루어'를 요구하는 조항에 개인 과제 문장을 근거로 대면 안 됩니다. 부분만 충족하면 위반 또는 확인 필요로 하고 부족한 점을 적으세요."""

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["results"],
    "properties": {"results": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["rule_id", "verdict", "evidence", "reason"],
        "properties": {
            "rule_id": {"type": "string"},
            "verdict": {"type": "string", "enum": ["지킴", "위반", "확인 필요"]},
            "evidence": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["location", "quote"],
                "properties": {"location": {"type": "string"}, "quote": {"type": "string"}}}},
            "reason": {"type": "string"},
        }}}},
}


def material(ws) -> Dict[str, str]:
    """심사 AI가 보는 커리큘럼 요소 (id → 텍스트). 설계 이유(rationale)는 주장이라 근거에서 뺀다."""
    cur, inp = ws.cur, ws.inp
    items: Dict[str, str] = {}
    for s in cur.subjects:
        items[s.id] = (f"교과목 {s.title} ({s.category}, {s.hours:g}시간). 학습목표: {'; '.join(s.goals)}. "
                       f"주요 내용: {'; '.join(s.topics)}. 평가: {s.assessment}. 협약기업 과제: {', '.join(s.company_task_ids) or '없음'}")
    for p in cur.projects:
        items[p.id] = (f"프로젝트 {p.title}. 협약기업 과제: {p.company_task_id or '없음'}. 교과목: {', '.join(p.subject_ids)}. "
                       f"내용: {p.description}. 성과물: {p.portfolio_output}")
    for t in cur.skill_targets:
        items[t.id] = f"숙련목표 {t.text} (수준: {t.level}, 교과목: {', '.join(t.subject_ids)})"
    for i, m in enumerate(cur.proficiency_methods, 1):
        items[f"M{i}"] = f"숙련도 향상 방법 {m.method}: {m.description} (시기: {m.timing})"
    for t in inp.company_tasks:
        items[t.id] = f"협약기업 과제 [{t.company}] {t.title}: {t.description} (산출물: {t.deliverable})"
    items["과정"] = (f"분야 {inp.course.field}, 총 {inp.course.total_hours}시간, 훈련 대상: {inp.target_learners}, "
                   f"교육 목적 해석: {cur.intent_summary}")
    return items


def _norm(text: str) -> str:
    return "".join(text.split()).lower()


def validate(raw: List[Dict], rules: List[Dict], items: Dict[str, str]) -> List[Dict]:
    """코드 확인: 근거 위치가 실제 요소인지, 인용이 그 요소에 실제로 있는지. 아니면 '확인 필요'로 바꾼다."""
    by_id = {r.get("rule_id"): r for r in raw}
    out = []
    for rule in rules:
        r = by_id.get(rule["id"])
        if not r:
            out.append({"rule_id": rule["id"], "verdict": "확인 필요", "evidence": [], "reason": "심사 AI가 판정하지 않음"})
            continue
        ev = [e for e in r.get("evidence", []) if e.get("location") in items]
        verdict, reason = r.get("verdict", "확인 필요"), r.get("reason", "")
        if verdict == "지킴":
            quoted = [e for e in ev if len(_norm(e.get("quote", ""))) >= 5 and _norm(e["quote"]) in _norm(items[e["location"]])]
            if not quoted:
                verdict, reason = "확인 필요", f"근거 인용을 커리큘럼에서 찾지 못함 (심사 AI 의견: 지킴 — {reason})"
            ev = quoted
        elif verdict == "위반" and not ev:
            verdict, reason = "확인 필요", f"위반 위치가 커리큘럼 요소가 아님 (심사 AI 의견: 위반 — {reason})"
        out.append({"rule_id": rule["id"], "verdict": verdict, "evidence": ev, "reason": reason})
    return out


def prompt(rules: List[Dict], items: Dict[str, str]) -> str:
    rule_lines = "\n".join(f"- {r['id']} [{r['article']}] {r['text']}" for r in rules)
    item_lines = "\n".join(f"[{k}] {v}" for k, v in items.items())
    return f"## 판정할 조항\n{rule_lines}\n\n## 커리큘럼 요소 (id는 근거 위치로 쓰세요)\n{item_lines}"


def openai_judge(client, model: str, charge: Callable[[object], None]) -> Callable[[List[Dict], Dict[str, str]], List[Dict]]:
    """OpenAI로 판정하는 함수를 만든다. charge(resp.usage)로 비용을 생성 agent 비용에 더한다."""
    def judge(rules: List[Dict], items: Dict[str, str]) -> List[Dict]:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt(rules, items)}],
            response_format={"type": "json_schema", "json_schema": {"name": "regulation_judgement", "strict": True, "schema": SCHEMA}},
        )
        if resp.usage:
            charge(resp.usage)
        return json.loads(resp.choices[0].message.content or "{}").get("results", [])
    return judge


def mock_judge(rules: List[Dict], items: Dict[str, str]) -> List[Dict]:
    return [{"rule_id": r["id"], "verdict": "확인 필요", "evidence": [], "reason": "시연 모드라 AI 판정을 하지 않음"} for r in rules]


def run(judge: Callable, rules: List[Dict], ws) -> Tuple[List[Dict], Dict[str, str]]:
    items = material(ws)
    try:
        raw = judge(rules, items)
    except Exception as e:  # 심사 AI 오류는 생성을 멈추지 않고 '확인 필요'로 남긴다
        raw = [{"rule_id": r["id"], "verdict": "확인 필요", "evidence": [], "reason": f"심사 AI 오류: {type(e).__name__}"} for r in rules]
    return validate(raw, rules, items), items
