"""검증 결과를 사람이 읽기 쉬운 Markdown으로 바꾼다."""
from typing import Dict

from .schemas import SCORE_ITEMS, SCORE_LABEL


def to_markdown(r: Dict, title: str = "") -> str:
    m = r["meta"]
    L = [f"# 학생 검증 결과{(' · ' + title) if title else ''}", "",
         f"**판정: {r['verdict']}** · 비전공자 비율 가중 평균 {r['weighted_score']} / 단순 평균 {r['simple_score']} / 합격 기준 {r['pass_score']}",
         "", f"- 실행: {m['provider']} {m.get('model', '')} · {m['rounds']}회차 · 학생 agent {m['runs']}번 · {m['seconds']}초 · 약 {m['cost_krw']:g}원"
             + (" · 예산 상한으로 중단" if m["stopped_by_budget"] else ""),
         f"- 가중치 (비전공자 {r['non_major_ratio'] if r['non_major_ratio'] is not None else '미입력→50'}%): "
         + ", ".join(f"{k} {v:.0%}" for k, v in r["weights"].items()),
         f"- 생성 단계 규정 점검: {'통과' if r['rules_pass'] else '미통과' if r['rules_pass'] is False else '정보 없음'}"]
    if r["reasons"]:
        L += ["", "**불합격 이유**", ""] + [f"- {x}" for x in r["reasons"]]
    L += ["", "## 페르소나별 점수", "",
          "점수 = (스스로 매긴 5개 항목 평균 + 일지 이해도 점수) ÷ 2 · 수료 = AI 답과 일지 기준 중 더 나쁜 쪽", "",
          "| 페르소나 | 점수 | 일지 이해도 | 스스로 매긴 평균 | " + " | ".join(SCORE_LABEL[k] for k in SCORE_ITEMS) + " | 수료 | 평가 횟수 |",
          "| --- | --- | --- | --- | " + " | ".join("---" for _ in SCORE_ITEMS) + " | --- | --- |"]
    for d in r["personas"].values():
        if d["insufficient"]:
            L.append(f"| {d['persona']} | 근거 부족 | - | - | " + " | ".join("-" for _ in SCORE_ITEMS) + " | - | 0 |")
        else:
            L.append(f"| {d['persona']} | **{d['score']}** | {d['journal_score']} | {d['self_score']} | "
                     + " | ".join(f"{d['items'][k]:g}" for k in SCORE_ITEMS) + f" | {d['completion']} | {d['runs']} |")
    if r["warnings"]:
        L += ["", "## 경고", ""] + [f"- {w}" for w in r["warnings"]]
    if r["gaps"]:
        L += ["", "## 보완점 (우선순위 순)", "", "| 위치 | 페르소나 | 심각도 | 문제 | 제안 |", "| --- | --- | --- | --- | --- |"]
        for g in r["gaps"]:
            for i in g["items"]:
                L.append(f"| {g['location']} | {i['persona']} | {i['severity']} | {i['issue']} — {i['reason']} | {i['suggestion']} |")
    if r.get("quiz_fit"):
        L += ["", "## 퀴즈 난이도 (학생 수준에서)", ""]
        names_q = [d["persona"] for d in r["personas"].values() if not d["insufficient"]]
        L += ["| 교과목 | " + " | ".join(names_q) + " |", "| --- | " + " | ".join("---" for _ in names_q) + " |"]
        for row in r["quiz_fit"]:
            L.append(f"| {row['title']} | " + " | ".join(row["personas"].get(n, {}).get("fit", "-") for n in names_q) + " |")
    L += ["", "## 교과목별 이해도 (상=5, 중=3, 하=1)", ""]
    names = [d["persona"] for d in r["personas"].values() if not d["insufficient"]]
    L += ["| 교과목 | " + " | ".join(names) + " |", "| --- | " + " | ".join("---" for _ in names) + " |"]
    sids = []
    for d in r["personas"].values():
        for sid in d.get("subjects", {}):
            if sid not in sids:
                sids.append(sid)
    for sid in sids:
        cells = [f"{d['subjects'][sid]['score']:g}" if sid in d.get("subjects", {}) else "-"
                 for d in r["personas"].values() if not d["insufficient"]]
        L.append(f"| {sid} | " + " | ".join(cells) + " |")
    return "\n".join(L) + "\n"
