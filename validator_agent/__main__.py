"""실행: 프로젝트 폴더(Content_Agent)에서

    .venv/bin/python -m validator_agent --curriculum generator_agent/output/sample_curriculum.json
    .venv/bin/python -m validator_agent --curriculum generator_agent/output/sample_curriculum.json --mock

--request는 생성 agent 입력(과정·학습자 정보, 기본: generator_agent/data/sample_input.json)이다.
--mock 이거나 OPENAI_API_KEY가 없으면 시연용 정책으로 돈다.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from .agent import StudentValidator
from .report import to_markdown
from .schemas import ValidationInput
from .views import from_generator

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main(argv=None):
    ap = argparse.ArgumentParser(description="학생 검증 agent")
    ap.add_argument("--curriculum", required=True, type=Path, help="생성 agent 결과 (…_curriculum.json)")
    ap.add_argument("--request", type=Path, default=ROOT / "generator_agent" / "data" / "sample_input.json")
    ap.add_argument("--out-dir", type=Path, default=HERE / "output")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args(argv)

    try:
        from app.config import BASE_DIR  # noqa: F401  (.env 읽기)
    except Exception:
        pass
    provider = "mock" if args.mock or not os.getenv("OPENAI_API_KEY") else "openai"
    cur = json.loads(args.curriculum.read_text(encoding="utf-8"))
    req = json.loads(args.request.read_text(encoding="utf-8")) if args.request.exists() else {}
    inp = ValidationInput(view=from_generator(cur, req), non_major_ratio=req.get("non_major_ratio"),
                          pass_score=req.get("pass_score", 3.1), budget_krw=req.get("budget_krw", 2000),
                          rules_pass=cur.get("check_report", {}).get("pass"))
    tracing = os.getenv("LANGSMITH_TRACING", "").lower() == "true" and os.getenv("LANGSMITH_API_KEY")
    print(f"provider={provider} · 교과목 {len(inp.view.subjects)}개 · 비전공 {inp.non_major_ratio}% · 합격 기준 {inp.pass_score}"
          f" · LangSmith {'기록 중' if tracing else '꺼짐'}")
    validator = StudentValidator(inp, provider=provider, on_event=lambda m: print("  ·", m))
    result = validator.run()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.curriculum.stem.replace("_curriculum", "")
    trace = [{"persona": r.persona_id, "run": r.run, "cost_krw": round(r.cost_krw, 1), "fidelity": r.fidelity,
              "journal": r.journal, "gaps": r.gaps, "steps": r.trace} for r in validator.runs]
    (args.out_dir / f"{stem}_validation_trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out_dir / f"{stem}_validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=list), encoding="utf-8")
    (args.out_dir / f"{stem}_validation.md").write_text(to_markdown(result, cur.get("meta", {}).get("course_title", "")), encoding="utf-8")
    m = result["meta"]
    print(f"\n판정: {result['verdict']} · 가중 평균 {result['weighted_score']} (단순 {result['simple_score']}) / 기준 {result['pass_score']}"
          f" · {m['rounds']}회차 · {m['runs']}번 실행 · {m['seconds']}초 · 약 {m['cost_krw']:g}원")
    for x in result["reasons"]:
        print("  - 이유:", x)
    print(f"저장: {args.out_dir / (stem + '_validation.json')} (+ .md, _trace.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
