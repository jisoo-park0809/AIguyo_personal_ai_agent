"""업로드한 공고 읽기와 검색.

공고에서 규정을 자동으로 뽑지는 않는다(팀 결정). agent가 필요한 부분을 찾아 읽고, 규정은 직접 입력한 것만 점검한다.
"""
from pathlib import Path
from typing import Callable, Dict, List

CHUNK_LINES = 4  # 검색 단위: 연속된 줄 몇 개
TOP_K = 5


def load_announcement(path: Path) -> str:
    try:
        from app.extract import extract_text  # hwp·hwpx·pdf·docx·txt를 읽는 앱의 추출기
    except Exception:
        return path.read_text(encoding="utf-8", errors="ignore")
    return extract_text(path.name, path.read_bytes())


def make_announcement_search(text: str) -> Callable[[str], List[Dict]]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    chunks = [(i + 1, " ".join(lines[i:i + CHUNK_LINES])) for i in range(0, len(lines), CHUNK_LINES // 2 or 1)]

    def search(query: str) -> List[Dict]:
        words = [w for w in query.lower().split() if len(w) >= 2] or [query.lower()]
        scored = []
        for line_no, chunk in chunks:
            low = chunk.lower()
            score = sum(low.count(w) for w in words)
            if score:
                scored.append((score, line_no, chunk))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [{"line": n, "text": t[:400]} for _, n, t in scored[:TOP_K]]

    return search
