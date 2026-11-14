"""운영 규정집 검색.

프로토타입: data/regulations/ 폴더의 고시 PDF를 조문(제N조) 단위로 나누고,
설문 조건에서 뽑은 키워드로 점수를 매겨 관련 조문을 돌려준다.
나중에 DB(벡터 검색 등)로 바꿀 때는 RegulationStore.search()의 입출력만 유지하면 된다.
"""
import bisect
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple

from pypdf import PdfReader

from .schemas import RegSnippet, Survey

MAX_ARTICLE_CHARS = 1800

ARTICLE_RE = re.compile(r"(?m)^\s*(제\d+조(?:의\d+)?)\(([^()\n]{1,40})\)")

# 훈련 유형별로 우선할 고시(파일명 일부)와 조문 키워드
FUNDING_RULES = {
    "KDT": {
        "docs": ["현장 실무인재"],
        # KDT는 고시에서 '첨단산업 디지털 핵심 실무인재 양성훈련'으로 규정됨
        "terms": ["첨단산업 디지털 핵심 실무인재", "디지털", "K-디지털", "KDT", "준용"],
        # 같은 고시 안의 다른 사업 조문은 감점
        "other_programs": ["기업 맞춤형"],
    },
    "국민내일배움카드": {
        "docs": ["국민내일배움카드"],
        "terms": ["내일배움카드 훈련과정", "내일배움카드", "계좌제훈련"],
        "other_programs": ["외국어훈련", "기업 맞춤형", "첨단산업"],
    },
}

# AI에 넘길 규정 발췌 분량 상한(글자 수)
SEARCH_CHAR_BUDGET = 16000
# 최고 점수 대비 이 비율 미만인 조문은 제외
MIN_RELATIVE_SCORE = 0.2

# 커리큘럼 설계·운영과 직접 관련된 조문 키워드 (제목에 있으면 가중치 큼)
CURRICULUM_TERMS = ["요건", "실시", "훈련시간", "편성", "출결", "출석", "수료", "평가", "프로젝트",
                    "훈련생 관리", "인정", "심사", "정의", "훈련내용", "훈련 내용", "교과", "준용"]
# 행정·재정 조문은 커리큘럼 설계와 거리가 멀어 감점
ADMIN_TITLE_TERMS = ["계좌", "훈련비", "장려금", "수당", "급식", "기숙사", "회계", "재검토", "시행일",
                     "위탁계약", "이의신청", "지원단가", "끝수", "심의회", "협의회", "자료의 보관",
                     "지출내역", "운영기관에 대한 지원", "환급", "유효기간"]


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


class Article:
    __slots__ = ("source", "page", "number", "title", "text")

    def __init__(self, source: str, page: int, number: str, title: str, text: str):
        self.source, self.page, self.number, self.title, self.text = source, page, number, title, text


def _clean_pages(reader: PdfReader) -> List[str]:
    pages = [_nfc(p.extract_text() or "") for p in reader.pages]
    first = [ln.strip() for ln in pages[0].splitlines() if ln.strip()] if pages else []
    doc_title = next((ln for ln in first if "법제처" not in ln and "국가법령정보센터" not in ln), "")
    cleaned = []
    for text in pages:
        keep = []
        for ln in text.splitlines():
            s = ln.strip()
            if not s or "국가법령정보센터" in s or s.startswith("법제처") or s == doc_title or s.startswith("[시행"):
                continue
            keep.append(s)
        cleaned.append("\n".join(keep))
    return cleaned


def _split_articles(path: Path) -> List[Article]:
    pages = _clean_pages(PdfReader(str(path)))
    starts, full = [], ""
    for p in pages:
        starts.append(len(full))
        full += p + "\n"
    matches = [m for m in ARTICLE_RE.finditer(full) if "다만" not in m.group(2) and "," not in m.group(2)]
    source = _nfc(path.name)
    articles = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full)
        body = " ".join(full[m.start():end].split())
        page = bisect.bisect_right(starts, m.start())
        head = f"{m.group(1)}({m.group(2)})"
        for j in range(0, len(body), MAX_ARTICLE_CHARS):
            piece = body[j:j + MAX_ARTICLE_CHARS]
            articles.append(Article(source, page, m.group(1), m.group(2), piece if j == 0 else f"{head} (계속) {piece}"))
    return articles


def _score(a: Article, survey: Survey) -> float:
    rule = FUNDING_RULES.get(survey.funding, {"docs": [], "terms": [survey.funding]})
    title, body = a.title, a.text

    score = 0.0
    for t in CURRICULUM_TERMS:
        score += 4.0 * (t in title) + min(body.count(t), 3) * 0.5
    for t in rule["terms"]:
        score += 2.0 * (t in title) + min(body.count(t), 3) * 1.0
    if survey.level == "심화":
        score += 6.0 * ("심화" in title) + min(body.count("심화"), 3) * 1.5
    if "비전공" in survey.target:
        score += min(body.count("비전공"), 3) * 1.5
    for word in survey.subject.replace("/", " ").split():
        if len(word) >= 2:
            score += min(body.count(word), 3) * 1.0

    if any(d in a.source for d in rule["docs"]):
        score *= 1.6
    if any(t in title for t in ADMIN_TITLE_TERMS):
        score *= 0.2
    if any(t in title for t in rule.get("other_programs", [])):
        score *= 0.3
    return score


class RegulationStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self._cache_key: Tuple = ()
        self._articles: List[Article] = []

    def files(self) -> List[str]:
        return sorted(_nfc(p.name) for p in self.directory.glob("*.pdf"))

    def _load(self) -> List[Article]:
        paths = sorted(self.directory.glob("*.pdf"))
        key = tuple((p.name, p.stat().st_mtime) for p in paths)
        if key == self._cache_key:
            return self._articles
        articles: List[Article] = []
        for path in paths:
            try:
                articles += _split_articles(path)
            except Exception:
                continue
        self._cache_key, self._articles = key, articles
        return articles

    def search(self, survey: Survey, budget: int = SEARCH_CHAR_BUDGET) -> List[RegSnippet]:
        scored = [(s, a) for a in self._load() if (s := _score(a, survey)) > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        picked, used = [], 0
        cutoff = scored[0][0] * MIN_RELATIVE_SCORE if scored else 0
        for s, a in scored:
            if s < cutoff:
                break
            if used + len(a.text) > budget:
                continue
            picked.append(RegSnippet(source=a.source, page=a.page, article=f"{a.number}({a.title})", text=a.text))
            used += len(a.text)
        return picked

    def status(self) -> Dict:
        return {"files": self.files(), "articles": len(self._load())}
