"""업로드한 문서(.txt/.md/.pdf/.docx/.pptx/.hwp/.hwpx)에서 텍스트 추출."""
import io
from pathlib import Path


def extract_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext in (".txt", ".md", ".csv"):
        for enc in ("utf-8", "cp949"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="ignore")
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if ext == ".docx":
        from docx import Document
        doc = Document(io.BytesIO(data))
        lines = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                lines.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(lines)
    if ext == ".pptx":
        from pptx import Presentation
        prs = Presentation(io.BytesIO(data))
        lines = []
        for i, slide in enumerate(prs.slides, start=1):
            lines.append(f"--- 슬라이드 {i} ---")
            for shape in slide.shapes:
                if shape.has_text_frame:
                    lines.append(shape.text_frame.text)
                if getattr(shape, "has_table", False) and shape.has_table:
                    for row in shape.table.rows:
                        lines.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(lines)
    if ext == ".hwpx":
        from .hwp import hwpx_text
        return hwpx_text(data)
    if ext == ".hwp":
        from .hwp import hwp_text
        return hwp_text(data)
    raise ValueError(f"지원하지 않는 파일 형식입니다: {ext}")
