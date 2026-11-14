"""커리큘럼 버전 기록: data/versions/<과정 id>/v1.json, v2.json …

생성하면 v1, 수정·검증 반영할 때마다 다음 번호로 자동 저장한다. 검증 결과와 학습 자료는 그 버전에 덧붙인다.
나의 자료실 저장(PPT·PDF·신청 서류 묶음)과는 따로, 모든 버전이 남는다.
"""
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .config import VERSIONS_DIR


def _dir(lineage: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", lineage or ""):
        raise ValueError("잘못된 과정 id입니다.")
    return VERSIONS_DIR / lineage


def _path(lineage: str, version: int) -> Path:
    return _dir(lineage) / f"v{int(version)}.json"


def _numbers(lineage: str) -> List[int]:
    d = _dir(lineage)
    return sorted(int(p.stem[1:]) for p in d.glob("v*.json")) if d.exists() else []


def _write(rec: Dict) -> None:
    path = _path(rec["lineage_id"], rec["version"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")


def record(curriculum: Dict, note: str, base: Optional[Dict] = None) -> Dict:
    """새 버전으로 저장하고 버전 정보를 채운 커리큘럼을 돌려준다.

    base(수정·반영의 바탕)에 과정 id가 있으면 그 과정의 다음 번호, 없으면(예전 저장본·붙여넣기) base를 v1로 먼저 남긴다.
    """
    lineage = (base or {}).get("lineage_id") or ""
    parent = (base or {}).get("version") or None
    if base is not None and not lineage:
        lineage = uuid.uuid4().hex[:12]
        base.update(lineage_id=lineage, version=1, version_note="불러온 원본")  # 호출한 쪽에도 v1 정보를 알려 준다
        _write(_rec(dict(base), None))
        parent = 1
    lineage = lineage or uuid.uuid4().hex[:12]
    version = (max(_numbers(lineage)) if _numbers(lineage) else 0) + 1
    cur = {**curriculum, "lineage_id": lineage, "version": version, "version_note": note}
    _write(_rec(cur, parent))
    return cur


def _rec(cur: Dict, parent: Optional[int]) -> Dict:
    return {"lineage_id": cur["lineage_id"], "version": cur["version"], "note": cur.get("version_note", ""),
            "parent": parent, "created_at": datetime.now().isoformat(timespec="seconds"),
            "validation": None, "curriculum": cur}


def attach(lineage: str, version: int, **fields) -> None:
    """검증 결과 요약(validation)이나 학습 자료가 붙은 커리큘럼(curriculum)을 그 버전에 덧붙인다."""
    path = _path(lineage, version)
    if not path.exists():
        return
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec.update(fields)
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")


def list_versions(lineage: str) -> List[Dict]:
    out = []
    for n in _numbers(lineage):
        rec = json.loads(_path(lineage, n).read_text(encoding="utf-8"))
        cur = rec["curriculum"]
        out.append({"version": n, "note": rec["note"], "parent": rec["parent"], "created_at": rec["created_at"],
                    "validation": rec.get("validation"), "title": cur.get("title", ""),
                    "modules": len(cur.get("modules", [])), "materials": bool(cur.get("learning_materials"))})
    return out


def get_version(lineage: str, version: int) -> Dict:
    path = _path(lineage, version)
    if not path.exists():
        raise FileNotFoundError(f"v{version}")
    return json.loads(path.read_text(encoding="utf-8"))["curriculum"]
