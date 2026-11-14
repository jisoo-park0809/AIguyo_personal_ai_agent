# 커리큘럼 생성 agent

팀 통합 입력 구성안을 받아 편성표(와 단원 설계)를 만드는 tool 사용 agent입니다.
AI가 요청을 분석하고 상황에 맞게 tool을 고르며, 숫자 계산과 점검은 코드가 합니다(원칙 p1).
프로토타입 앱(`app/`)과는 분리돼 있고, 규정 검색(`app/regulations.py`)과 문서 읽기(`app/extract.py`)만 앱의 것을 씁니다.

## 실행

프로젝트 폴더(`Content_Agent`)에서:

```bash
# 생성 모드 (OPENAI_API_KEY가 있으면 실제 AI, 없으면 시연용 정책)
.venv/bin/python -m generator_agent --input generator_agent/data/sample_input.json

# 수정 모드: 기존 커리큘럼 + 학생 페르소나 점수
.venv/bin/python -m generator_agent --input generator_agent/data/sample_revise_input.json

# API 없이 시연 (비용 없음)
.venv/bin/python -m generator_agent --input generator_agent/data/sample_input.json --mock
```

결과는 `generator_agent/output/`에 저장돼요.

| 파일 | 내용 |
|---|---|
| `<이름>_curriculum.json` | 커리큘럼 (검증 agent가 받을 데이터, 합격 기준 포함) |
| `<이름>_curriculum.md` | 사람이 읽는 편성표·단원·점검 결과·변경 기록 |
| `<이름>_trace.json` | agent가 고른 tool, 고른 이유, 결과 전체 기록 |

| 설정 (`.env`) | 기본값 | 내용 |
|---|---|---|
| `GENERATOR_MODEL` | `.env`에 gpt-5.4-mini (없으면 `OPENAI_MODEL`) | 생성 agent 모델. 4개 모델 비교 후 gpt-5.4-mini로 정함 (아래 시험 결과) |
| `GENERATOR_MAX_STEPS` | 60 | 최대 단계 수 |
| `KRW_PER_USD` | 1400 | 비용 계산 환율. 모델 단가(캐시 할인 포함)는 `pricing.py` |

## 파이프라인

```
① 요청(입력 JSON, 공고 파일은 읽어서 텍스트로)
⓪ 입력 점검 (precheck.py, 코드) ── 실패하면 AI를 부르지 않고 이유를 돌려줌
② 요청 분석 (AI) → set_plan으로 교육 목적 해석·학습 목표 저장
③ tool 선택 (AI, why에 이유) ⇄ ④ 도구 실행 (코드)  ── 반복
⑤ 종료: finish(코드 점검 통과 + 판단 조항 심사) / 최대 단계 / 예산 상한 / AI가 멈춤
→ 출력: 커리큘럼 JSON (편성표·숙련목표·객관식 퀴즈·숙련도 향상 방법·운영 규정 대조표 + 합격 기준) → 검증 agent
```

입력 점검(⓪) 항목: 필수 항목(사업 프로필과 그 운영 규정 조항, 분야·직군, 훈련 대상, 교육 목적), 값 범위, **기간(개월)이 총 훈련시간을 담는지**(개월 × 52/12 주 × 주 훈련일 × 1일 시간), 예산.

## 입력 (`GenerationInput`, `schemas.py`)

| 묶음 | 필드 | 필수 | 쓰는 곳 |
|---|---|---|---|
| 기본 정보 | `draft.owner` 담당자, `draft.name`, `draft.memo`, `draft.course_examples` | 선택 | 결과 기록, 과정 예시 tool |
| 과정 조건 | `course.business_profile`, `field` 분야·직군, `title`(선택), `total_hours`, `daily_hours`, `days_per_week`, `months` 기간(개월), `training_mode` | ✅ | 분석, 시간 배분, 점검 |
| 학습자 | `target_learners`, `non_major_ratio`(%), `prior_experience`, `learner_goal` | ✅ (세부 선택) | 분석, 선수 개념·기초 교과 점검 |
| 교육 목적 | `purpose` | ✅ | 가장 중요한 기준 |
| 규정 | 운영 규정 조항은 `data/regulation_rules.json`에서 자동으로 읽음. `announcement_path` 공고 업로드(선택), `confirmed_rules`(CLI용 추가 규정) | 선택 | 규정 대조, 공고 검색 tool |
| 편성 조건 | `project_ratio`(하한), `required_subjects`, `company_tasks` | 선택 | 시간 배분, 점검 |
| 기준·실행 | `pass_score`(기본 3.1), `budget_krw`(기본 2,000원) | 선택 | 검증 agent로 전달, 예산 상한 |
| 수정 모드 | `persona_feedback`, `previous_curriculum(_path)` | — | 수정 모드 |

## tool 22개 (`tools.py`)

모든 tool은 `why`(지금 이 tool을 부르는 이유)를 필수로 받아요.

| 분류 | tool | 하는 일 |
|---|---|---|
| 자료 (7) | `get_brief`, `get_rules` | 입력 정리, 목표치(프로젝트 최소 시간, 기간 최대 시간 등) |
| | `search_regulations` | 운영 규정집 조문 검색 (c4b) |
| | `search_announcement` | 업로드한 공고에서 관련 구절 검색 (새로 추가) |
| | `get_course_example`, `get_portfolio_examples` | 과정 예시, 포트폴리오 예시 |
| | `get_persona_feedback` | 수정 모드: 기준 미만 교과목 |
| 작업 공간 (9) | `get_draft`, `set_plan` | 초안 보기, 교육 목적 해석·학습 목표 |
| | `add_subject`, `update_subject`, `remove_subject`, `move_subject` | 교과목 쓰고 고치기 |
| | `allocate_hours` | AI는 비중만, 코드가 시간 배분 |
| | `set_project`, `write_units` | 기업 과제 연결, 단원 설계 |
| 평가 (3) | `set_skill_targets` | 숙련목표: 교육 목적(설계 의도)·학습자 목표를 참고해 AI가 만들고 교과목에 연결 |
| | `write_quiz` | 교과목별 객관식 퀴즈 (3문항 이상, 보기 4개). 형식은 코드가 확인하고, 정답 위치는 코드가 ①~④에 고르게 섞음 |
| | `set_proficiency_methods` | 숙련도 향상 방법 (보충학습·복습 과제·코드 리뷰·멘토링 등, 언제·무엇을) |
| 점검·종료 (3) | `check_draft`, `finish` | 코드 점검, FAIL 없을 때만 종료 |
| | `check_regulations` | 판단 조항을 별도 심사 AI가 판정 (최대 2번, finish 때 자동 실행) |

점검(`checks.py`): 시간 합계, 프로젝트 비율, 훈련 방식, 선수 개념 순서, 기업 과제 연결, 학습 목표 연결, 단원 시간, 페르소나 피드백 반영, **기간**, **필수 교과목**(이름에 핵심 단어의 절반 이상), **비전공자 50% 이상이면 앞 4주 안 기초 교과**(WARN), **숙련목표·퀴즈(프로젝트가 아닌 교과목마다 3문항)·숙련도 향상 방법**(없으면 FAIL), 평가 간격 4주 초과(WARN), 운영 규정 조항.

## 운영 규정 대조 (`data/regulation_rules.json`, `rulebook.py`, `regulation_judge.py`)

규정집 PDF 2개에서 커리큘럼 편성과 관련된 조항을 뽑은 목록이에요(KDT 14개, 국민내일배움카드 6개). 사업 프로필과 훈련 방식에 맞는 조항만 써요.

| 종류 | 확인 | 예 |
|---|---|---|
| 계산 | 코드가 지표와 기준값 비교 | 1일 12시간 이하, 훈련기간 3개월~1년, 350시간 이상, 프로젝트 학습 30% 이상 |
| 구조 | 코드가 항목이 있는지·연결됐는지 | 숙련목표, 주기적 평가(퀴즈), 숙련도 향상 방법, 프로젝트 성과물, 협약기업 과제 연결 |
| 판단 | 별도 심사 AI가 판정, 코드가 근거 위치·인용을 확인 (인용이 커리큘럼에 없으면 '확인 필요') | 프로젝트 학습의 정의, 기업수요 기반 설계, 능동적 학습환경, 인정 제외 과정 |

- 단서 조항(예외)이 있는 조항을 어기면 '확인 필요'로 표시하고 막지 않아요.
- `confirmed: false`(팀 확인 전) 조항 위반은 UNVERIFIED로 표시만 해요. 팀이 원문과 맞는지 확인하면 `confirmed: true`로 바꾸세요. 그때부터 위반은 FAIL이 돼요.
- 판단 조항 위반 의견이 나오면 finish를 한 번 돌려보내 고칠 기회를 주고, 그래도 남으면 대조표에 '위반'으로 남겨 강사가 확인해요.
- 결과의 `compliance`가 대조표예요(조항, 원문, 결과, 근거, 판정 주체, 팀 확인 여부).

## 실행 흐름 보기 (LangSmith)

1. https://smith.langchain.com 에서 키를 만들고 `.env`의 `LANGSMITH_API_KEY=` 뒤에 붙여넣어요 (`LANGSMITH_TRACING=true`, `LANGSMITH_PROJECT=curriculum-generator`는 이미 있음).
2. 실행하면 첫 줄에 `LangSmith 기록 중`이 보여요.
3. LangSmith → Projects → `curriculum-generator`에서 실행을 누르면 AI 호출과 tool 호출(넣은 값, 결과, 고른 이유)이 트리로 보여요.

## 예시 데이터 (`data/`)

모두 시연용 **가상 데이터**예요.

| 파일 | 내용 |
|---|---|
| `business_profiles.json` | 사업 프로필 이름 (규정 조항은 `regulation_rules.json`) |
| `regulation_rules.json` | 운영 규정 조항 목록 (규정집 원문에서 뽑은 초안, 팀 확인 전) |
| `examples/courses/*.json`, `examples/portfolios.json` | 과정 예시 2개, 포트폴리오 예시 5개 |
| `sample_input.json`, `sample_announcement.txt` | 생성 모드 입력 (5개월·800시간·비전공 60%·필수 교과목 2개·가상 기업 2곳)과 가상 공고 |
| `sample_revise_input.json`, `examples/previous_curriculum.json` | 수정 모드 입력과 기존 커리큘럼 |

## 시험 결과 (2026-11-09)

같은 입력(게임 과정 800시간, 5개월, 비전공 60%, 필수 교과목 2개, 기업 과제 2개)으로 모델을 비교했어요. 결과물은 `output/compare/`에 있어요.

| 모델 | 단계 · 시간 | 비용 | 결과 |
|---|---|---|---|
| gpt-4o-mini | 17 · 30초 | 17.8원 | 교과목 4개뿐(필수 2 + 프로젝트 2), 학습 목표 연결 없음 → 쓸 수 없음 |
| gpt-4.1-mini | 46 · 69초 | 269원 | 교과목 10개. 두 기업 과제를 같은 교과목에 연결, 순서 어색 |
| gpt-5-mini | 36 · 165초 | 145원 | 교과목 12개. 두 기업 과제를 264시간 교과목 하나로 합침, 가장 느림 |
| **gpt-5.4-mini** | 33~35 · 약 90초 | **88.8원** (캐시 93%) | 교과목 8~9개. C# → Unity → 2D → 데이터 → QA → 기업 과제 I·II 흐름, 목표 모두 연결, WARN 없음 |

수정 모드(gpt-4o-mini): 8단계 · 6.2원 · 시간 초과를 점검으로 발견하고 allocate_hours로 스스로 보정. 입력 점검: 기간 부족·교육 목적 없음·규정 없음을 AI 호출 전에 거부.

## 시험 결과 (2026-11-11, 숙련목표·퀴즈·규정 대조 추가 후)

| 시험 | 결과 |
|---|---|
| CLI 생성 (`sample_input.json`, 단원 설계 포함) | 49단계 · 104초 · 약 168원 · 점검 통과. 숙련목표 5개, 퀴즈 9회·27문항, 숙련도 향상 방법 4개, 대조표 14개 조항 모두 지킴 |
| 앱 경로 생성 → 말로 수정 | 생성 71초 · 약 106원 (퀴즈 7회·21문항) / 수정 22초 · 약 27원 (고친 S02의 퀴즈도 다시 씀) |
| 시연 정책 · 국민내일배움카드 · 원격 · 1일 9시간 | 1일 8시간 조항 위반 → 예외 조항이 있어 '확인 필요'. 원격 과정의 월 1회 평가 조항이 추가로 적용됨 |

## 학습 자료 (`materials.py`, c9a)

앱 미리보기의 "학습 자료 만들기"로 교과목마다 **개념 설명 → 실습 → 핵심 정리** 자료를 만들어요(퀴즈는 생성 단계에서 이미 있음). 교과목마다 AI를 한 번씩 동시에 부르고, 코드가 확인해요.

- 교과목 주요 내용이 자료에 모두 나오는지
- 퀴즈 정답이 설명에 나오는지 (자료만 읽고 퀴즈를 풀 수 있는지) — 긴 문장형 정답은 바꿔 쓴 표현을 못 찾아 '확인 필요'가 나올 수 있어요
- 프로젝트 교과목은 건너뛰어요

시험(2026-11-11, gpt-5.4-mini, 교과목 8개): 25초 · 약 99원 · 점검 통과 6/8 (2개는 퀴즈 정답 문장이 설명에 그대로 없음). 저장하면 `학습자료.docx`가 함께 만들어져요.

## 알려진 한계

- 점검은 규칙(숫자·순서·연결)만 봐요. "교과목 구성이 말이 되는지"는 보지 않아서 약한 모델은 최소한으로 끝낼 수 있어요. 품질 판단은 검증 agent의 몫이에요.
- 수정 모드에서 `allocate_hours`를 쓰면 점수가 낮지 않은 교과목의 시간도 함께 바뀔 수 있어요.
- 사전 경험·포트폴리오의 웹 검색(팀 결정)은 아직 없어요. 지금은 입력값과 예시 데이터를 써요.
- 공고는 검색만 하고 규정을 자동으로 뽑지 않아요(팀 결정). 운영 규정 조항 목록은 아직 팀 확인 전이라 위반해도 막지 않아요.
- 판단 조항 심사 AI는 너그럽게 판정하는 편이에요(예: 보충학습 문장을 '능동적 학습환경'의 근거로 댐). 강사 판단과 맞춰 보는 보정이 필요해요.
- 별표(전략산업직종, 학습관리시스템 요건 등)를 가리키는 조항은 별표 문서가 없어 목록에 넣지 않았어요.
- 학습 자료(c9a)와 신청 서류(c10a·c10b) 생성은 이 agent에 없어요.
