"""한글(.hwp / .hwpx) 문서에서 텍스트 추출.

- .hwpx: zip 안의 Contents/section*.xml 에서 글자(<hp:t>)를 문단 단위로 모은다.
- .hwp(5.0): OLE 파일의 BodyText/Section* 스트림을 풀어 문단 글자 레코드(HWPTAG_PARA_TEXT)를 읽는다.
표 안의 글자도 문단으로 들어 있어서 한 줄씩 나온다.
"""
import io
import re
import struct
import zipfile
import zlib
from typing import List

HWPTAG_PARA_TEXT = 67
# 문단 글자 안의 제어 문자: 이 코드들은 8글자(16바이트)를 차지한다
WIDE_CONTROLS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}


def _num(name: str) -> int:
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else 0


def hwpx_text(data: bytes) -> str:
    from lxml import etree
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        sections = sorted((n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)), key=_num)
        if not sections:
            raise ValueError("한글(.hwpx) 본문을 찾지 못했습니다.")
        lines: List[str] = []
        for name in sections:
            root = etree.fromstring(z.read(name))
            current, buf = None, []
            for el in root.iter():
                tag = etree.QName(el).localname if isinstance(el.tag, str) else ""
                if tag not in ("t", "tab", "lineBreak"):
                    continue
                # 가장 가까운 문단(p)이 바뀌면 줄을 바꾼다 (표 안 문단도 따로 한 줄)
                para = next((a for a in el.iterancestors() if etree.QName(a).localname == "p"), None)
                if para is not current:
                    if buf:
                        lines.append("".join(buf))
                    current, buf = para, []
                if tag == "t":
                    buf.append("".join(el.itertext()))
                elif tag == "tab":
                    buf.append("\t")
                else:
                    buf.append("\n")
            if buf:
                lines.append("".join(buf))
    return "\n".join(lines)


def _para_text(raw: bytes) -> str:
    out, i = [], 0
    while i + 1 < len(raw):
        code = struct.unpack_from("<H", raw, i)[0]
        if code in WIDE_CONTROLS:
            if code == 9:
                out.append("\t")
            i += 16
            continue
        if code in (10, 13):
            out.append("\n")
        elif code >= 32:
            out.append(chr(code))
        i += 2
    return "".join(out)


def hwp_text(data: bytes) -> str:
    import olefile
    if not olefile.isOleFile(io.BytesIO(data)):
        raise ValueError("한글(.hwp) 파일 형식이 아닙니다.")
    ole = olefile.OleFileIO(io.BytesIO(data))
    try:
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack_from("<I", header, 36)[0]
        if flags & 0x02:
            raise ValueError("암호가 걸린 한글 파일은 읽을 수 없습니다. 암호를 풀고 다시 넣어주세요.")
        if flags & 0x04:
            raise ValueError("배포용(복사 방지) 한글 파일은 읽을 수 없습니다. 한글에서 PDF나 .hwpx로 저장해서 넣어주세요.")
        compressed = bool(flags & 0x01)
        sections = sorted((e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText"), key=lambda e: _num(e[1]))
        paras: List[str] = []
        for entry in sections:
            raw = ole.openstream(entry).read()
            if compressed:
                raw = zlib.decompress(raw, -15)
            i = 0
            while i + 4 <= len(raw):
                head = struct.unpack_from("<I", raw, i)[0]
                tag, size = head & 0x3FF, (head >> 20) & 0xFFF
                i += 4
                if size == 0xFFF:
                    size = struct.unpack_from("<I", raw, i)[0]
                    i += 4
                if tag == HWPTAG_PARA_TEXT:
                    paras.append(_para_text(raw[i:i + size]).rstrip("\n"))
                i += size
        return "\n".join(paras)
    finally:
        ole.close()
