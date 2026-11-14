"""입력 점검: AI를 부르기 전에 잘못된 요청을 막는다 (돈을 쓰기 전에 거르는 단계, c1a)."""
from typing import List

from .rulebook import load_rules
from .schemas import GenerationInput

TRAINING_MODES = ("집체", "원격", "혼합")


def precheck(inp: GenerationInput) -> List[str]:
    c = inp.course
    errors: List[str] = []

    def need(ok: bool, message: str):
        if not ok:
            errors.append(message)

    # 필수 항목 (수정 모드는 기존 커리큘럼이 기준이라 과정 설명 항목은 비어 있어도 된다)
    if not inp.revise_mode:
        need(bool(c.business_profile.strip()), "사업 프로필이 비어 있음")
        need(bool(c.field.strip() or c.title.strip()), "분야·직군(또는 과정명)이 비어 있음")
        need(bool(inp.target_learners.strip()), "훈련 대상이 비어 있음")
        need(bool(inp.purpose.strip()), "교육 목적·설계 의도가 비어 있음")
        # 운영 규정 조항은 data/regulation_rules.json에서 읽는다 (공고는 있으면 참고)
        need(bool(load_rules(c.business_profile, c.training_mode)),
             f"사업 프로필 '{c.business_profile}'의 운영 규정 조항이 없음 (data/regulation_rules.json)")
    elif not (inp.persona_feedback or inp.revision_request.strip() or inp.revision_items):
        errors.append("수정 모드인데 수정 요청이나 반영할 보완점이 없음")

    # 값 범위
    need(c.total_hours > 0, "총 훈련시간은 0보다 커야 함")
    need(1 <= c.daily_hours <= 12, f"1일 훈련시간 {c.daily_hours}시간은 1~12 사이여야 함")
    need(1 <= c.days_per_week <= 7, f"주 훈련일 {c.days_per_week}일은 1~7 사이여야 함")
    need(c.months > 0, "기간(개월)이 비어 있음")
    need(c.training_mode in TRAINING_MODES, f"훈련 방식은 {'/'.join(TRAINING_MODES)} 중 하나여야 함")
    need(0 <= inp.project_ratio <= 1, f"프로젝트 비율 하한 {inp.project_ratio}는 0~1 사이여야 함 (예: 0.3)")
    if inp.non_major_ratio is not None:
        need(0 <= inp.non_major_ratio <= 100, f"비전공자 비율 {inp.non_major_ratio}는 0~100(%) 사이여야 함")
    need(inp.budget_krw > 0, "예산 상한은 0보다 커야 함")

    # 기간이 총 훈련시간을 담을 수 있는지
    if c.months > 0 and c.total_hours > 0:
        capacity = inp.weeks * c.days_per_week * c.daily_hours
        need(capacity >= c.total_hours,
             f"기간 {c.months:g}개월(약 {inp.weeks:g}주)에는 최대 {capacity:g}시간까지 편성 가능한데 총 훈련시간은 {c.total_hours}시간")

    # 수정 모드
    if inp.persona_feedback and not inp.previous_curriculum:
        errors.append("페르소나 점수가 있는데 기존 커리큘럼(previous_curriculum)이 없음")
    return errors
