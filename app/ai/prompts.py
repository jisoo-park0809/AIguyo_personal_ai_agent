import json
from typing import Dict, List

from ..documents import KIND_LABEL
from .base import AIContext

MAX_DOC_CHARS = 15000
FORM_REF_CHARS = 6000  # 서식 작성 시 함께 넘길 공고·심사기준 분량

CURRICULUM_SCHEMA = """{
  "title": "과정명",
  "summary": "과정 개요 (3~5문장)",
  "target_summary": "훈련 대상 설명",
  "total_weeks": 정수,
  "total_hours": 정수,
  "learning_goals": ["최종 학습 목표"],
  "modules": [
    {"period": "1~2주차", "title": "모듈명", "hours": 정수,
     "objectives": ["학습 목표"], "topics": ["주요 내용"],
     "practice": "실습/과제", "prerequisites": ["선수 지식"]}
  ],
  "projects": [{"name": "프로젝트명", "period": "기간", "description": "설명"}],
  "assessment": "평가 방법",
  "compliance_notes": ["운영 규정·심사 기준을 어떻게 반영했는지"],
  "change_log": ["변경 사항 (수정 시에만)"]
}"""

VALIDATION_SCHEMA = """{
  "overall": "전체 총평 (2~3문장)",
  "personas": [
    {"persona": "페르소나 이름", "profile": "페르소나 설명",
     "score": 1~5 정수,
     "strengths": ["이 학생에게 좋은 점"],
     "gaps": [{"issue": "부족한 점", "location": "해당 모듈/주차",
               "severity": "높음|중간|낮음", "suggestion": "보완 제안"}]}
  ]
}"""

GENERATE_SYSTEM = f"""당신은 부트캠프 강사진을 돕는 커리큘럼 설계 전문가입니다.
사업계획서, 심사 기준, 운영 규정 발췌, 과정 조건을 모두 반영해 실제 운영 가능한 커리큘럼을 설계합니다.
- '강사의 커리큘럼 설계 의도'가 있으면 과정 전체의 방향을 정하는 가장 중요한 기준으로 삼으세요.
  과정 개요·학습 목표·모듈 구성·프로젝트에 의도가 드러나야 하고, 어떻게 반영했는지 compliance_notes에 한 줄 적으세요.
- 과정 조건의 총 훈련시간·기간·1일/주 훈련시간·훈련 방식을 그대로 지키세요. 모듈 시간의 합은 총 훈련시간과 같아야 합니다.
  미지정인 값만 운영 규정과 분야에 맞게 정하세요.
- 편성 조건을 반드시 지키세요: 프로젝트 시간은 프로젝트 비율 하한 이상, 필수 교과목은 모두 모듈로 포함,
  협약기업 과제는 각각 프로젝트로 연결하세요. 운영 규정 반영 내용은 compliance_notes에 적으세요.
- 비전공자 비율이 높으면 초반에 선수 지식이 필요 없는 기초 모듈을 두고, 학습자 사전 경험과 목표에 맞춰 난이도를 정하세요.
- 운영 규정(훈련 시간, 편성 기준 등)과 심사 기준을 반드시 지키고, 반영 내용을 compliance_notes에 근거 조문과 함께 적으세요.
  (예: "제4조(…요건)에 따라 프로젝트 학습을 전체 훈련시간의 20% 이상 편성")
- 모듈은 학습 순서상 선수 지식이 앞에 오도록 배치하세요.
- 반드시 아래 JSON 형식으로만 답하세요. change_log는 빈 배열로 둡니다.
{CURRICULUM_SCHEMA}"""

REVISE_SYSTEM = f"""당신은 부트캠프 커리큘럼 설계 전문가입니다. 기존 커리큘럼을 강사의 수정 요청에 맞게 고칩니다.
- 요청과 관련 없는 부분은 그대로 유지하세요.
- 운영 규정과 심사 기준을 계속 지키세요.
- change_log에 이번에 무엇을 바꿨는지 구체적으로 적으세요(이전 change_log는 지우고 새로 작성).
- 반드시 아래 JSON 형식으로만 답하세요.
{CURRICULUM_SCHEMA}"""

VALIDATE_SYSTEM = f"""당신은 이 부트캠프 커리큘럼을 받아 든 '학생'입니다. 주어진 학생 페르소나 각각이 되어 커리큘럼을 검토합니다.
- 설계자의 의도는 모릅니다. 문서에 적힌 내용만 보고 판단하세요.
- 각 페르소나 입장에서 이해하기 어려운 부분, 선수 지식 누락, 난이도 급상승, 학습량 과부하, 중복, 목표와 맞지 않는 내용,
  취업·실무 연계 부족 등을 찾아 gaps에 적으세요. 막연한 칭찬이나 지적은 피하고 위치(location)를 구체적으로 적으세요.
- 페르소나 목록에 있는 모든 페르소나를 빠짐없이, 주어진 이름 그대로 사용하세요.
- 반드시 아래 JSON 형식으로만 답하세요.
{VALIDATION_SCHEMA}"""

APPLY_SYSTEM = f"""당신은 부트캠프 커리큘럼 설계 전문가입니다. 학생 관점 검증에서 나온 보완점 목록을 커리큘럼에 반영합니다.
- 목록에 있는 보완점만 반영하고, 나머지는 유지하세요.
- 운영 규정과 심사 기준을 계속 지키세요(총 훈련 시간 등).
- change_log에 보완점별로 어떻게 반영했는지 적으세요(이전 change_log는 지우고 새로 작성).
- 반드시 아래 JSON 형식으로만 답하세요.
{CURRICULUM_SCHEMA}"""

PARSE_SYSTEM = f"""다음은 문서에서 추출한 부트캠프 커리큘럼 텍스트입니다. 아래 JSON 형식으로 구조화하세요.
- 문서에 없는 내용은 지어내지 말고 빈 값으로 두세요.
- 반드시 JSON으로만 답하세요.
{CURRICULUM_SCHEMA}"""

ANALYZE_SYSTEM = """다음은 정부 지원 훈련사업 신청 파일에서 뽑은 줄 목록("줄번호: 내용")입니다.
이 파일에는 공고문(선정 방식·절차), 별첨(심사 기준, 참고 현황 등), 신청 기관이 작성해 제출할 서식(신청서, 사업계획서,
일반현황, 동의서 등)이 하나로 합쳐져 있을 수 있습니다. 각 문서가 시작되는 줄을 찾아 나누세요.
- kind: announcement(공고·선정 방식·안내) | criteria(심사·평가 기준) | form(신청 기관이 작성해 제출하는 서식) | other(참고 자료)
- [서식 1], [첨부 1-1], [별첨 2] 같은 표시가 보통 새 문서의 시작입니다. 서식 안의 소제목은 별도 문서로 나누지 마세요.
- "===== 파일: 이름 =====" 줄은 파일 경계입니다. 파일 경계에서는 항상 새 문서가 시작되며, 경계 줄 자체는 문서 이름이 아닙니다.
- 첫 문서는 0번 줄에서 시작합니다. name은 문서 제목(예: "운영기관 지정 신청서"), summary는 한 줄 설명입니다.
- 반드시 JSON으로만 답하세요: {"parts": [{"name": "...", "kind": "...", "start_line": 정수, "summary": "..."}]}"""

FORM_SCHEMA = """{
  "title": "서식 제목",
  "blocks": [
    {"type": "heading", "text": "1. 사업 목표", "level": 1},
    {"type": "paragraph", "text": "작성 내용"},
    {"type": "bullet", "text": "항목"},
    {"type": "table", "rows": [["구분", "내용"], ["...", "..."]]}
  ]
}"""

FILL_SYSTEM = f"""당신은 국비 지원 훈련기관의 신청 서류 작성 담당자입니다. 주어진 서식(양식)을 채워 제출용 문서를 만듭니다.
- 서식의 항목 구성과 순서를 그대로 유지하세요. 작성 요령·안내 문구(※로 시작하는 줄 등)는 지우고 그 지시에 맞게 내용을 쓰세요.
- 커리큘럼, 과정 조건, 공고안, 심사 기준, 운영 규정으로 채울 수 있는 항목은 심사 기준을 의식해 구체적으로 작성하세요.
- 기관명, 대표자, 사업자등록번호, 주소, 연락처, 인력 실명, 실적 수치, 금액처럼 자료에 없는 사실은 절대 지어내지 말고
  "[작성 필요: 항목명]"으로 남기세요.
- 서명·날인·체크 칸은 원래 모양대로 두세요. 표 형태 항목은 table 블록으로 만드세요.
- 반드시 아래 JSON 형식으로만 답하세요.
{FORM_SCHEMA}"""


def _clip(text: str) -> str:
    text = (text or "").strip()
    return text if len(text) <= MAX_DOC_CHARS else text[:MAX_DOC_CHARS] + "\n...(이하 생략)"


def _n(v, unit: str = "") -> str:
    return "미지정" if v in (None, "") else f"{v:g}{unit}" if isinstance(v, float) else f"{v}{unit}"


def survey_lines(s) -> List[str]:
    """과정 조건과 학습자 정보. 생성·수정·검증·서식 작성에 모두 넘긴다."""
    lines = [
        f"- 사업 프로필: {s.funding}",
        f"- 분야·직군: {s.subject or '미지정'}",
        f"- 총 훈련시간: {_n(s.total_hours, '시간')} / 1일 {_n(s.daily_hours, '시간')} / 주 {_n(s.days_per_week, '일')}",
        f"- 기간: {_n(s.months, '개월')}" + (f" ({s.duration})" if s.duration else ""),
        f"- 훈련 방식: {s.training_mode or '미지정'}",
        f"- 훈련 대상: {s.target_desc or s.target}",
        f"- 비전공자 비율: {_n(s.non_major_ratio, '%')}",
    ]
    if s.prior_experience:
        lines.append(f"- 학습자 사전 경험: {s.prior_experience}")
    if s.learner_goal:
        lines.append(f"- 학습자 목표: {s.learner_goal}")
    return lines


def composition_lines(s) -> List[str]:
    """설계자가 정한 편성 조건. 생성·수정·서식 작성에 넘긴다."""
    lines = [f"- 프로젝트 비율 하한: {_n(s.project_ratio, '%')}",
             f"- 필수 교과목: {', '.join(s.required_subjects) or '없음'}"]
    if s.company_tasks:
        lines.append("- 협약기업 과제: " + "; ".join(f"{t.company} - {t.title}" for t in s.company_tasks))
    return lines


def format_context(ctx: AIContext, with_intent: bool = True) -> str:
    """with_intent=False: 검증(학생 입장)에는 설계자의 의도를 넘기지 않는다."""
    s = ctx.survey
    parts = ["[과정 조건]", *survey_lines(s), ""]
    if with_intent:
        parts += ["[교육 목적·설계 의도]", s.intent or "없음", ""]
        # 편성 조건은 설계자가 정한 제약이라 검증(학생 입장)에는 넘기지 않는다
        parts += ["[편성 조건]", *composition_lines(s), ""]
    if ctx.documents:
        parts += ["[신청 서류 구성]", *[f"- {d.name} ({KIND_LABEL.get(d.kind, d.kind)})" for d in ctx.documents], ""]
    parts += [
        "[각종 신청 서류 및 공고안]",
        _clip(ctx.application_docs) or "(없음)",
        "",
        "[심사 기준]",
        _clip(ctx.effective_criteria) or "(없음)",
        "",
        "[운영 규정 발췌]",
    ]
    if ctx.regulations:
        for r in ctx.regulations:
            parts.append(f"- [{r.source} {r.article} p.{r.page}] {r.text}")
    else:
        parts.append("(등록된 운영 규정 없음 - 일반적인 국비 훈련 기준을 따르세요)")
    return "\n".join(parts)


def dump(obj) -> str:
    if isinstance(obj, dict) and "agent_curriculum" in obj:  # 생성 agent 원본은 AI 프롬프트에 넣지 않는다 (같은 내용이 두 번 들어감)
        obj = {k: v for k, v in obj.items() if k not in ("agent_curriculum", "quizzes", "learning_materials")}  # 퀴즈·학습 자료도 길어서 뺀다
    return json.dumps(obj, ensure_ascii=False, indent=1)


def generate_user(ctx: AIContext) -> str:
    return format_context(ctx) + "\n\n위 조건으로 커리큘럼을 설계하세요."


def revise_user(ctx: AIContext, curriculum: Dict, instruction: str) -> str:
    return f"{format_context(ctx)}\n\n[기존 커리큘럼]\n{dump(curriculum)}\n\n[수정 요청]\n{instruction}"


def validate_user(ctx: AIContext, curriculum: Dict, personas: List[Dict]) -> str:
    plist = "\n".join(f"- {p['name']}: {p['profile']}" for p in personas)
    return f"{format_context(ctx, with_intent=False)}\n\n[학생 페르소나]\n{plist}\n\n[검토할 커리큘럼]\n{dump(curriculum)}"


def analyze_user(outline: List[Dict]) -> str:
    return "\n".join(f"{o['line']}: {o['text']}" for o in outline)


def fill_user(ctx: AIContext, curriculum: Dict, form: Dict) -> str:
    s = ctx.survey
    refs = "\n\n".join(d.text for d in ctx.documents if d.kind == "announcement")[:FORM_REF_CHARS]
    regs = "\n".join(f"- [{r.article}] {r.text[:400]}" for r in ctx.regulations)
    return "\n".join([
        "[과정 조건]", *survey_lines(s), *composition_lines(s),
        f"[교육 목적·설계 의도] {s.intent or '없음'}",
        f"[담당자] {s.owner or '[작성 필요: 담당자]'}",
        "", "[공고안 요약 자료]", refs or _clip(ctx.application_docs)[:FORM_REF_CHARS] or "(없음)",
        "", "[심사 기준]", ctx.effective_criteria[:FORM_REF_CHARS] or "(없음)",
        "", "[운영 규정 발췌]", regs or "(없음)",
        "", "[확정된 커리큘럼]", dump(curriculum),
        "", f"[작성할 서식: {form.get('name', '')}]", _clip(form.get("text", "")),
    ])


def apply_user(ctx: AIContext, curriculum: Dict, gaps: List[Dict]) -> str:
    glist = "\n".join(
        f"- [{g.get('persona', '')}/{g.get('severity', '')}] {g.get('location', '')}: {g.get('issue', '')} -> 제안: {g.get('suggestion', '')}"
        for g in gaps
    )
    return f"{format_context(ctx)}\n\n[기존 커리큘럼]\n{dump(curriculum)}\n\n[반영할 보완점]\n{glist}"
