"""설문 조건으로 검증에 쓸 학생 페르소나를 정한다."""
from typing import Dict, List

from .schemas import Survey

MAJOR = {
    "name": "유관 전공자",
    "profile": "컴퓨터 관련 전공 졸업(예정)자. 언어·자료구조 기초는 있으나 실무 스택과 협업 경험이 부족하다. 이미 아는 내용이 길게 반복되면 지루해한다.",
}
NON_MAJOR = {
    "name": "비전공 전환자",
    "profile": "인문·경영 등 비전공 출신. 프로그래밍이 처음이라 개념 설명과 선수지식 안내가 필요하고, 진도가 갑자기 빨라지면 쉽게 낙오한다.",
}
JOB_SEEKER = {
    "name": "취업 준비생",
    "profile": "수료 후 바로 취업이 목표. 포트폴리오가 될 프로젝트, 기업 연계, 취업 지원 일정을 가장 중요하게 본다.",
}
WORKER = {
    "name": "재직자·직장 병행자",
    "profile": "직장을 다니며 수강한다. 평일 저녁·주말 등 시간 제약이 크고, 배운 내용을 실무에 바로 적용할 수 있기를 원한다.",
}
JUNIOR = {
    "name": "현업 주니어(1~3년차)",
    "profile": "현업 경험이 있어 기초 반복은 불필요하다. 심화 주제의 깊이, 실제 서비스 수준의 아키텍처·성능·운영 경험을 기대한다.",
}


def build_personas(survey: Survey) -> List[Dict[str, str]]:
    personas = [MAJOR]
    if "비전공" in survey.target:
        personas.append(NON_MAJOR)
    personas.append(WORKER if survey.funding == "국민내일배움카드" else JOB_SEEKER)
    if survey.level == "심화":
        personas.append(JUNIOR)
    return personas
