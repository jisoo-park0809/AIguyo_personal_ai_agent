"""충실도 검사(c6c)와 집계·판정(c7a). AI가 아니라 코드가 계산한다 (원칙 p1)."""
from collections import Counter
from statistics import mean
from typing import Dict, List

from .schemas import SCORE_ITEMS, SCORE_LABEL, SEVERITY_WEIGHT, UNDERSTANDING_SCORE, PersonaCard, RunResult, ValidationInput
from .tools import PersonaToolBox

BORDERLINE = 0.3  # 합격 기준 ±0.3 안쪽이면 판정 횟수를 늘린다
MAX_ROUNDS = 3
LOW_SHARE_IMPOSSIBLE = 0.6  # 일지에서 이해도 '하' 비율이 이보다 크면 수료 불가
LOW_SHARE_RISK = 0.3  # 이보다 크면 수료 위험
COMPLETION_ORDER = {"불가": 0, "위험": 1, "가능": 2}


def journal_score(run: RunResult) -> float:
    """일지의 이해도로 계산한 점수 (상=5, 중=3, 하=1)."""
    vals = [UNDERSTANDING_SCORE[e["understanding"]] for e in run.journal]
    return round(mean(vals), 2) if vals else 0


def journal_completion(run: RunResult) -> str:
    n = max(len(run.journal), 1)
    low = sum(e["understanding"] == "하" for e in run.journal) / n
    return "불가" if low > LOW_SHARE_IMPOSSIBLE else "위험" if low > LOW_SHARE_RISK else "가능"


def run_score(run: RunResult) -> float:
    """페르소나 점수 = (AI가 매긴 5개 항목 평균 + 일지 이해도 점수) ÷ 2. AI 자기 평가만 믿지 않는다 (p1)."""
    return round((mean(run.scores[k] for k in SCORE_ITEMS) + journal_score(run)) / 2, 2)


def run_completion(run: RunResult) -> str:
    """수료 가능성 = AI 답과 일지 기준 중 더 나쁜 쪽."""
    return min(run.completion, journal_completion(run), key=lambda c: COMPLETION_ORDER.get(c, 2))


def fidelity(run: RunResult, tb: PersonaToolBox) -> Dict:
    """페르소나 설정과 어긋난 답을 찾는다. 너무 많이 어긋나면 이 실행은 판정에서 뺀다."""
    issues: List[str] = []
    entries = list(tb.journal.values())
    n = max(len(entries), 1)
    for e in entries:
        dont_know = tb.prereq_facts(e["subject_id"])["i_dont_know"]
        if e["understanding"] == "상" and dont_know:
            issues.append(f"{e['title']}: 모르는 선수 지식 {dont_know}이 있는데 이해도 '상'")
        if e.get("quiz_fit") == "쉬움" and (dont_know or e["understanding"] == "하"):
            issues.append(f"{e['title']}: 이해도 '{e['understanding']}'·모르는 선수 지식 {dont_know}인데 퀴즈가 '쉬움'")
    share = Counter(e["understanding"] for e in entries)
    pid = tb.persona.id
    if not tb.persona.major and not tb.persona.known_terms and share["상"] / n > 0.5:
        issues.append(f"지식이 없는 학생인데 교과목 {share['상']}/{n}개를 '상'으로 이해")
    if "*" in tb.persona.known_terms and tb.persona.project_experience.startswith("있음") and share["하"] / n > 0.5:
        issues.append(f"경험 많은 학생인데 교과목 {share['하']}/{n}개를 '하'로 이해")
    level_rule = any(x.startswith(("지식이 없는", "경험 많은")) for x in issues)
    excluded = level_rule or len(issues) >= max(2, round(0.3 * n))
    warnings = []
    if run.scores:
        gap = mean(run.scores[k] for k in SCORE_ITEMS) - journal_score(run)
        if abs(gap) >= 1.5:
            warnings.append(f"스스로 매긴 점수({mean(run.scores[k] for k in SCORE_ITEMS):.1f})와 일지 이해도 점수({journal_score(run)})가 크게 다름")
        if run.completion != run_completion(run):
            warnings.append(f"수료 '{run.completion}'라고 했지만 일지 기준으로는 '{run_completion(run)}'")
    return {"issues": issues, "warnings": warnings, "excluded": excluded, "persona": pid}


def _weights(personas: List[PersonaCard], non_major_ratio) -> Dict[str, float]:
    r = 50.0 if non_major_ratio is None else float(non_major_ratio)
    major = [p for p in personas if p.group == "major"]
    non = [p for p in personas if p.group != "major"]
    w = {}
    for p in major:
        w[p.id] = (100 - r) / len(major) if non else 100 / len(major)
    for p in non:
        w[p.id] = r / len(non) if major else 100 / len(non)
    total = sum(w.values()) or 1
    return {k: v / total for k, v in w.items()}


def aggregate(inp: ValidationInput, runs: List[RunResult]) -> Dict:
    personas = {p.id: p for p in inp.personas}
    view = {s.id: s for s in inp.view.subjects}
    valid = {pid: [r for r in runs if r.persona_id == pid and r.finished and not r.fidelity.get("excluded")]
             for pid in personas}

    per = {}
    for pid, rs in valid.items():
        p = personas[pid]
        if not rs:
            per[pid] = {"persona": p.name, "insufficient": True, "runs": 0}
            continue
        items = {k: round(mean(r.scores[k] for r in rs), 2) for k in SCORE_ITEMS}
        comp = Counter(run_completion(r) for r in rs).most_common()
        completion = sorted([c for c, k in comp if k == comp[0][1]], key=lambda c: COMPLETION_ORDER[c])[0]  # 동률이면 나쁜 쪽
        subj = {}
        for sid in view:
            vals = [UNDERSTANDING_SCORE[r.journal_map[sid]["understanding"]] for r in rs if sid in r.journal_map]
            if vals:
                notes = [r.journal_map[sid].get("blocked_reason", "") for r in rs if sid in r.journal_map]
                subj[sid] = {"score": round(mean(vals), 2), "note": next((x for x in notes if x), "")}
        per[pid] = {"persona": p.name, "summary": p.summary, "runs": len(rs),
                    "score": round(mean(run_score(r) for r in rs), 2),
                    "self_score": round(mean(items.values()), 2), "journal_score": round(mean(journal_score(r) for r in rs), 2),
                    "items": items, "completion": completion, "subjects": subj,
                    "comment": rs[-1].summary, "insufficient": False,
                    "consistency_warnings": [w for r in rs for w in r.fidelity.get("warnings", [])]}

    judged = [pid for pid in per if not per[pid]["insufficient"]]
    w = _weights([personas[pid] for pid in judged], inp.non_major_ratio)
    weighted = round(sum(per[pid]["score"] * w[pid] for pid in judged), 2) if judged else 0
    simple = round(mean(per[pid]["score"] for pid in judged), 2) if judged else 0

    reasons = []
    if inp.rules_pass is False:
        reasons.append("생성 단계 규정 점검 미통과")
    impossible = [per[pid]["persona"] for pid in judged if per[pid]["completion"] == "불가"]
    if impossible:
        reasons.append("수료 불가: " + ", ".join(impossible))
    if weighted < inp.pass_score:
        reasons.append(f"가중 평균 {weighted} < 합격 기준 {inp.pass_score}")
    if not judged:
        reasons.append("판정 근거 부족 (모든 페르소나 결과가 제외됨)")

    warnings = []
    for pid in judged:
        d = per[pid]
        if d["completion"] == "위험":
            warnings.append(f"{d['persona']}: 수료 위험")
        low = [SCORE_LABEL[k] for k, v in d["items"].items() if v <= 2]
        if low:
            warnings.append(f"{d['persona']}: {', '.join(low)} 2점 이하")
        warnings += [f"{d['persona']}: {w}" for w in dict.fromkeys(d["consistency_warnings"])]
    for pid, d in per.items():
        if d["insufficient"]:
            warnings.append(f"{d['persona']}: 설정과 다른 답이 많아 판정 근거 부족")
    hard = []
    for sid, s in view.items():
        lows = [per[pid]["persona"] for pid in judged if per[pid]["subjects"].get(sid, {}).get("score", 5) <= 1.5]
        if len(lows) >= 3:
            hard.append({"subject_id": sid, "title": s.title, "personas": lows})
            warnings.append(f"{s.title}: 학생 {len(lows)}명이 이해도 '하'")

    # 퀴즈 난이도: 교과목마다 학생별 쉬움/적절/어려움 (판정에 쓴 실행 중 마지막 회차)
    quiz_fit = []
    for sid, s in view.items():
        if not inp.view.quizzes.get(sid):
            continue
        row = {"subject_id": sid, "title": s.title, "personas": {}}
        for pid in judged:
            last = next((r.journal_map.get(sid) for r in reversed(valid[pid]) if sid in r.journal_map), None)
            if last and last.get("quiz_fit"):
                row["personas"][per[pid]["persona"]] = {"fit": last["quiz_fit"], "note": last.get("quiz_note", "")}
        fits = [v["fit"] for v in row["personas"].values()]
        if fits.count("어려움") >= 3:
            warnings.append(f"{s.title} 퀴즈: 학생 {fits.count('어려움')}명이 '어려움'")
        elif fits and all(f == "쉬움" for f in fits):
            warnings.append(f"{s.title} 퀴즈: 모든 학생이 '쉬움' (변별력 부족)")
        quiz_fit.append(row)

    merged: Dict[str, Dict] = {}
    for r in runs:
        if r.fidelity.get("excluded") or not r.finished:
            continue
        for g in r.gaps:
            m = merged.setdefault(g["subject_id"], {"subject_id": g["subject_id"], "location": g["location"],
                                                     "personas": set(), "items": []})
            m["personas"].add(personas[r.persona_id].name)
            m["items"].append({**g, "persona": personas[r.persona_id].name})
    gaps = []
    for m in merged.values():
        sev = max(SEVERITY_WEIGHT[i["severity"]] for i in m["items"])
        gaps.append({**m, "personas": sorted(m["personas"]), "priority": sev * len(m["personas"])})
    gaps.sort(key=lambda g: -g["priority"])

    return {
        "verdict": "합격" if not reasons else "불합격",
        "reasons": reasons, "pass_score": inp.pass_score,
        "weighted_score": weighted, "simple_score": simple,
        "weights": {personas[k].name: round(v, 3) for k, v in w.items()},
        "non_major_ratio": inp.non_major_ratio, "rules_pass": inp.rules_pass,
        "personas": per, "warnings": warnings, "hard_subjects": hard, "gaps": gaps, "quiz_fit": quiz_fit,
    }


def needs_more_rounds(result: Dict, rounds: int) -> bool:
    return rounds < MAX_ROUNDS and abs(result["weighted_score"] - result["pass_score"]) <= BORDERLINE


def to_persona_feedback(result: Dict) -> Dict:
    """생성 agent 수정 모드의 입력(persona_feedback) 형식."""
    return {"scale_max": 5, "pass_score": result["pass_score"], "personas": [
        {"persona": d["persona"], "avg_score": d["score"],
         "subjects": [{"subject_id": sid, "score": v["score"], "note": v["note"]} for sid, v in d["subjects"].items()]}
        for d in result["personas"].values() if not d["insufficient"]]}


def to_app_validation(result: Dict, runs: List[RunResult], personas: List[PersonaCard]) -> Dict:
    """앱의 검증 결과(Validation) 형식: 화면의 '반영해드릴까요?'에서 보완점을 고를 수 있게."""
    overall = (f"판정: {result['verdict']} (비전공자 비율 가중 평균 {result['weighted_score']} / 단순 평균 {result['simple_score']}"
               f" / 합격 기준 {result['pass_score']})")
    if result["reasons"]:
        overall += " · 이유: " + "; ".join(result["reasons"])
    if result["warnings"]:
        overall += " · 경고: " + "; ".join(result["warnings"][:5])
    reviews = []
    for p in personas:
        d = result["personas"].get(p.id, {})
        good = [r for r in runs if r.persona_id == p.id and r.finished and not r.fidelity.get("excluded")]
        strengths = list(dict.fromkeys(e["title"] for r in good for e in r.journal if e["understanding"] == "상"))[:3]
        seen, gaps = set(), []
        for r in good:
            for g in r.gaps:
                key = (g["subject_id"], g["issue"])
                if key in seen:
                    continue
                seen.add(key)
                gaps.append({"issue": g["issue"] + (f" ({g['reason']})" if g.get("reason") else ""),
                             "location": g["location"], "severity": g["severity"], "suggestion": g["suggestion"]})
        reviews.append({
            "persona": p.name,
            "profile": p.summary + (f" · 수료 {d['completion']} · 평가 {d['runs']}회" if not d.get("insufficient") else " · 판정 근거 부족"),
            "score": round(d["score"]) if not d.get("insufficient") else None,
            "strengths": [f"{t}: 이해하기 좋았음" for t in strengths] + ([d["comment"]] if d.get("comment") else []),
            "gaps": gaps,
        })
    return {"overall": overall, "personas": reviews, "verdict": result["verdict"], "score": result["weighted_score"],
            "quiz_fit": result.get("quiz_fit", [])}
