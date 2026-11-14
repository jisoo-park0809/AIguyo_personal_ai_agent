"""사업 프로필과 예시 데이터(과정 예시, 포트폴리오 예시) 읽기."""
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

DATA = Path(__file__).resolve().parent / "data"


@lru_cache(maxsize=None)
def _profiles() -> Dict:
    return json.loads((DATA / "business_profiles.json").read_text(encoding="utf-8"))


def load_profile(key: str) -> Dict:
    return _profiles().get(key, {"name": key, "verified": False, "rules": [],
                                 "note": f"사업 프로필 '{key}'가 business_profiles.json에 없음"})


def course_example_ids() -> List[str]:
    return sorted(p.stem for p in (DATA / "examples" / "courses").glob("*.json"))


def load_course_example(cid: str) -> Dict:
    path = DATA / "examples" / "courses" / f"{cid}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_portfolios() -> List[Dict]:
    return json.loads((DATA / "examples" / "portfolios.json").read_text(encoding="utf-8"))
