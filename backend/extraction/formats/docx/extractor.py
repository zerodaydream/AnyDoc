"""DOCX -> IR blocks, read straight from the OOXML (stdlib zipfile + ElementTree; no new dependency).

Paragraph order mirrors the viewer (docx-preview 0.4.1, `parseBodyElements` / `parseTableCell` / `parseParagraph` /
`parseRun`), so `DocxRegion.para` = the n-th `<p>` the viewer renders:
- body: `w:p`, `w:tbl`, `w:sdt` (content controls, recursively); table cells: `w:p` and nested `w:tbl` only.
- paragraph text: runs, hyperlinks, smart tags, content controls, insertions and math; deleted text is left out.
- run text: `w:t`, tab -> "\t", line break -> "\n", `w:sym`, non-breaking hyphen -> "-". Runs holding field codes
  (`w:fldChar`/`w:instrText`) are skipped, as the viewer skips them; the field's result runs are kept.
Headers, footers, footnotes, comments and text boxes are not read (documented limitation).

Uploaded files are untrusted: parts are size- and ratio-capped before reading, DTDs are refused (OOXML never has
one), and nothing is extracted to disk. Runs inside the parsing sandbox: pure function, no DB, no network.
"""

import contextlib
import hashlib
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree as ET

from backend.core.errors import InvalidFile
from backend.document_ir.models import BlockType, ExtractLimits, ExtractResult, IRBlock
from backend.extraction.formats.docx.locate import locate_docx
from backend.extraction.split import MAX_BLOCK_CHARS, cut

MAIN_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
MAX_PART_BYTES = 64 * 1024 * 1024  # uncompressed size of one XML part we read
MAX_RATIO = 200  # uncompressed / compressed, above 1 MB: a decompression bomb, not a document
CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # password-protected .docx files are OLE compound files
_HEADING = re.compile(r"^heading\s*([1-9])$")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(el: ET.Element, name: str) -> str | None:
    """Attribute by local name: transitional (w:) and strict OOXML use different namespaces."""
    for k, v in el.attrib.items():
        if k == name or k.endswith("}" + name):
            return v
    return None


def _child(el: ET.Element, name: str) -> ET.Element | None:
    return next((c for c in el if _local(c.tag) == name), None)


def _read(zf: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        info = zf.getinfo(name)
    except KeyError:
        return None
    big = f"Part of this Word file is too large to read ({info.file_size // (1024 * 1024):,} MB unpacked)."
    if info.file_size > MAX_PART_BYTES:
        raise InvalidFile("too_large", big)
    if info.file_size > 1024 * 1024 and info.file_size > MAX_RATIO * max(1, info.compress_size):
        raise InvalidFile("unsafe_file", "This Word file unpacks to far more data than it holds; it was not opened.")
    with zf.open(info) as f:
        data = f.read(MAX_PART_BYTES + 1)
    if len(data) > MAX_PART_BYTES:  # the header lied about the size
        raise InvalidFile("too_large", big)
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise InvalidFile("unsafe_file", "This Word file has XML declarations Word never writes; it was not opened.")
    try:
        return ET.fromstring(data)  # noqa: S314 - DTDs refused above; expat >= 2.4.1 also caps entity expansion
    except ET.ParseError:
        raise InvalidFile("parse_failed", "This Word file is damaged (its XML can't be read).") from None


def _rels(zf: zipfile.ZipFile, part: str) -> dict[str, str]:
    """Relationship type suffix -> target part path, for `part` (e.g. "word/document.xml")."""
    p = PurePosixPath(part)
    root = _read(zf, str(p.parent / "_rels" / f"{p.name}.rels") if part else "_rels/.rels")
    out: dict[str, str] = {}
    for r in root if root is not None else []:
        target, kind = _attr(r, "Target"), (_attr(r, "Type") or "").rsplit("/", 1)[-1]
        if target and _attr(r, "TargetMode") != "External" and kind not in out:
            path = target.lstrip("/") if target.startswith("/") else str(p.parent / target) if part else target
            out[kind] = str(PurePosixPath(path))
    return out


@dataclass(slots=True)
class _Style:
    name: str
    based_on: str | None
    outline: int | None
    numbered: bool


def _styles(root: ET.Element | None) -> dict[str, _Style]:
    out: dict[str, _Style] = {}
    for s in root if root is not None else []:
        if _local(s.tag) != "style" or _attr(s, "type") not in (None, "paragraph"):
            continue
        sid = _attr(s, "styleId") or ""
        name_el, base_el, ppr = _child(s, "name"), _child(s, "basedOn"), _child(s, "pPr")
        outline = _child(ppr, "outlineLvl") if ppr is not None else None
        out[sid] = _Style(
            name=(_attr(name_el, "val") or sid) if name_el is not None else sid,
            based_on=_attr(base_el, "val") if base_el is not None else None,
            outline=int(_attr(outline, "val") or 9) if outline is not None else None,
            numbered=ppr is not None and _child(ppr, "numPr") is not None,
        )
    return out


def _kind(p: ET.Element, styles: dict[str, _Style]) -> tuple[BlockType, int]:
    """Block type and heading level from the paragraph's own properties, then its style chain."""
    ppr = _child(p, "pPr")
    sid, outline, numbered = None, None, False
    if ppr is not None:
        if (ps := _child(ppr, "pStyle")) is not None:
            sid = _attr(ps, "val")
        if (ol := _child(ppr, "outlineLvl")) is not None:
            outline = int(_attr(ol, "val") or 9)
        if (num := _child(ppr, "numPr")) is not None:
            num_id = _child(num, "numId")
            numbered = num_id is None or _attr(num_id, "val") != "0"
    seen: set[str] = set()
    while sid and sid not in seen and len(seen) < 20:
        seen.add(sid)
        st = styles.get(sid)
        name = (st.name if st else sid).lower()
        if m := _HEADING.match(name) or _HEADING.match(sid.lower()):
            return "heading", int(m.group(1))
        if name == "title":
            return "heading", 0  # above Heading 1, so chapters keep the title as their root
        if name in ("quote", "intense quote"):
            return "quote", 0
        if st is None:
            break
        outline = st.outline if outline is None else outline
        numbered = numbered or st.numbered
        sid = st.based_on
    if outline is not None and outline < 9:
        return "heading", outline + 1
    return ("list_item" if numbered else "paragraph"), 0


def _run(r: ET.Element, out: list[str]) -> None:
    kids = list(r)
    if any(_local(k.tag) in ("fldChar", "instrText") for k in kids):
        return  # field code; the viewer renders nothing for it
    for k in kids:
        n = _local(k.tag)
        if n == "t":
            out.append(k.text or "")
        elif n == "tab":
            out.append("\t")
        elif n == "br" and _attr(k, "type") in (None, "textWrapping"):
            out.append("\n")
        elif n == "sym":
            with contextlib.suppress(ValueError):
                out.append(chr(int(_attr(k, "char") or "", 16)))
        elif n == "noBreakHyphen":
            out.append("-")


def _inline(el: ET.Element, out: list[str]) -> None:
    for c in el:
        n = _local(c.tag)
        if n == "r":
            _run(c, out)
        elif n == "hyperlink":
            for r in c:
                if _local(r.tag) == "r":
                    _run(r, out)
        elif n == "smartTag":
            _smart_tag(c, out)
        elif n == "ins":
            _inline(c, out)
        elif n == "sdt" and (content := _child(c, "sdtContent")) is not None:
            _inline(content, out)
        elif n in ("oMath", "oMathPara"):
            out.extend(t.text or "" for t in c.iter() if _local(t.tag) == "t")


def _smart_tag(el: ET.Element, out: list[str]) -> None:
    for c in el:
        if _local(c.tag) == "r":
            _run(c, out)
        elif _local(c.tag) == "smartTag":
            _smart_tag(c, out)


@dataclass(slots=True)
class _Para:
    index: int  # among all rendered paragraphs (DocxRegion.para)
    text: str
    kind: BlockType
    level: int


class _Walker:
    def __init__(self, styles: dict[str, _Style]) -> None:
        self.styles = styles
        self.paras: list[_Para] = []  # every rendered paragraph, in order: paras[i].index == i
        self.units: list[_Para | list[list[list[_Para]]]] = []  # body paragraphs and top-level tables

    def para(self, p: ET.Element) -> _Para:
        parts: list[str] = []
        _inline(p, parts)
        kind, level = _kind(p, self.styles)
        self.paras.append(_Para(len(self.paras), "".join(parts), kind, level))
        return self.paras[-1]

    def body(self, el: ET.Element) -> None:
        for c in el:
            n = _local(c.tag)
            if n == "p":
                self.units.append(self.para(c))
            elif n == "tbl":
                self.units.append(self.table(c))
            elif n == "sdt" and (content := _child(c, "sdtContent")) is not None:
                self.body(content)

    def table(self, tbl: ET.Element) -> list[list[list[_Para]]]:
        rows: list[list[list[_Para]]] = []
        for tr in tbl:
            if _local(tr.tag) != "tr":
                continue
            cells: list[list[_Para]] = []
            for tc in tr:
                if _local(tc.tag) == "tc":
                    cells.append(self.cell(tc))
            rows.append(cells)
        return rows

    def cell(self, tc: ET.Element) -> list[_Para]:
        """Paragraphs of a cell, nested tables flattened into it (they count toward `para` in order)."""
        out: list[_Para] = []
        for c in tc:
            n = _local(c.tag)
            if n == "p":
                out.append(self.para(c))
            elif n == "tbl":
                out.extend(p for row in self.table(c) for cell in row for p in cell)
        return out


Segment = list[int]  # [content_start, content_end, para, para_start, ref]; ref = paragraph or row number


def _slice(segments: list[Segment], a: int, b: int) -> list[Segment]:
    out = []
    for cs, ce, para, ps, ref in segments:
        lo, hi = max(cs, a), min(ce, b)
        if lo < hi:
            out.append([lo - a, hi - a, para, ps + lo - cs, ref])
    return out


def extract_docx(path: Path, limits: ExtractLimits) -> ExtractResult:
    with path.open("rb") as f:
        if f.read(8) == CFB_MAGIC:
            raise InvalidFile("encrypted", "This Word file is password-protected. Remove the password, then upload it.")
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise InvalidFile("parse_failed", "This Word file is damaged (it isn't a valid .docx package).") from None
    with zf:
        main = _rels(zf, "").get("officeDocument", "word/document.xml")
        types = _read(zf, "[Content_Types].xml")
        overrides: Iterable[ET.Element] = types if types is not None else []
        declared = next((_attr(o, "ContentType") for o in overrides if _attr(o, "PartName") == f"/{main}"), None)
        if declared != MAIN_TYPE:
            raise InvalidFile("type_mismatch", "This file is named .docx, but it isn't a Word document (.docx).")
        doc = _read(zf, main)
        if doc is None:
            raise InvalidFile("parse_failed", "This Word file is damaged (its main document is missing).")
        styles_part = _rels(zf, main).get("styles")
        styles = _styles(_read(zf, styles_part) if styles_part else None)

    body = _child(doc, "body")
    walker = _Walker(styles)
    if body is not None:
        walker.body(body)

    total = sum(len(p.text) for p in walker.paras)
    if total > limits.max_chars:
        raise InvalidFile("too_long", f"This file has {total:,} characters; the limit is {limits.max_chars:,}.")

    blocks: list[IRBlock] = []
    heads: list[tuple[int, str]] = []
    number = tables = 0

    def emit(content: str, segments: list[Segment], kind: BlockType, meta: dict[str, Any]) -> None:
        for a, b in cut(content, 0, len(content), MAX_BLOCK_CHARS):
            while a < b and content[a].isspace():
                a += 1
            while b > a and content[b - 1].isspace():
                b -= 1
            if a >= b:
                continue
            piece, segs = content[a:b], _slice(segments, a, b)
            m: dict[str, Any] = {**meta, "segments": segs}
            digest = hashlib.sha1(piece.encode(), usedforsecurity=False).hexdigest()[:8]
            blocks.append(
                IRBlock(
                    block_id=f"docx:{segs[0][2]}:{len(blocks)}:{digest}",
                    ordinal=len(blocks),
                    type=kind,
                    content=piece,
                    page=None,
                    source_location=locate_docx(piece, None, m, 0, len(piece)),
                    format_metadata=m,
                    section_path=[h for _, h in heads],
                )
            )

    for unit in walker.units:
        if isinstance(unit, _Para):
            text = unit.text.strip()
            if not text:
                continue
            number += 1
            lead = len(unit.text) - len(unit.text.lstrip())
            if unit.kind == "heading":
                while heads and heads[-1][0] >= unit.level:
                    heads.pop()
                heads.append((unit.level, text[:200]))
            meta = {"level": unit.level} if unit.kind == "heading" else {}
            emit(text, [[0, len(text), unit.index, lead, number]], unit.kind, meta)
            continue
        tables += 1
        content, segments, row_no = "", [], 0
        for row in unit:
            row_no += 1
            line, row_segs = "", []
            for k, cell in enumerate(row):
                if k:
                    line += " | "
                first = True
                for p in cell:
                    t = p.text.strip()
                    if not t:
                        continue
                    if not first:
                        line += " "
                    first = False
                    base = len(content) + (1 if content else 0) + len(line)
                    row_segs.append([base, base + len(t), p.index, len(p.text) - len(p.text.lstrip()), row_no])
                    line += t
            if row_segs:
                content += ("\n" if content else "") + line
                segments.extend(row_segs)
        if segments:
            emit(content, segments, "table", {"table": tables})

    if not blocks:
        raise InvalidFile("no_text", "This Word file has no text in it.")
    heads_by_level = sorted((b.format_metadata["level"], b.ordinal) for b in blocks if b.type == "heading")
    title = blocks[heads_by_level[0][1]].content if heads_by_level else ""
    return ExtractResult(
        page_count=None,
        blocks=blocks,
        metadata={
            "title": title[:200],
            "paragraph_count": len(walker.paras),
            "table_count": tables,
            "word_count": sum(len(p.text.split()) for p in walker.paras),
            "char_count": total,
            "extractor": "docx-ooxml",
        },
    )
