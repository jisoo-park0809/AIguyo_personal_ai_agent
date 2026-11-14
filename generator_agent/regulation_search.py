"""운영 규정 검색: 프로토타입 앱의 RegulationStore(app/regulations.py)를 그대로 쓴다."""
from typing import Callable, Dict, List

from .schemas import GenerationInput

SNIPPET_CHARS = 500
TOP_K = 5


def make_search(inp: GenerationInput) -> Callable[[str], List[Dict]]:
    try:
        from app.config import REGULATIONS_DIR
        from app.regulations import RegulationStore
        from app.schemas import Survey
    except Exception as e:  # 앱 밖에서 실행하면 규정 검색 없이 진행
        err = f"규정 검색을 쓸 수 없음: {e}"
        return lambda query: [{"source": "-", "article": "-", "text": err}]

    store = RegulationStore(REGULATIONS_DIR)
    text = inp.target_learners + " " + inp.purpose
    base = Survey(
        target="전공+비전공" if "비전공" in text or (inp.non_major_ratio or 0) > 0 else "전공",
        level="심화" if "심화" in text else "일반",
        funding=inp.course.business_profile if inp.course.business_profile in ("KDT", "국민내일배움카드") else "KDT",
        subject=inp.course.title or inp.course.field,
        intent=inp.purpose,
    )

    def search(query: str) -> List[Dict]:
        survey = base.model_copy(update={"subject": f"{query} {inp.course.title or inp.course.field}"})
        return [{"source": s.source, "article": s.article, "page": s.page, "text": s.text[:SNIPPET_CHARS]}
                for s in store.search(survey)[:TOP_K]]

    return search
