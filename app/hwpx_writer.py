"""작성한 신청 서식(FilledForm)을 한글(.hwpx) 파일로 저장한다.

.hwpx는 zip 안에 XML(OWPML)이 들어 있는 한글 표준 형식이다. 바이너리 .hwp는 직접 쓰기 어려워서
원본이 .hwp여도 .hwpx로 만든다 (한글에서 그대로 열리고, 필요하면 .hwp로 다시 저장할 수 있다).
글꼴·문단 모양은 최소한만 정의하고, 줄 배치(linesegarray)는 한글이 열 때 다시 계산한다.
"""
import re
import zipfile
from pathlib import Path
from typing import List
from xml.sax.saxutils import escape

from .config import DOC_FONT_NAME
from .schemas import FilledForm

PLACEHOLDER_RE = re.compile(r"(\[작성 필요[^\]]*\])")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

NS = ('xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
      'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
      'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" '
      'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
      'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
      'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
      'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" '
      'xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" '
      'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" '
      'xmlns:dc="http://purl.org/dc/elements/1.1/" '
      'xmlns:opf="http://www.idpf.org/2007/opf/" '
      'xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" '
      'xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" '
      'xmlns:epub="http://www.idpf.org/2007/ops" '
      'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"')
XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'

# A4 (HWPUNIT: 1mm ≈ 283.46), 좌우 여백 20mm
PAGE_W, PAGE_H, MARGIN_LR, MARGIN_TB = 59528, 84188, 5669, 4251
TEXT_W = PAGE_W - 2 * MARGIN_LR

# 글자 모양 id
CHAR_BODY, CHAR_TITLE, CHAR_H1, CHAR_H2, CHAR_H3, CHAR_MARK, CHAR_CELL_HEAD = range(7)
# 문단 모양 id
PARA_BODY, PARA_TITLE, PARA_HEADING, PARA_BULLET, PARA_CELL = range(5)
# 테두리 id: 1 없음(쪽), 2 없음(글자), 3 표 칸 실선, 4 표 머리 칸(실선 + 회색 배경)
BORDER_NONE, BORDER_CHAR, BORDER_CELL, BORDER_CELL_HEAD = 1, 2, 3, 4
LANGS = ["HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER"]


def _clean(text: str) -> str:
    return escape(CONTROL_RE.sub("", text or ""))


def _lang_attrs(value) -> str:
    return " ".join(f'{lang.lower()}="{value}"' for lang in LANGS)


def _char_pr(cid: int, height: int, bold: bool = False, shade: str = "none") -> str:
    return (f'<hh:charPr id="{cid}" height="{height}" textColor="#000000" shadeColor="{shade}" useFontSpace="0" '
            f'useKerning="0" symMark="NONE" borderFillIDRef="{BORDER_CHAR}">'
            f'<hh:fontRef {_lang_attrs(0)}/><hh:ratio {_lang_attrs(100)}/><hh:spacing {_lang_attrs(0)}/>'
            f'<hh:relSz {_lang_attrs(100)}/><hh:offset {_lang_attrs(0)}/>' + ("<hh:bold/>" if bold else "") +
            '<hh:underline type="NONE" shape="SOLID" color="#000000"/><hh:strikeout shape="NONE" color="#000000"/>'
            '<hh:outline type="NONE"/><hh:shadow type="NONE" color="#B2B2B2" offsetX="10" offsetY="10"/></hh:charPr>')


def _para_pr(pid: int, align: str = "JUSTIFY", left: int = 0, indent: int = 0, prev: int = 0, nxt: int = 0,
             line: int = 160) -> str:
    margin = (f'<hh:margin><hc:intent value="{indent}" unit="HWPUNIT"/><hc:left value="{left}" unit="HWPUNIT"/>'
              f'<hc:right value="0" unit="HWPUNIT"/><hc:prev value="{prev}" unit="HWPUNIT"/>'
              f'<hc:next value="{nxt}" unit="HWPUNIT"/></hh:margin>'
              f'<hh:lineSpacing type="PERCENT" value="{line}" unit="HWPUNIT"/>')
    return (f'<hh:paraPr id="{pid}" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" '
            f'suppressLineNumbers="0" checked="0"><hh:align horizontal="{align}" vertical="BASELINE"/>'
            '<hh:heading type="NONE" idRef="0" level="0"/>'
            '<hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" '
            'keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>'
            '<hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
            f'<hp:switch><hp:case hp:required-namespace="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar">{margin}'
            f'</hp:case><hp:default>{margin}</hp:default></hp:switch>'
            f'<hh:border borderFillIDRef="{BORDER_NONE}" offsetLeft="0" offsetRight="0" offsetTop="0" '
            'offsetBottom="0" connect="0" ignoreMargin="0"/></hh:paraPr>')


def _border_fill(bid: int, line: str = "NONE", face: str = "none") -> str:
    sides = "".join(f'<hh:{s}Border type="{line}" width="0.12 mm" color="#000000"/>'
                    for s in ("left", "right", "top", "bottom"))
    return (f'<hh:borderFill id="{bid}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
            '<hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
            f'{sides}<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>'
            f'<hc:fillBrush><hc:winBrush faceColor="{face}" hatchColor="#FF000000" alpha="0"/></hc:fillBrush>'
            '</hh:borderFill>')


def _header() -> str:
    font = (f'<hh:font id="0" face="{escape(DOC_FONT_NAME)}" type="TTF" isEmbedded="0">'
            '<hh:typeInfo familyType="FCAT_GOTHIC" weight="5" proportion="3" contrast="2" strokeVariation="0" '
            'armStyle="0" letterform="2" midline="0" xHeight="4"/></hh:font>')
    fontfaces = "".join(f'<hh:fontface lang="{lang}" fontCnt="1">{font}</hh:fontface>' for lang in LANGS)
    borders = [_border_fill(BORDER_NONE), _border_fill(BORDER_CHAR), _border_fill(BORDER_CELL, "SOLID"),
               _border_fill(BORDER_CELL_HEAD, "SOLID", "#E8E8E8")]
    chars = [_char_pr(CHAR_BODY, 1000), _char_pr(CHAR_TITLE, 1800, bold=True), _char_pr(CHAR_H1, 1400, bold=True),
             _char_pr(CHAR_H2, 1200, bold=True), _char_pr(CHAR_H3, 1100, bold=True),
             _char_pr(CHAR_MARK, 1000, shade="#FFFF00"), _char_pr(CHAR_CELL_HEAD, 1000, bold=True)]
    paras = [_para_pr(PARA_BODY, nxt=300), _para_pr(PARA_TITLE, "CENTER", nxt=1200),
             _para_pr(PARA_HEADING, "LEFT", prev=900, nxt=300), _para_pr(PARA_BULLET, left=1500, indent=-1000, nxt=200),
             _para_pr(PARA_CELL, "LEFT", line=130)]
    return (f'{XML_HEAD}<hh:head {NS} version="1.5" secCnt="1">'
            '<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/><hh:refList>'
            f'<hh:fontfaces itemCnt="{len(LANGS)}">{fontfaces}</hh:fontfaces>'
            f'<hh:borderFills itemCnt="{len(borders)}">{"".join(borders)}</hh:borderFills>'
            f'<hh:charProperties itemCnt="{len(chars)}">{"".join(chars)}</hh:charProperties>'
            '<hh:tabProperties itemCnt="1"><hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/></hh:tabProperties>'
            f'<hh:paraProperties itemCnt="{len(paras)}">{"".join(paras)}</hh:paraProperties>'
            '<hh:styles itemCnt="1"><hh:style id="0" type="PARA" name="바탕글" engName="Normal" '
            f'paraPrIDRef="{PARA_BODY}" charPrIDRef="{CHAR_BODY}" nextStyleIDRef="0" langID="1042" lockForm="0"/>'
            '</hh:styles></hh:refList>'
            '<hh:compatibleDocument targetProgram="HWP201X"><hh:layoutCompatibility/></hh:compatibleDocument>'
            '<hh:docOption><hh:linkinfo path="" pageInherit="0" footnoteInherit="0"/></hh:docOption>'
            '<hh:trackchageConfig flags="56"/></hh:head>')


def _runs(text: str, char: int) -> str:
    """[작성 필요: …] 부분은 노란 음영 글자로 나눈다."""
    pieces = [p for p in PLACEHOLDER_RE.split(text or "") if p] or [""]
    return "".join(f'<hp:run charPrIDRef="{CHAR_MARK if PLACEHOLDER_RE.fullmatch(p) else char}">'
                   f'<hp:t>{_clean(p)}</hp:t></hp:run>' for p in pieces)


def _p(inner: str, para: int = PARA_BODY) -> str:
    return (f'<hp:p id="0" paraPrIDRef="{para}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            f'{inner}</hp:p>')


SEC_PR = (
    f'<hp:run charPrIDRef="{CHAR_BODY}"><hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" '
    'tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="0" memoShapeIDRef="0" '
    'textVerticalWidthHead="0" masterPageCnt="0"><hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/>'
    '<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
    '<hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" '
    'fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>'
    '<hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>'
    f'<hp:pagePr landscape="WIDELY" width="{PAGE_W}" height="{PAGE_H}" gutterType="LEFT_ONLY">'
    f'<hp:margin header="2834" footer="2834" gutter="0" left="{MARGIN_LR}" right="{MARGIN_LR}" '
    f'top="{MARGIN_TB}" bottom="{MARGIN_TB}"/></hp:pagePr>'
    '<hp:footNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>'
    '<hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/>'
    '<hp:noteSpacing betweenNotes="283" belowLine="567" aboveLine="850"/>'
    '<hp:numbering type="CONTINUOUS" newNum="1"/><hp:placement place="EACH_COLUMN" beneathText="0"/></hp:footNotePr>'
    '<hp:endNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>'
    '<hp:noteLine length="14692344" type="SOLID" width="0.12 mm" color="#000000"/>'
    '<hp:noteSpacing betweenNotes="0" belowLine="567" aboveLine="850"/>'
    '<hp:numbering type="CONTINUOUS" newNum="1"/><hp:placement place="END_OF_DOCUMENT" beneathText="0"/>'
    '</hp:endNotePr>' + "".join(
        f'<hp:pageBorderFill type="{t}" borderFillIDRef="{BORDER_NONE}" textBorder="PAPER" headerInside="0" '
        'footerInside="0" fillArea="PAPER"><hp:offset left="1417" right="1417" top="1417" bottom="1417"/>'
        '</hp:pageBorderFill>' for t in ("BOTH", "EVEN", "ODD")) +
    '</hp:secPr><hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/>'
    '</hp:ctrl></hp:run>')


def _table(rows: List[List[str]], tid: int) -> str:
    cols = max(len(r) for r in rows)
    width = TEXT_W // cols
    cell_h = 1800
    trs = []
    for r, row in enumerate(rows):
        tcs = []
        for c, val in enumerate(row + [""] * (cols - len(row))):
            head = r == 0
            tcs.append(
                f'<hp:tc name="" header="{int(head)}" hasMargin="0" protect="0" editable="0" dirty="0" '
                f'borderFillIDRef="{BORDER_CELL_HEAD if head else BORDER_CELL}">'
                '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
                'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
                + "".join(_p(_runs(line, CHAR_CELL_HEAD if head else CHAR_BODY), PARA_CELL)
                          for line in (str(val).split("\n") or [""])) +
                f'</hp:subList><hp:cellAddr colAddr="{c}" rowAddr="{r}"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
                f'<hp:cellSz width="{width}" height="{cell_h}"/>'
                '<hp:cellMargin left="510" right="510" top="141" bottom="141"/></hp:tc>')
        trs.append(f'<hp:tr>{"".join(tcs)}</hp:tr>')
    tbl = (f'<hp:tbl id="{tid}" zOrder="{tid}" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
           'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="1" '
           f'rowCnt="{len(rows)}" colCnt="{cols}" cellSpacing="0" borderFillIDRef="{BORDER_CELL}" noAdjust="0">'
           f'<hp:sz width="{width * cols}" widthRelTo="ABSOLUTE" height="{cell_h * len(rows)}" '
           'heightRelTo="ABSOLUTE" protect="0"/>'
           '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
           'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
           '<hp:outMargin left="0" right="0" top="0" bottom="283"/>'
           '<hp:inMargin left="510" right="510" top="141" bottom="141"/>'
           f'{"".join(trs)}</hp:tbl>')
    return _p(f'<hp:run charPrIDRef="{CHAR_BODY}">{tbl}<hp:t/></hp:run>')


def _section(form: FilledForm) -> str:
    title = form.title or "신청서"
    body = [_p(SEC_PR + _runs(title, CHAR_TITLE), PARA_TITLE)]
    heading_char = {1: CHAR_H1, 2: CHAR_H2, 3: CHAR_H3}
    for i, b in enumerate(form.blocks, start=1):
        if b.type == "heading":
            body.append(_p(_runs(b.text, heading_char[min(max(b.level, 1), 3)]), PARA_HEADING))
        elif b.type == "bullet":
            body.append(_p(_runs(f"• {b.text}", CHAR_BODY), PARA_BULLET))
        elif b.type == "table" and b.rows:
            body.append(_table(b.rows, 1000 + i))
        else:
            body.append(_p(_runs(b.text, CHAR_BODY)))
    return f'{XML_HEAD}<hs:sec {NS}>{"".join(body)}</hs:sec>'


def _content_hpf(title: str) -> str:
    return (f'{XML_HEAD}<opf:package {NS} version="" unique-identifier="" id="">'
            f'<opf:metadata><opf:title>{_clean(title)}</opf:title><opf:language>ko</opf:language></opf:metadata>'
            '<opf:manifest>'
            '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
            '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
            '<opf:item id="settings" href="settings.xml" media-type="application/xml"/>'
            '</opf:manifest><opf:spine><opf:itemref idref="header" linear="yes"/>'
            '<opf:itemref idref="section0" linear="yes"/></opf:spine></opf:package>')


VERSION_XML = (f'{XML_HEAD}<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" '
               'tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="1" buildNumber="0" os="1" '
               'xmlVersion="1.5" application="Hancom Office Hangul" appVersion="12, 0, 0, 0"/>')
CONTAINER_XML = (f'{XML_HEAD}<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" '
                 'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf"><ocf:rootfiles>'
                 '<ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>'
                 '<ocf:rootfile full-path="Preview/PrvText.txt" media-type="text/plain"/>'
                 '</ocf:rootfiles></ocf:container>')
MANIFEST_XML = f'{XML_HEAD}<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>'
SETTINGS_XML = (f'{XML_HEAD}<ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
                'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0">'
                '<ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/></ha:HWPApplicationSetting>')


def _preview_text(form: FilledForm) -> str:
    lines = [form.title]
    for b in form.blocks:
        lines += [" | ".join(r) for r in b.rows] if b.type == "table" else [b.text]
    return "\r\n".join(lines)[:1000]


def build_form_hwpx(form: FilledForm, path: Path) -> None:
    """신청 서식 작성본(FilledForm)을 한글(.hwpx)로 저장한다."""
    with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as z:
        # mimetype은 맨 앞에 압축하지 않고 넣어야 한글이 형식을 알아본다
        z.writestr(zipfile.ZipInfo("mimetype"), "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("version.xml", VERSION_XML)
        z.writestr("Contents/header.xml", _header())
        z.writestr("Contents/section0.xml", _section(form))
        z.writestr("Preview/PrvText.txt", _preview_text(form))
        z.writestr("settings.xml", SETTINGS_XML)
        z.writestr("Contents/content.hpf", _content_hpf(form.title or "신청서"))
        z.writestr("META-INF/container.xml", CONTAINER_XML)
        z.writestr("META-INF/manifest.xml", MANIFEST_XML)
