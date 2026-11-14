"""검증할 학습자 유형 (c6f): 기본 학생 1~4(validator_agent/data/personas.json) + 운영자가 화면에서 추가한 유형."""
import json
import re
from typing import Dict, List, Optional

from validator_agent.schemas import PersonaCard, load_personas

from .config import LEARNER_TYPES_PATH


def _custom() -> List[Dict]:
    if not LEARNER_TYPES_PATH.exists():
        return []
    return json.loads(LEARNER_TYPES_PATH.read_text(encoding="utf-8"))


def _save(items: List[Dict]) -> None:
    LEARNER_TYPES_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEARNER_TYPES_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def all_types() -> List[Dict]:
    return ([{**p.model_dump(), "custom": False} for p in load_personas()]
            + [{**p, "custom": True} for p in _custom()])


def selected(ids: Optional[List[str]]) -> List[Dict]:
    """고른 유형의 카드. 고르지 않았으면 기본 학생 1~4."""
    items = all_types()
    if not ids:
        return [p for p in items if not p["custom"]]
    chosen = [p for p in items if p["id"] in ids]
    return chosen or [p for p in items if not p["custom"]]


def _split(text: str) -> List[str]:
    return [x.strip() for x in re.split(r"[,\n]", text or "") if x.strip()]


def add(form: Dict) -> Dict:
    """화면 입력으로 학습자 유형 카드를 만든다. 형식은 PersonaCard로 확인한다."""
    name = (form.get("name") or "").strip()
    if not name:
        raise ValueError("학습자 유형 이름을 입력하세요.")
    items = _custom()
    n = max([int(p["id"][1:]) for p in items if re.fullmatch(r"U\d+", p["id"])] or [0]) + 1
    major = form.get("group") == "major"
    known = ["*"] if form.get("knows_basics") else _split(form.get("known_terms", ""))
    card = PersonaCard(
        id=f"U{n}", name=f"{name} (추가)", summary=(form.get("summary") or name).strip(),
        group="major" if major else "non_major", major=major,
        knowledge=(form.get("knowledge") or "").strip() or ("기초 전부" if known == ["*"] else "입력 없음"),
        project_experience=(form.get("project_experience") or "").strip() or "없음",
        known_terms=known, unknown=_split(form.get("unknown", "")),
        cares_about=(form.get("cares_about") or "").strip(),
        review_hours_per_day=float(form.get("review_hours_per_day") or 2),
        dropout_signal=(form.get("dropout_signal") or "").strip(),
    )
    items.append(card.model_dump())
    _save(items)
    return {**card.model_dump(), "custom": True}


def remove(type_id: str) -> None:
    items = _custom()
    left = [p for p in items if p["id"] != type_id]
    if len(left) == len(items):
        raise FileNotFoundError(type_id)
    _save(left)
