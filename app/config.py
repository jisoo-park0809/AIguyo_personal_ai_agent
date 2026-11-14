import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
REGULATIONS_DIR = Path(os.getenv("REGULATIONS_DIR", DATA_DIR / "regulations"))
LIBRARY_DIR = Path(os.getenv("LIBRARY_DIR", DATA_DIR / "library"))
# 커리큘럼 버전 기록 (과정마다 v1, v2, v3 …)
VERSIONS_DIR = Path(os.getenv("VERSIONS_DIR", DATA_DIR / "versions"))
# 운영자가 추가한 학습자 유형 (검증 학생 페르소나, c6f)
LEARNER_TYPES_PATH = Path(os.getenv("LEARNER_TYPES_PATH", DATA_DIR / "learner_types.json"))
STATIC_DIR = BASE_DIR / "static"

# 나의 자료실 폴더 구분
LIBRARY_CATEGORIES = ["커리큘럼 생성안", "수정안", "검증 반영안"]
# 이름이 바뀐 폴더: 예전 이름 -> 새 이름 (시작할 때 옮긴다)
LEGACY_CATEGORIES = {"1차 생성안": "커리큘럼 생성안"}

# 문서(.docx/.pptx)에 지정할 한글 폰트 이름
DOC_FONT_NAME = os.getenv("DOC_FONT_NAME", "맑은 고딕")

# PDF에 임베드할 한글 TTF 폰트 후보 (앞에서부터 처음 존재하는 파일 사용)
PDF_FONT_CANDIDATES = [
    os.getenv("PDF_FONT_PATH", ""),
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "C:/Windows/Fonts/malgun.ttf",
]

for _d in (REGULATIONS_DIR, LIBRARY_DIR, VERSIONS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
for _c in LIBRARY_CATEGORIES:
    (LIBRARY_DIR / _c).mkdir(parents=True, exist_ok=True)
