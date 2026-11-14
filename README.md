# 커리큘럼 에이전트 프로토타입

부트캠프 강사진용 커리큘럼 생성 · 학생 관점 검증 · 수정 도구 프로토타입.

## 실행

```bash
cp .env.example .env          # OPENAI_API_KEY 입력 (없으면 모의 응답으로 동작)
.venv/bin/pip install -r requirements.txt   # 처음 한 번
.venv/bin/uvicorn app.main:app --reload
```

브라우저에서 http://127.0.0.1:8000 접속.

운영 규정집 PDF는 `data/regulations/` 폴더에 넣으면 설문 조건(대상·과정·과목)으로 검색되어 AI 입력에 포함됩니다.
훈련 유형은 KDT로 고정이며, KDT 규정(현장 실무인재 운영규정)을 우선하고 국민내일배움카드 규정집도 참고로 함께 검색합니다.

## 화면 흐름

1. 시작: 각종 신청 서류 및 공고안 넣기 — 심사 기준까지 한 칸에(여러 파일 가능) → 문서 구성 자동 분석
   (지원 파일: 한글 .hwp·.hwpx, .pdf, .docx, .pptx, .txt, .md — 한글 파일 읽기는 app/hwp.py)
   (공고·선정 방식 / 심사 기준 / 작성할 서류 / 참고 자료) → 생성 / 검증 / 수정 선택
2. 설문(생성만): 대상, 과정 수준, 과목, 훈련 기간, 강사의 커리큘럼 설계 의도
   (설계 의도는 생성·수정·서류 작성에 쓰이고, 학생 입장 검증에는 넘기지 않습니다)
3. 모드별
   - 생성: 미리보기(커리큘럼·신청 서류 탭) → 저장 시 `나의 자료실/커리큘럼 생성안/`
     (체크한 서류를 미리보기 전에 모두 작성하고, 저장 시 미리보기한 내용을 그대로 씀)
   - 수정: (설문 없이) 커리큘럼 넣기 + 자연어 수정 요청 → 미리보기 → 저장(`수정안/`) 또는 다시 생성하기
   - 검증: (설문 없이) 커리큘럼 넣기(붙여넣기/파일/자료실) → 학생 역할별 부족한 점 → 반영할까요?(예/아니오) → 미리보기 → 저장(`검증 반영안/`) 또는 다시 검증하기

저장하면 폴더 하나에 `커리큘럼.pptx`, `커리큘럼.pdf`와 체크한 **작성할 서류마다 원본과 같은 형식의 파일**이 묶여 저장됩니다
(한글 .hwp·.hwpx 서식 → `.hwpx`, Word 서식 → `.docx`, PDF·PPT·텍스트·붙여넣기 → 편집할 수 있게 `.docx`; 한글 파일 쓰기는 app/hwpx_writer.py)
(검증 시 `검증결과.docx` 추가). 자료에 없는 사실(기관명, 금액 등)은 `[작성 필요: …]`로 남기고 노란색으로 표시합니다.
작성할 서식을 못 찾으면 기본 `사업계획서.docx`를 만듭니다.

## 구조

```
app/
  main.py              API 라우트
  schemas.py           Curriculum / Validation 등 입출력 형식 (파이프라인과의 계약)
  ai/
    base.py            AI 인터페이스 (generate / revise / validate / apply_feedback / parse)
    openai_provider.py 임시 OpenAI 구현
    mock_provider.py   API 키 없이 화면 확인용
    pipeline_provider.py  ← 자체 agent 파이프라인 연결 자리
    prompts.py         OpenAI용 프롬프트
  documents.py         신청 서류 묶음 → 문서별 분할 ([서식 N]·[첨부 N]·파일 경계 기준)
  personas.py          설문 조건 → 검증용 학생 페르소나
  regulations.py       운영 규정집 검색 (PDF 키워드 검색, 추후 DB로 교체)
  exporters.py         PPT / PDF / Word 생성
  hwpx_writer.py       작성한 서식을 한글(.hwpx)로 저장
  library.py           나의 자료실 저장·조회
generator_agent/       통합용 커리큘럼 생성 agent (tool 사용. generator_agent/README.md)
validator_agent/       학생 검증 agent (학생 페르소나 4명. validator_agent/README.md)
static/                화면 (index.html, app.js, style.css)
data/regulations/      운영 규정집 PDF
data/library/          나의 자료실
```

## 커리큘럼 생성을 생성 agent로 실행하기 (현재 설정)

`.env`의 `AI_PROVIDER=pipeline`이면 화면의 "커리큘럼 생성하기"가 생성 agent(`generator_agent/`)로 실행돼요.
과정 정보 화면의 입력이 `app/ai/agent_bridge.py`에서 생성 agent 입력으로 바뀌고, 결과 편성표가 다시 앱의 커리큘럼 형식(모듈)으로 바뀌어 미리보기·저장으로 이어져요.
시간 합계·프로젝트 비율·필수 교과목·기업 과제 연결은 코드가 점검하고, 결과의 "운영 규정·심사 기준 반영"에 점검 결과와 실행 정보(모델, 단계, 비용)가 남아요.
"학생 입장에서 검증하기"는 학생 검증 agent(`validator_agent/`)로, "수정하기"(말로 수정)와 "반영해드릴까요? → 예"는 생성 agent 수정 모드로 실행돼요.
앱 커리큘럼에는 생성 agent 원본(`agent_curriculum`)이 함께 저장돼서 수정·검증 때 개념 태그까지 그대로 써요. 신청 서식 작성만 아직 OpenAI 1회 호출이에요. `AI_PROVIDER=openai`로 바꾸면 예전 방식으로 돌아가요.

## 자체 파이프라인으로 교체하기

1. `app/ai/pipeline_provider.py`의 각 메서드에서 생성 agent / 검증 agent를 호출하고
   `schemas.py`의 `Curriculum` / `Validation` 형식 dict를 반환
2. `.env`에서 `AI_PROVIDER=pipeline`

검증 agent에는 커리큘럼 결과물과 조건만 전달되고, 생성 과정의 추론은 전달되지 않습니다.

운영 규정 DB가 준비되면 `RegulationStore.search(survey)`의 반환 형식(`RegSnippet` 목록)만 유지한 채 내부를 교체하면 됩니다.
