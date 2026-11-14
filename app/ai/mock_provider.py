"""모의 AI: API 키 없이 화면 흐름을 확인하기 위한 고정 응답."""
import copy
import re
import time
from typing import Dict, List

from ..documents import MARK_RE, heuristic_parts, tidy
from .base import AIContext, CurriculumAI

DELAY = 0.8

HEAD_RE = re.compile(r"^(\d+[.)]|[가-하][.)]|[□■○◾▪①-⑳])")
INFO_WORDS = ["기관명", "대표자", "사업자", "소재지", "주소", "연락처", "전화", "성명", "생년월일", "직위", "금액", "인원"]

SUBJECT_TRACKS = {
    "프론트엔드": ["HTML/CSS와 웹 표준", "JavaScript 핵심", "React 기초", "상태 관리와 라우팅", "TypeScript", "프론트엔드 테스트와 배포"],
    "백엔드": ["Java 문법과 객체지향", "자료구조·알고리즘", "데이터베이스와 SQL", "Spring Boot 웹 API", "JPA와 트랜잭션", "인증·보안과 배포"],
    "풀스택": ["웹 기초(HTML/CSS/JS)", "React", "Node.js와 Express", "데이터베이스 설계", "REST API와 인증", "클라우드 배포"],
    "데이터": ["Python 기초", "데이터 전처리(Pandas)", "시각화", "통계 기초", "SQL 분석", "대시보드와 리포팅"],
    "AI": ["Python 기초", "수학·통계 기초", "머신러닝", "딥러닝(PyTorch)", "LLM 활용과 RAG", "MLOps 기초"],
    "게임": ["C# 프로그래밍 기초", "게임 수학·물리 기초", "Unity 엔진 기초", "게임플레이 프로그래밍", "UI·사운드·애니메이션", "최적화와 빌드·출시"],
    "클라우드": ["Linux와 네트워크", "AWS 핵심 서비스", "Docker", "Kubernetes", "CI/CD", "모니터링과 IaC"],
}
DEFAULT_TRACK = ["개발 환경과 협업 도구", "핵심 언어 문법", "핵심 프레임워크", "데이터 다루기", "실무 기능 구현", "배포와 운영"]


def _track(subject: str) -> List[str]:
    for key, track in SUBJECT_TRACKS.items():
        if key.lower() in subject.lower():
            return track
    return DEFAULT_TRACK


def _weeks(ctx: AIContext) -> int:
    m = re.search(r"(\d+)\s*주", ctx.survey.duration)
    if m:
        return int(m.group(1))
    return 24 if ctx.survey.funding == "KDT" else 16


class MockProvider(CurriculumAI):
    name = "mock (모의 응답)"

    def generate(self, ctx: AIContext) -> Dict:
        time.sleep(DELAY)
        s = ctx.survey
        weekly_hours = 40 if s.funding == "KDT" else 20
        weeks = _weeks(ctx)
        titles = list(_track(s.subject))
        if "비전공" in s.target and s.level != "심화":
            titles.insert(0, "프로그래밍 첫걸음(비전공자 온보딩)")
        if s.level == "심화":
            titles = titles[2:] + ["고급 아키텍처와 성능 최적화"]

        project_weeks = max(4, weeks // 4)
        per = max(1, (weeks - project_weeks) // len(titles))
        modules, week = [], 1
        for t in titles:
            modules.append({
                "period": f"{week}~{week + per - 1}주차" if per > 1 else f"{week}주차",
                "title": t,
                "hours": per * weekly_hours,
                "objectives": [f"{t}의 핵심 개념을 설명할 수 있다", f"{t}를 활용해 간단한 기능을 구현할 수 있다"],
                "topics": [f"{t} 개요", f"{t} 실습", "코드 리뷰"],
                "practice": f"{t} 미니 과제",
                "prerequisites": [] if not modules else [modules[-1]["title"]],
            })
            week += per
        notes = [f"{r.article} 규정을 참고해 편성" for r in ctx.regulations[:3]] or [
            "등록된 운영 규정이 없어 일반 국비 훈련 기준으로 편성(모의)"
        ]
        return {
            "title": f"{s.subject or '소프트웨어'} {'심화 ' if s.level == '심화' else ''}부트캠프 ({s.funding})",
            "summary": f"{s.target} 대상 {weeks}주 과정입니다. 기초부터 실무 프로젝트까지 단계적으로 학습합니다."
                       + (f" 설계 의도: {s.intent}" if s.intent else "") + " (모의 응답)",
            "target_summary": f"{s.target} / {s.level} 과정",
            "total_weeks": weeks,
            "total_hours": weeks * weekly_hours,
            "learning_goals": ["실무 수준의 서비스를 팀으로 기획·개발·배포할 수 있다", "포트폴리오 프로젝트 2개 이상을 완성한다"],
            "modules": modules,
            "projects": [
                {"name": "중간 프로젝트", "period": f"{week - per}주차", "description": "개인 미니 서비스 구현"},
                {"name": "최종 팀 프로젝트", "period": f"{week}~{weeks}주차", "description": "실제 사용자 대상 서비스 개발 및 배포"},
            ],
            "assessment": "모듈별 과제(40%) + 프로젝트(50%) + 출결(10%)",
            "compliance_notes": notes,
            "change_log": [],
        }

    def revise(self, ctx: AIContext, curriculum: Dict, instruction: str) -> Dict:
        time.sleep(DELAY)
        c = copy.deepcopy(curriculum)
        c["summary"] = (c.get("summary") or "") + f"\n[수정 반영] {instruction}"
        c["change_log"] = [f"요청 반영(모의): {instruction}"]
        return c

    def validate(self, ctx: AIContext, curriculum: Dict, personas: List[Dict]) -> Dict:
        time.sleep(DELAY)
        modules = curriculum.get("modules") or [{}]
        first = modules[0].get("title", "1주차")
        last = modules[-1].get("title", "마지막 모듈")
        canned = {
            "유관 전공자": [("초반 기초 내용이 전공 수업과 겹쳐 지루할 수 있음", first, "중간", "사전 레벨 테스트로 기초 모듈을 면제하거나 심화 과제를 제공")],
            "비전공 전환자": [
                ("용어와 개발 환경 설명이 부족해 첫 주에 막힐 수 있음", first, "높음", "사전 학습 자료와 개발 환경 세팅 실습을 추가"),
                ("모듈 간 난이도가 급격히 올라감", modules[min(2, len(modules) - 1)].get("title", ""), "중간", "중간에 복습·보충 주간을 배치"),
            ],
            "취업 준비생": [("취업 지원(이력서·모의 면접) 일정이 보이지 않음", "전체 일정", "중간", "최종 프로젝트 기간에 취업 특강·모의 면접 추가")],
            "재직자·직장 병행자": [("수업 시간대와 결석 시 보강 방법이 불명확함", "운영 방식", "높음", "녹화 강의·주말 보강 운영 방식을 명시")],
            "현업 주니어(1~3년차)": [("심화 주제의 깊이가 부족함", last, "중간", "성능 튜닝·장애 대응 실습을 추가")],
        }
        reviews = []
        for p in personas:
            gaps = [{"issue": i, "location": l, "severity": sv, "suggestion": sg} for i, l, sv, sg in canned.get(p["name"], [])]
            reviews.append({
                "persona": p["name"],
                "profile": p["profile"],
                "score": 4 if len(gaps) <= 1 else 3,
                "strengths": ["프로젝트 중심 구성으로 결과물이 남는다"],
                "gaps": gaps,
            })
        return {"overall": "전반적으로 실무 중심이지만 대상별 보완이 필요합니다. (모의 응답)", "personas": reviews}

    def apply_feedback(self, ctx: AIContext, curriculum: Dict, gaps: List[Dict]) -> Dict:
        time.sleep(DELAY)
        c = copy.deepcopy(curriculum)
        for g in gaps:
            target = next((m for m in c.get("modules", []) if m.get("title") == g.get("location")), None)
            if target is not None:
                target.setdefault("topics", []).append(f"[보완] {g.get('suggestion', '')}")
            else:
                c.setdefault("compliance_notes", []).append(f"[보완] {g.get('suggestion', '')}")
        c["change_log"] = [f"[{g.get('persona', '')}] {g.get('suggestion', '')} 반영(모의)" for g in gaps]
        return c

    def parse(self, text: str) -> Dict:
        time.sleep(DELAY)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        title = lines[0][:60] if lines else "불러온 커리큘럼"
        modules = [{"period": "", "title": ln[:80], "topics": []} for ln in lines[1:21]]
        return {"title": title, "summary": "문서에서 불러온 커리큘럼 (모의 구조화)", "modules": modules}

    def analyze_documents(self, outline: List[Dict], text: str) -> Dict:
        time.sleep(DELAY)
        return {"parts": heuristic_parts(text)}

    def fill_form(self, ctx: AIContext, curriculum: Dict, form: Dict) -> Dict:
        time.sleep(DELAY)
        title = form.get("name") or "신청서"
        lines = [tidy(ln) for ln in (form.get("text") or "").splitlines() if ln.strip()]
        if lines and MARK_RE.match(lines[0]):
            lines = lines[1:]
        blocks = [{"type": "paragraph", "text": "(모의 작성본입니다. 실제 내용은 AI 연결 후 작성됩니다.)"}]
        for ln in lines[:150]:
            if ln.startswith("※") or ln == title:
                continue
            if HEAD_RE.match(ln) and len(ln) <= 40:
                blocks.append({"type": "heading", "text": ln, "level": 2})
                if any(k in ln for k in ("사업 내용", "사업내용", "훈련", "과정", "목표")):
                    blocks.append({"type": "paragraph", "text": curriculum.get("summary", "")})
            elif len(ln) <= 30 and any(w in ln.replace(" ", "") for w in INFO_WORDS):
                blocks.append({"type": "paragraph", "text": f"{ln}: [작성 필요: {ln}]"})
            else:
                blocks.append({"type": "paragraph", "text": ln})
        if "계획" in title:
            rows = [["기간", "모듈", "시간"]] + [
                [m.get("period", ""), m.get("title", ""), f"{m.get('hours') or '-'}시간"] for m in curriculum.get("modules", [])]
            blocks += [{"type": "heading", "text": "훈련과정 커리큘럼", "level": 1}, {"type": "table", "rows": rows}]
        return {"title": title, "blocks": blocks}
