"""실행: 프로젝트 폴더(Content_Agent)에서

    .venv/bin/python -m generator_agent --input generator_agent/data/sample_input.json
    .venv/bin/python -m generator_agent --input generator_agent/data/sample_revise_input.json --mock

--mock 이거나 OPENAI_API_KEY가 없으면 시연용 정책으로 돈다.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from .agent import DEFAULT_MAX_STEPS, GeneratorAgent
from .announcement import load_announcement
from .report import to_markdown
from .schemas import GenerationInput

HERE = Path(__file__).resolve().parent


def load_input(path: Path) -> GenerationInput:
    data = json.loads(path.read_text(encoding="utf-8"))
    inp = GenerationInput.model_validate(data)
    if inp.previous_curriculum_path and inp.previous_curriculum is None:
        prev = Path(inp.previous_curriculum_path)
        if not prev.is_absolute():
            prev = (path.parent / prev).resolve()
        inp.previous_curriculum = json.loads(prev.read_text(encoding="utf-8"))
    if inp.announcement_path and not inp.announcement_text:
        ann = Path(inp.announcement_path)
        if not ann.is_absolute():
            ann = (path.parent / ann).resolve()
        inp.announcement_text = load_announcement(ann)
    return inp


def _brief(result: dict) -> str:
    if not isinstance(result, dict):
        return str(result)[:120]
    if result.get("ok") is False:
        return "실패: " + str(result.get("error"))[:120]
    if "pass" in result:
        fails = [i["message"] for i in result.get("issues", []) if i["level"] == "FAIL"]
        return f"pass={result['pass']} FAIL {len(fails)}건" + (f" · {fails[0][:80]}" if fails else "")
    if "id" in result:
        return f"id={result['id']}" + (f" ({result['hours']:g}시간)" if "hours" in result else "")
    if "passages" in result:
        return f"공고 구절 {result['count']}개"
    if "count" in result:
        return f"조문 {result['count']}개"
    return ", ".join(list(result)[:4])


def main(argv=None):
    ap = argparse.ArgumentParser(description="커리큘럼 생성 agent")
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--out-dir", type=Path, default=HERE / "output")
    ap.add_argument("--mock", action="store_true", help="API 없이 시연용 정책으로 실행")
    ap.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    args = ap.parse_args(argv)

    try:
        from app.config import BASE_DIR  # noqa: F401  (.env 읽기)
    except Exception:
        pass
    provider = "mock" if args.mock or not os.getenv("OPENAI_API_KEY") else "openai"
    inp = load_input(args.input)

    def show(step):
        print(f"[{step['step']:02d}] {step['tool']:<22} {_brief(step['result'])}")
        if step["thought"]:
            print(f"     └ 이유: {step['thought'][:100]}")

    tracing = os.getenv("LANGSMITH_TRACING", "").lower() == "true" and os.getenv("LANGSMITH_API_KEY")
    print(f"provider={provider} · mode={'수정' if inp.revise_mode else '생성'} · {inp.course.title or inp.course.field}"
          f" · LangSmith {'기록 중 (프로젝트: ' + os.getenv('LANGSMITH_PROJECT', 'default') + ')' if tracing else '꺼짐'}")
    out = GeneratorAgent(inp, provider=provider, max_steps=args.max_steps, on_step=show).run()
    if out.get("rejected"):
        print("\n입력 점검에서 막혔어요 (AI는 부르지 않았어요):")
        for e in out["rejected"]:
            print(f"  - {e}")
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.input.stem.replace("_input", "")
    cur_path = args.out_dir / f"{stem}_curriculum.json"
    cur_path.write_text(json.dumps(out["curriculum"], ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out_dir / f"{stem}_curriculum.md").write_text(to_markdown(out["curriculum"]), encoding="utf-8")
    (args.out_dir / f"{stem}_trace.json").write_text(json.dumps(out["trace"], ensure_ascii=False, indent=2), encoding="utf-8")

    meta, rep = out["curriculum"]["meta"], out["curriculum"]["check_report"]
    print(f"\n종료: {meta['stop_reason']} · pass={rep.get('pass')} · steps={meta['steps']} · {meta['seconds']}s"
          f" · 비용 {meta['cost_krw']:g}원 / 상한 {meta['budget_krw']:g}원")
    print(f"저장: {cur_path} (+ .md, _trace.json)")
    return 0 if meta["finished"] else 1


if __name__ == "__main__":
    sys.exit(main())
