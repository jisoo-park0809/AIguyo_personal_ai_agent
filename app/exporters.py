"""커리큘럼을 PPT / PDF / Word(사업계획서, 검증 결과)로 내보낸다."""
import os
import re
from pathlib import Path
from typing import List, Optional

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt as DocxPt
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

from .config import DOC_FONT_NAME, PDF_FONT_CANDIDATES
from .schemas import Curriculum, FilledForm, FormBlock, RegSnippet, Validation

ACCENT = RGBColor(0x2F, 0x5B, 0xEA)
INK = RGBColor(0x1F, 0x23, 0x2B)
MUTED = RGBColor(0x5F, 0x66, 0x73)


def _hours(v: Optional[int]) -> str:
    return f"{v}시간" if v else "-"


# ---------------- PPT ----------------

def _textbox(slide, x, y, w, h, lines: List[str], size=16, color=INK, bullet=False):
    tf = slide.shapes.add_textbox(x, y, w, h).text_frame
    tf.word_wrap = True
    for i, line in enumerate(lines or ["-"]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        run = p.add_run()
        run.text = f"• {line}" if bullet else line
        run.font.size = Pt(size)
        run.font.color.rgb = color
        run.font.name = DOC_FONT_NAME
        p.space_after = Pt(6)
    return tf


def _slide(prs, title: str):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bar = slide.shapes.add_shape(1, 0, 0, prs.slide_width, Inches(0.12))
    bar.fill.solid()
    bar.fill.fore_color.rgb = ACCENT
    bar.line.fill.background()
    _textbox(slide, Inches(0.6), Inches(0.35), Inches(12), Inches(0.8), [title], size=28)
    return slide


def build_pptx(c: Curriculum, path: Path) -> None:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    body_x, body_y, body_w, body_h = Inches(0.6), Inches(1.4), Inches(12.1), Inches(5.6)

    cover = prs.slides.add_slide(prs.slide_layouts[6])
    block = cover.shapes.add_shape(1, Inches(0.8), Inches(2.2), Inches(1.2), Inches(0.12))
    block.fill.solid()
    block.fill.fore_color.rgb = ACCENT
    block.line.fill.background()
    _textbox(cover, Inches(0.8), Inches(2.6), Inches(11.5), Inches(1.2), [c.title], size=40)
    _textbox(cover, Inches(0.8), Inches(3.8), Inches(11.5), Inches(1.0),
             [f"{c.target_summary}  |  {c.total_weeks or '-'}주  |  {_hours(c.total_hours)}"], size=18, color=MUTED)

    s = _slide(prs, "과정 개요")
    _textbox(s, body_x, body_y, body_w, Inches(2.2), [c.summary], size=18)
    _textbox(s, body_x, Inches(3.8), body_w, Inches(3), ["최종 학습 목표"] , size=18, color=ACCENT)
    _textbox(s, body_x, Inches(4.3), body_w, Inches(2.8), c.learning_goals, size=16, bullet=True)

    rows_per_slide = 9
    for start in range(0, max(len(c.modules), 1), rows_per_slide):
        chunk = c.modules[start:start + rows_per_slide]
        s = _slide(prs, "커리큘럼 한눈에 보기" + (" (계속)" if start else ""))
        table = s.shapes.add_table(len(chunk) + 1, 4, body_x, body_y, body_w, Inches(0.5) * (len(chunk) + 1)).table
        widths = [Inches(1.8), Inches(4.0), Inches(1.3), Inches(5.0)]
        for i, w in enumerate(widths):
            table.columns[i].width = w
        for i, head in enumerate(["기간", "모듈", "시간", "주요 내용"]):
            table.cell(0, i).text = head
        for r, m in enumerate(chunk, start=1):
            for col, val in enumerate([m.period, m.title, _hours(m.hours), ", ".join(m.topics[:4])]):
                table.cell(r, col).text = val
        for row in table.rows:
            for cell in row.cells:
                for p in cell.text_frame.paragraphs:
                    for run in p.runs:
                        run.font.size = Pt(13)
                        run.font.name = DOC_FONT_NAME

    for m in c.modules:
        s = _slide(prs, f"{m.period}  {m.title}".strip())
        half = Inches(5.9)
        _textbox(s, body_x, body_y, half, Inches(0.5), ["학습 목표"], size=16, color=ACCENT)
        _textbox(s, body_x, Inches(1.9), half, Inches(2.2), m.objectives, size=14, bullet=True)
        _textbox(s, body_x, Inches(4.2), half, Inches(0.5), ["주요 내용"], size=16, color=ACCENT)
        _textbox(s, body_x, Inches(4.7), half, Inches(2.4), m.topics, size=14, bullet=True)
        rx = Inches(6.9)
        _textbox(s, rx, body_y, half, Inches(0.5), ["실습 / 과제"], size=16, color=ACCENT)
        _textbox(s, rx, Inches(1.9), half, Inches(1.6), [m.practice or "-"], size=14)
        _textbox(s, rx, Inches(3.6), half, Inches(0.5), ["선수 지식"], size=16, color=ACCENT)
        _textbox(s, rx, Inches(4.1), half, Inches(1.4), m.prerequisites or ["없음"], size=14, bullet=True)
        _textbox(s, rx, Inches(5.6), half, Inches(0.5), [f"편성 시간: {_hours(m.hours)}"], size=14, color=MUTED)

    if c.projects:
        s = _slide(prs, "프로젝트")
        _textbox(s, body_x, body_y, body_w, body_h,
                 [f"{p.name} ({p.period}) - {p.description}" for p in c.projects], size=16, bullet=True)

    s = _slide(prs, "평가 및 운영 규정 반영")
    _textbox(s, body_x, body_y, body_w, Inches(1.2), [f"평가: {c.assessment or '-'}"], size=16)
    _textbox(s, body_x, Inches(2.8), body_w, Inches(4.2), c.compliance_notes, size=14, bullet=True)

    prs.save(str(path))


# ---------------- PDF ----------------

def _pdf_font() -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if "KFont" in pdfmetrics.getRegisteredFontNames():
        return "KFont"
    for cand in PDF_FONT_CANDIDATES:
        if cand and os.path.exists(cand):
            pdfmetrics.registerFont(TTFont("KFont", cand))
            return "KFont"
    return "Helvetica"  # 한글 폰트를 못 찾으면 한글이 깨진다. PDF_FONT_PATH를 지정할 것.


def build_pdf(c: Curriculum, path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    font = _pdf_font()
    base = dict(fontName=font, wordWrap="CJK", leading=15, fontSize=10)
    h1 = ParagraphStyle("h1", **{**base, "fontSize": 20, "leading": 26, "textColor": colors.HexColor("#1F232B")})
    h2 = ParagraphStyle("h2", **{**base, "fontSize": 13, "leading": 20, "textColor": colors.HexColor("#2F5BEA"), "spaceBefore": 10})
    body = ParagraphStyle("body", **base)
    small = ParagraphStyle("small", **{**base, "fontSize": 9, "leading": 13})

    P = lambda t, st=body: Paragraph(escape(t or "-").replace("\n", "<br/>"), st)
    story = [P(c.title, h1), Spacer(1, 4),
             P(f"{c.target_summary}  |  {c.total_weeks or '-'}주  |  {_hours(c.total_hours)}", small),
             Spacer(1, 8), P(c.summary)]

    story += [P("최종 학습 목표", h2)] + [P(f"• {g}") for g in c.learning_goals]

    story.append(P("커리큘럼", h2))
    data = [[P(x, small) for x in ["기간", "모듈", "시간", "주요 내용 / 실습"]]]
    for m in c.modules:
        detail = ", ".join(m.topics) + (f"\n실습: {m.practice}" if m.practice else "")
        data.append([P(m.period, small), P(m.title, small), P(_hours(m.hours), small), P(detail, small)])
    table = Table(data, colWidths=[24 * mm, 45 * mm, 18 * mm, 93 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2FD")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9CED8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(table)

    if c.projects:
        story += [P("프로젝트", h2)] + [P(f"• {p.name} ({p.period}): {p.description}") for p in c.projects]
    story += [P("평가", h2), P(c.assessment)]
    if c.compliance_notes:
        story += [P("운영 규정·심사 기준 반영", h2)] + [P(f"• {n}") for n in c.compliance_notes]

    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                      topMargin=15 * mm, bottomMargin=15 * mm, title=c.title).build(story)


# ---------------- Word ----------------

def _korean_doc() -> Document:
    doc = Document()
    for name in ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3"):
        style = doc.styles[name]
        style.font.name = DOC_FONT_NAME
        rpr = style.element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        for attr in ("w:ascii", "w:hAnsi", "w:eastAsia"):
            rfonts.set(qn(attr), DOC_FONT_NAME)
    doc.styles["Normal"].font.size = DocxPt(10.5)
    return doc


def _curriculum_section(doc: Document, c: Curriculum) -> None:
    doc.add_heading(c.title, level=2)
    doc.add_paragraph(f"{c.target_summary}  |  {c.total_weeks or '-'}주  |  {_hours(c.total_hours)}")
    doc.add_paragraph(c.summary)
    doc.add_heading("최종 학습 목표", level=3)
    for g in c.learning_goals:
        doc.add_paragraph(g, style="List Bullet")
    doc.add_heading("세부 커리큘럼", level=3)
    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    for cell, head in zip(table.rows[0].cells, ["기간", "모듈", "시간", "주요 내용", "실습/과제"]):
        cell.text = head
    for m in c.modules:
        row = table.add_row().cells
        for cell, val in zip(row, [m.period, m.title, _hours(m.hours), ", ".join(m.topics), m.practice]):
            cell.text = val or "-"
    if c.projects:
        doc.add_heading("프로젝트", level=3)
        for p in c.projects:
            doc.add_paragraph(f"{p.name} ({p.period}): {p.description}", style="List Bullet")
    doc.add_heading("평가", level=3)
    doc.add_paragraph(c.assessment or "-")
    if c.compliance_notes:
        doc.add_heading("운영 규정·심사 기준 반영", level=3)
        for n in c.compliance_notes:
            doc.add_paragraph(n, style="List Bullet")


PLACEHOLDER_RE = re.compile(r"(\[작성 필요[^\]]*\])")


def _add_marked_text(paragraph, text: str) -> None:
    """[작성 필요: …] 부분은 노란 형광펜으로 표시한다."""
    for piece in PLACEHOLDER_RE.split(text or ""):
        if not piece:
            continue
        run = paragraph.add_run(piece)
        if PLACEHOLDER_RE.fullmatch(piece):
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW


def build_form_docx(form: FilledForm, path: Path) -> None:
    """신청 서식 작성본(FilledForm)을 Word로 저장한다."""
    doc = _korean_doc()
    doc.add_heading(form.title or "신청서", level=0)
    for b in form.blocks:
        if b.type == "heading":
            _add_marked_text(doc.add_heading(level=min(max(b.level, 1), 3)), b.text)
        elif b.type == "bullet":
            _add_marked_text(doc.add_paragraph(style="List Bullet"), b.text)
        elif b.type == "table" and b.rows:
            cols = max(len(r) for r in b.rows)
            table = doc.add_table(rows=0, cols=cols)
            table.style = "Table Grid"
            for row in b.rows:
                cells = table.add_row().cells
                for cell, val in zip(cells, row + [""] * (cols - len(row))):
                    cell.text = ""
                    _add_marked_text(cell.paragraphs[0], val)
            doc.add_paragraph()
        else:
            _add_marked_text(doc.add_paragraph(), b.text)
    doc.save(str(path))


def read_form_docx(path: Path) -> FilledForm:
    """저장된 Word 서류를 다시 FilledForm 블록으로 읽는다 (자료실 미리보기용)."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    title, blocks = "", []
    for el in doc.element.body.iterchildren():
        if el.tag == qn("w:tbl"):
            rows = [[cell.text for cell in row.cells] for row in Table(el, doc).rows]
            if rows:
                blocks.append(FormBlock(type="table", rows=rows))
            continue
        if el.tag != qn("w:p"):
            continue
        p = Paragraph(el, doc)
        text, style = p.text.strip(), (p.style.name if p.style is not None else "")
        if not text:
            continue
        if style == "Title" and not title:
            title = text
        elif style.startswith("Heading"):
            level = int(style.split()[-1]) if style.split()[-1].isdigit() else 1
            blocks.append(FormBlock(type="heading", text=text, level=level))
        elif style.startswith("List"):
            blocks.append(FormBlock(type="bullet", text=text))
        else:
            blocks.append(FormBlock(type="paragraph", text=text))
    return FilledForm(title=title or path.stem, blocks=blocks)


def build_business_plan_docx(c: Curriculum, application_docs: str, regulations: List[RegSnippet], path: Path) -> None:
    """신청 서식을 찾지 못했을 때 쓰는 기본 사업계획서."""
    doc = _korean_doc()
    doc.add_heading("사업계획서", level=0)
    if application_docs.strip():
        doc.add_heading("1. 사업 개요", level=1)
        for line in application_docs.splitlines():
            doc.add_paragraph(line)
    doc.add_heading("2. 훈련 과정 커리큘럼", level=1)
    _curriculum_section(doc, c)
    if regulations:
        doc.add_heading("참고: 운영 규정 발췌", level=1)
        for r in regulations:
            doc.add_paragraph(f"[{r.source} {r.article} p.{r.page}] {r.text}")
    doc.save(str(path))


def build_validation_docx(v: Validation, c: Curriculum, path: Path) -> None:
    doc = _korean_doc()
    doc.add_heading("학생 관점 검증 결과", level=0)
    doc.add_paragraph(f"대상 커리큘럼: {c.title}")
    doc.add_paragraph(v.overall)
    for p in v.personas:
        doc.add_heading(f"{p.persona}  (만족도 {p.score or '-'}/5)", level=1)
        doc.add_paragraph(p.profile)
        if p.strengths:
            doc.add_heading("좋은 점", level=3)
            for s in p.strengths:
                doc.add_paragraph(s, style="List Bullet")
        if p.gaps:
            doc.add_heading("부족한 점", level=3)
            for g in p.gaps:
                doc.add_paragraph(f"[{g.severity}] {g.location}: {g.issue} → {g.suggestion}", style="List Bullet")
    if c.change_log:
        doc.add_heading("반영 내역", level=1)
        for line in c.change_log:
            doc.add_paragraph(line, style="List Bullet")
    doc.save(str(path))


def build_materials_docx(c: Curriculum, path: Path) -> None:
    """교과목별 학습 자료(설명 → 실습 → 퀴즈)를 Word로 저장한다. 퀴즈 정답은 교과목 끝에 모아 둔다."""
    doc = _korean_doc()
    doc.add_heading(f"{c.title} 학습 자료" + (f" (v{c.version})" if c.version else ""), level=0)
    quizzes = {}
    for q in c.quizzes:
        quizzes.setdefault(q.get("subject_id"), []).append(q)
    marks = "①②③④"
    for m in c.learning_materials:
        doc.add_heading(m.get("title", ""), level=1)
        _add_marked_text(doc.add_paragraph(), m.get("overview", ""))
        for s in m.get("sections", []):
            doc.add_heading(s.get("title", ""), level=2)
            _add_marked_text(doc.add_paragraph(), s.get("explanation", ""))
            if s.get("example"):
                _add_marked_text(doc.add_paragraph(), "예시: " + s["example"])
        for p in m.get("practices", []):
            doc.add_heading(f"실습: {p.get('title', '')}", level=2)
            doc.add_paragraph(f"목표: {p.get('goal', '')}")
            for i, step in enumerate(p.get("steps", []), 1):
                _add_marked_text(doc.add_paragraph(), f"{i}. {step}")
            doc.add_paragraph(f"확인할 결과: {p.get('expected_result', '')}")
            for h in p.get("hints", []):
                doc.add_paragraph(f"힌트: {h}", style="List Bullet")
        if m.get("summary_points"):
            doc.add_heading("핵심 정리", level=2)
            for x in m["summary_points"]:
                doc.add_paragraph(x, style="List Bullet")
        qs = [qq for q in quizzes.get(m.get("subject_id"), []) for qq in q.get("questions", [])]
        if qs:
            doc.add_heading("퀴즈", level=2)
            for n, qq in enumerate(qs, 1):
                doc.add_paragraph(f"{n}. {qq['question']}")
                for i, ch in enumerate(qq["choices"]):
                    doc.add_paragraph(f"   {marks[i]} {ch}")
            doc.add_paragraph("정답: " + ", ".join(f"{n}번 {marks[qq['answer'] - 1]}" for n, qq in enumerate(qs, 1)))
    doc.save(str(path))
