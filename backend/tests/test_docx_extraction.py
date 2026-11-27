"""DOCX: detection, block structure, paragraph order, exact locations, limits and malformed/unsafe input."""

import io
import zipfile
from pathlib import Path

import pytest

from backend.core.errors import InvalidFile
from backend.document_ir.models import DocxLocation, ExtractLimits, ExtractResult
from backend.extraction.formats.docx.extractor import CFB_MAGIC, MAX_PART_BYTES, extract_docx
from backend.extraction.formats.docx.handler import DocxHandler
from backend.extraction.registry import describe, detect, locate
from backend.extraction.sandbox import run_sandboxed
from backend.grounding.validator import EvidenceBlock, validate_segment
from backend.tests.docxgen import (
    BR,
    FIELD_PAGE,
    TAB,
    _paragraph_texts,
    cell,
    deleted,
    inserted,
    make_docx,
    p,
    sample_agreement,
    sdt,
    table,
)

LIMITS = ExtractLimits(max_pages=500, max_chars=1_000_000)


def _extract(tmp_path: Path, data: bytes, limits: ExtractLimits = LIMITS) -> ExtractResult:
    path = tmp_path / "f.docx"
    path.write_bytes(data)
    return extract_docx(path, limits)


def _block(r: ExtractResult, starts: str) -> int:
    return next(i for i, b in enumerate(r.blocks) if b.content.startswith(starts))


def _para_text(data: bytes, para: int) -> str:
    return _paragraph_texts(data)[para]


# --- detection ---------------------------------------------------------------------------------------


def test_sniff_and_detect() -> None:
    data = sample_agreement()
    assert detect("contract.docx", data[:16]).name == "docx"
    assert detect("locked.docx", CFB_MAGIC + b"\x00" * 8).name == "docx"  # extract() explains the password
    with pytest.raises(InvalidFile) as e:
        detect("contract.docx", b"%PDF-1.7\n")
    assert e.value.code == "type_mismatch"
    with pytest.raises(InvalidFile) as e:
        detect("old.doc", CFB_MAGIC)
    assert e.value.code == "unsupported_format"


# --- structure ---------------------------------------------------------------------------------------


def test_sample_blocks_types_and_sections(tmp_path: Path) -> None:
    r = _extract(tmp_path, sample_agreement())
    got = [(b.type, b.content[:30], b.section_path[-1]) for b in r.blocks]
    assert got[:3] == [
        ("heading", "Master Services Agreement", "Master Services Agreement"),
        ("paragraph", "Harbor Lane Logistics and Quil", "Master Services Agreement"),
        ("heading", "1. Scope", "1. Scope"),
    ]
    kinds = {b.content[:20]: (b.type, b.format_metadata.get("level")) for b in r.blocks}
    assert kinds["2.1 Availability"] == ("heading", 2)  # custom style based on Heading2
    assert kinds["Real-time parcel trac"[:20]] == ("list_item", None)
    assert kinds["Termination does not"] == ("quote", None)
    assert [b.type for b in r.blocks].count("table") == 2
    assert r.blocks[_block(r, "Severity")].section_path == [
        "Master Services Agreement",
        "2. Service levels",
        "2.2 Response times",
    ]
    assert r.metadata["title"] == "Master Services Agreement" and r.metadata["table_count"] == 2
    assert DocxHandler().extent(None, r.metadata) == f"{r.metadata['word_count']:,} words"


def test_run_level_text_rules(tmp_path: Path) -> None:
    body = p(
        "Pa",
        "rt",
        TAB,
        "one",
        BR,
        "two ",
        deleted("gone "),
        inserted("added "),
        FIELD_PAGE,
        '<w:r><w:sym w:font="Symbol" w:char="F0B7"/></w:r>',
        "<w:r><w:noBreakHyphen/></w:r>",
        "end",
    )
    r = _extract(tmp_path, make_docx(body))
    assert r.blocks[0].content == "Part\tone\ntwo added 3-end"


def test_table_rows_cells_and_merges(tmp_path: Path) -> None:
    data = sample_agreement()
    r = _extract(tmp_path, data)
    rate = r.blocks[_block(r, "Role")]
    assert rate.content == (
        "Role | Day rate\nPlatform engineer | EUR 950\n | EUR 1,150 on weekends\nData analyst | EUR 780 remote"
    )
    sla = r.blocks[_block(r, "Severity")]
    assert "Low | 1 business day by email only | Next release" in sla.content  # two paragraphs in one cell


def test_content_controls_and_unknown_styles(tmp_path: Path) -> None:
    body = sdt(p("Inside a control.")) + p("Body text.", style="NotDefined") + p("By outline.", outline=1)
    r = _extract(tmp_path, make_docx(body, styles=None))
    assert [(b.type, b.content) for b in r.blocks] == [
        ("paragraph", "Inside a control."),
        ("paragraph", "Body text."),
        ("heading", "By outline."),
    ]


def test_long_paragraph_is_split_without_losing_text(tmp_path: Path) -> None:
    sentence = "The carrier must scan every parcel at each depot. "
    data = make_docx(p(sentence * 120))
    r = _extract(tmp_path, data)
    assert len(r.blocks) > 1 and all(len(b.content) <= 2000 for b in r.blocks)
    assert " ".join(b.content for b in r.blocks) == (sentence * 120).strip()
    text = _para_text(data, 0)
    for b in r.blocks:  # every piece maps back to its exact place in the paragraph
        assert isinstance(b.source_location, DocxLocation)
        (region,) = b.source_location.regions
        assert text[region.char_start : region.char_end] == b.content


def test_block_ids_are_stable(tmp_path: Path) -> None:
    a = [b.block_id for b in _extract(tmp_path, sample_agreement()).blocks]
    assert a == [b.block_id for b in _extract(tmp_path, sample_agreement()).blocks]
    assert a[0].startswith("docx:0:0:")


# --- locations ---------------------------------------------------------------------------------------


def test_every_block_location_points_at_its_source_text(tmp_path: Path) -> None:
    data = sample_agreement()
    paras = _paragraph_texts(data)
    for b in _extract(tmp_path, data).blocks:
        loc = b.source_location
        assert isinstance(loc, DocxLocation)
        for seg, region in zip(b.format_metadata["segments"], loc.regions, strict=True):
            assert paras[region.para][region.char_start : region.char_end] == b.content[seg[0] : seg[1]]


def test_locate_quote_in_paragraph(tmp_path: Path) -> None:
    data = sample_agreement()
    r = _extract(tmp_path, data)
    b = r.blocks[_block(r, "Either party")]
    quote = "90 days' written notice"
    i = b.content.index(quote)
    loc = locate("docx", b.content, None, b.format_metadata, i, i + len(quote))
    (region,) = loc["regions"]
    assert _para_text(data, region["para"])[region["char_start"] : region["char_end"]] == quote
    assert describe(loc) == "paragraph 21"


def test_locate_quote_across_table_cells(tmp_path: Path) -> None:
    data = sample_agreement()
    r = _extract(tmp_path, data)
    b = r.blocks[_block(r, "Severity")]
    quote = "Critical | 15 minutes | 4 hours"
    i = b.content.index(quote)
    loc = locate("docx", b.content, None, b.format_metadata, i, i + len(quote))
    assert [_para_text(data, g["para"])[g["char_start"] : g["char_end"]] for g in loc["regions"]] == [
        "Critical",
        "15 minutes",
        "4 hours",
    ]
    assert describe(loc) == "table 1, row 2"
    two_rows = b.content.index("4 hours\nHigh")
    assert describe(locate("docx", b.content, None, b.format_metadata, two_rows, two_rows + 12)) == "table 1, rows 2–3"
    sep = b.content.index(" | ")  # a span on a separator only still points somewhere sensible
    assert locate("docx", b.content, None, b.format_metadata, sep, sep + 2)["regions"]


def test_validator_cites_docx_blocks(tmp_path: Path) -> None:
    r = _extract(tmp_path, sample_agreement())
    blocks = {
        f"b{i}": EvidenceBlock(b.block_id, "docx", b.content, None, b.format_metadata) for i, b in enumerate(r.blocks)
    }
    k = f"b{_block(r, 'Harbor Lane Logistics will pay')}"
    v = validate_segment(
        "The fee is EUR 18,500 a month.", [{"block_id": k, "quote": "fixed monthly fee of EUR 18,500"}], blocks, 90
    )
    assert v.ok
    c = v.citations[0].public()
    assert c["location"]["kind"] == "docx" and c["ref"] == "paragraph 15" and c["page"] is None
    bad = validate_segment("The fee is EUR 19,000.", [{"block_id": k, "quote": "fixed monthly fee"}], blocks, 90)
    assert not bad.ok and bad.reason == "unverified_number"


# --- failures ----------------------------------------------------------------------------------------


def _zip(parts: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in parts.items():
            z.writestr(k, v)
    return buf.getvalue()


def _with_document(xml: str) -> bytes:
    good = zipfile.ZipFile(io.BytesIO(make_docx(p("x"))))
    parts: dict[str, bytes | str] = {n: good.read(n) for n in good.namelist()}
    parts["word/document.xml"] = xml
    return _zip(parts)


@pytest.mark.parametrize(
    ("data", "limits", "code"),
    [
        (CFB_MAGIC + b"\x00" * 600, LIMITS, "encrypted"),
        (b"PK\x03\x04 not really a zip", LIMITS, "parse_failed"),
        (_zip({"hello.txt": "hi"}), LIMITS, "type_mismatch"),  # a zip, not a Word package
        (
            make_docx(p("x"), main_type="application/vnd.ms-word.document.macroEnabled.main+xml"),
            LIMITS,
            "type_mismatch",
        ),
        (make_docx(p("") + p("   ")), LIMITS, "no_text"),
        (make_docx(p("a" * 101)), ExtractLimits(max_pages=1, max_chars=100), "too_long"),
        (_with_document("<w:document xmlns:w='x'><w:body><w:p>"), LIMITS, "parse_failed"),
        (
            _with_document('<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaa">]><d>&a;</d>'),
            LIMITS,
            "unsafe_file",
        ),
    ],
    ids=["encrypted", "not-zip", "plain-zip", "macro", "empty", "too-long", "broken-xml", "dtd"],
)
def test_docx_failures(tmp_path: Path, data: bytes, limits: ExtractLimits, code: str) -> None:
    with pytest.raises(InvalidFile) as e:
        _extract(tmp_path, data, limits)
    assert e.value.code == code


def test_decompression_bomb_is_refused_before_reading(tmp_path: Path) -> None:
    bomb = _with_document("<w:document xmlns:w='x'>" + " " * (MAX_PART_BYTES + 10) + "</w:document>")
    assert len(bomb) < 1024 * 1024  # tiny on disk, 64 MB+ unpacked
    with pytest.raises(InvalidFile) as e:
        _extract(tmp_path, bomb)
    assert e.value.code == "too_large"
    ratio = _with_document("<w:document xmlns:w='x'>" + " " * (8 * 1024 * 1024) + "</w:document>")
    with pytest.raises(InvalidFile) as e:
        _extract(tmp_path, ratio)
    assert e.value.code == "unsafe_file"


def test_docx_extract_runs_in_sandbox(tmp_path: Path) -> None:
    path = tmp_path / "msa.docx"
    path.write_bytes(sample_agreement())
    r = run_sandboxed(DocxHandler().extract, path, LIMITS, timeout_s=60, mem_mb=1024)
    assert len(r.blocks) == 27


def test_nested_and_merged_tables_keep_paragraph_order(tmp_path: Path) -> None:
    body = (
        p("Before")
        + table([cell(p("A")), cell(table([cell(p("B1")), cell(p("B2"))]))], [cell(merge="continue"), cell(p("C"))])
        + p("After")
    )
    data = make_docx(body)
    assert _paragraph_texts(data) == ["Before", "A", "B1", "B2", "", "C", "After"]
    r = _extract(tmp_path, data)
    after = r.blocks[-1].source_location
    assert isinstance(after, DocxLocation) and after.regions[0].para == 6
