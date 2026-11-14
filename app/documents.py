"""신청 서류 묶음을 문서별로 나눈다.

운영기관 공모 파일은 공고문(선정 방식) + 별첨(심사기준 등) + 서식(신청서, 사업계획서 등)이
한 파일로 합쳐져 나온다. 각 문서가 시작하는 줄 번호만 정하면(AI 또는 규칙) 나머지는 여기서 자른다.
"""
import re
from typing import Dict, List

from .schemas import DocPart

HEADING_MAX_CHARS = 60
MAX_OUTLINE_LINES = 500

# [서식 1], [ 첨부 1-1], [별지 제2호서식], <붙임 3>, 【별첨】 같은 문서 구분 표시
# 화면에서 여러 파일을 이어 붙일 때 넣는 경계 줄
FILE_RE = re.compile(r"^=====\s*파일:\s*(.+?)\s*=====$")
MARK_RE = re.compile(r"^[\[<【〔(]\s*(별지|별첨|별표|서식|양식|첨부|붙임)\s*[^\]>】〕)]{0,15}[\]>】〕)]")

KIND_WORDS = [  # 위에서부터 우선 (띄어쓰기를 지운 이름으로 비교)
    ("criteria", ["심사기준", "평가기준", "배점", "평가표", "심사항목"]),
    ("form", ["신청서", "계획서", "동의서", "확약서", "서약서", "명세서", "확인서", "현황", "요약서", "이력서"]),
    ("announcement", ["공고", "공모", "선정", "모집", "안내", "지침"]),
]
FORM_MARKS = {"서식", "양식", "별지", "첨부"}
# 별첨·붙임처럼 참고 자료일 수도 있는 표시에서는 이 단어가 있어야 작성할 서류로 본다
STRONG_FORM_WORDS = ["신청서", "계획서", "동의서", "확약서", "서약서"]

KIND_LABEL = {"announcement": "공고·선정 방식", "criteria": "심사 기준", "form": "작성할 서류", "other": "참고 자료"}


def tidy(line: str) -> str:
    """PDF 균등 배분으로 '사 업 계 획 서'처럼 벌어진 글자를 붙인다."""
    s = " ".join(line.split())
    tokens = s.split(" ")
    if len(tokens) >= 3 and sum(len(t) for t in tokens) / len(tokens) <= 1.5:
        s = s.replace(" ", "")
    return s


def classify(name: str, default: str = "other") -> str:
    flat = name.replace(" ", "")
    for kind, words in KIND_WORDS:
        if any(w in flat for w in words):
            return kind
    return default


def outline(text: str) -> List[Dict]:
    """AI에 넘길 줄 목록. 문서 구분 표시가 있는 줄을 우선하고 짧은 줄로 채운다."""
    short = [(i, tidy(ln)) for i, ln in enumerate(text.splitlines()) if 0 < len(ln.strip()) <= HEADING_MAX_CHARS]
    marked = [x for x in short if MARK_RE.match(x[1]) or classify(x[1]) != "other"]
    picked = {i for i, _ in marked[:MAX_OUTLINE_LINES]}
    for i, _ in short:
        if len(picked) >= MAX_OUTLINE_LINES:
            break
        picked.add(i)
    return [{"line": i, "text": s} for i, s in short if i in picked]


def _following(lines: List[str], i: int, n: int = 3) -> List[str]:
    return [tidy(x) for x in lines[i + 1:i + 8] if x.strip() and not FILE_RE.match(x.strip())][:n]


def heuristic_parts(text: str) -> List[Dict]:
    """규칙 기반 분할: 파일 경계와 문서 구분 표시 줄에서 새 문서가 시작된다고 본다."""
    lines = text.splitlines()
    head = _following(lines, -1)
    parts = [{"name": " ".join(head)[:60] or "공고문", "kind": classify(" ".join(head), "announcement"),
              "start_line": 0, "summary": ""}]
    for i, ln in enumerate(lines):
        s = tidy(ln)
        f = FILE_RE.match(ln.strip())
        if f and i > 0:
            # 파일 바로 뒤에 [서식] 같은 표시가 오면 그 줄에서 시작하게 둔다
            if not any(MARK_RE.match(x) for x in _following(lines, i)):
                nxt = _following(lines, i)
                parts.append({"name": (nxt[0] if nxt else f.group(1))[:60],
                              "kind": classify(" ".join(nxt[:2]) + f.group(1)), "start_line": i, "summary": f.group(1)})
            continue
        m = MARK_RE.match(s)
        if not m:
            continue
        following = _following(lines, i)
        rest = s[m.end():].strip()
        name = rest if len(rest) >= 4 else next((f for f in following if classify(f) != "other"), following[0] if following else s)
        default = "form" if m.group(1) in FORM_MARKS else "other"
        kind = classify(name, default)
        if default == "form" and kind == "announcement":
            kind = "form"
        if default == "other" and kind == "form" and not any(w in name.replace(" ", "") for w in STRONG_FORM_WORDS):
            kind = "other"
        parts.append({"name": name[:60], "kind": kind, "start_line": i, "summary": s})
    return parts


def split(text: str, parts: List[Dict]) -> List[DocPart]:
    """start_line 기준으로 원문을 잘라 DocPart 목록을 만든다."""
    lines = text.splitlines()
    clean = []
    for p in parts:
        try:
            start = int(p.get("start_line", -1))
        except (TypeError, ValueError):
            continue
        if 0 <= start < len(lines) and all(start != c["start_line"] for c in clean):
            clean.append({**p, "start_line": start})
    clean.sort(key=lambda p: p["start_line"])
    if not clean:
        return []
    clean[0]["start_line"] = 0  # 첫 문서 앞부분이 빠지지 않게

    # 각 문서가 어느 파일에서 왔는지: 시작 줄 위쪽에서 가장 가까운 파일 경계 줄
    boundaries = [(i, m.group(1)) for i, ln in enumerate(lines) if (m := FILE_RE.match(ln.strip()))]

    def source_format(start: int) -> str:
        name = next((n for i, n in reversed(boundaries) if i <= start), "")
        return name.rsplit(".", 1)[-1].lower() if "." in name else ""

    docs = []
    for idx, p in enumerate(clean):
        end = clean[idx + 1]["start_line"] if idx + 1 < len(clean) else len(lines)
        kind = p.get("kind") if p.get("kind") in KIND_LABEL else "other"
        docs.append(DocPart(
            id=f"d{idx}",
            name=tidy(str(p.get("name") or f"문서 {idx + 1}"))[:60],
            kind=kind,
            summary=str(p.get("summary") or ""),
            text="\n".join(lines[p["start_line"]:end]).strip(),
            selected=kind == "form",
            source_format=source_format(p["start_line"]),
        ))
    return docs


def criteria_text(criteria: str, documents: List[DocPart]) -> str:
    """심사 기준 칸이 비어 있으면 묶음 안에서 찾은 심사 기준 문서를 쓴다."""
    if criteria.strip():
        return criteria
    return "\n\n".join(d.text for d in documents if d.kind == "criteria")
