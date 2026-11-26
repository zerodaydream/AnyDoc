"""TXT / Markdown: decoding, block detection, exact locations, limits and malformed input."""

from pathlib import Path

import pytest

from backend.core.errors import InvalidFile
from backend.document_ir.models import ExtractLimits, ExtractResult, TextLocation
from backend.extraction.formats.text.decode import decode_text, looks_like_text
from backend.extraction.formats.text.extractor import MAX_BLOCK_CHARS, extract_text
from backend.extraction.registry import describe, detect, locate
from backend.extraction.sandbox import run_sandboxed
from backend.grounding.validator import EvidenceBlock, validate_segment

LIMITS = ExtractLimits(max_pages=500, max_chars=1_000_000)

GUIDE_MD = (
    "---\ntitle: Ops guide\n---\n"  # 1-3 front matter
    "# Ops guide\r\n"  # 4 (CRLF on purpose)
    "\r\n"
    "The service listens on port 8443 and ☕ restarts nightly 😀.\n"  # 6
    "Logs rotate after 14 days.\n"  # 7
    "\n"
    "## Deploy\n"  # 9
    "\n"
    "- Build the image\n"  # 11
    "  with `make image`.\n"  # 12
    "- Push it to the registry.\n"  # 13
    "\n"
    "> Never deploy on Fridays.\n"  # 15
    "\n"
    "```bash\nmake deploy ENV=prod\n```\n"  # 17-19
    "\n"
    "| env | replicas |\n|---|---|\n| prod | 6 |\n"  # 21-23
    "\n"
    "Rollback\n--------\n"  # 25-26
    "\n"
    "Run make rollback within 30 minutes.\n"  # 28
)


def _extract(tmp_path: Path, data: bytes | str, name: str = "f.md", limits: ExtractLimits = LIMITS) -> ExtractResult:
    p = tmp_path / name
    p.write_bytes(data.encode() if isinstance(data, str) else data)
    return extract_text(p, limits, markdown=name.endswith(".md"))


def _text_regions(r: ExtractResult) -> list[tuple[int, int, int, int]]:
    out = []
    for b in r.blocks:
        assert isinstance(b.source_location, TextLocation)
        g = b.source_location.regions[0]
        out.append((g.char_start, g.char_end, g.line_start, g.line_end))
    return out


# --- decoding --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "text", "label"),
    [
        (b"plain\r\nwindows\rold mac\n", "plain\nwindows\nold mac\n", "utf-8"),
        (b"\xef\xbb\xbfbom caf\xc3\xa9", "bom café", "utf-8"),
        ("﻿wide é 😀".encode("utf-16-le"), "wide é 😀", "utf-16le"),
        ("﻿big é".encode("utf-16-be"), "big é", "utf-16be"),
        (b"caf\xe9 \x93quoted\x94", "café “quoted”", "windows-1252"),
    ],
)
def test_decode(data: bytes, text: str, label: str) -> None:
    assert decode_text(data) == (text, label)


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"text\x00with nul", "not_text"),
        (b"\x81\x8d\x8f undefined in cp1252 and invalid utf-8", "unsupported_encoding"),
        (b"\xff\xfe\x41", "malformed_text"),  # UTF-16 BOM with an odd byte count
        (bytes(range(1, 32)) * 4, "not_text"),  # control characters
    ],
)
def test_decode_rejects(data: bytes, code: str) -> None:
    with pytest.raises(InvalidFile) as e:
        decode_text(data)
    assert e.value.code == code


def test_sniff_and_detect() -> None:
    assert looks_like_text("naïve".encode()[:3])  # cut mid-character is fine
    assert not looks_like_text(b"\x89PNG\r\n\x1a\n\x00\x00")
    assert not looks_like_text(b"PK\x03\x04\x14\x00\x00\x00")
    assert detect("notes.TXT", b"hello").name == "text"
    assert detect("README.markdown", b"# hi").name == "markdown"
    with pytest.raises(InvalidFile) as e:
        detect("photo.md", b"\x89PNG\r\n\x1a\n\x00\x00\x00")
    assert e.value.code == "type_mismatch"


# --- markdown --------------------------------------------------------------------------------------


def test_markdown_blocks_types_and_sections(tmp_path: Path) -> None:
    r = _extract(tmp_path, GUIDE_MD)
    got = [(b.type, b.format_metadata["line"], b.content.split("\n")[0]) for b in r.blocks]
    assert got == [
        ("code", 1, "---"),
        ("heading", 4, "# Ops guide"),
        ("paragraph", 6, "The service listens on port 8443 and ☕ restarts nightly 😀."),
        ("heading", 9, "## Deploy"),
        ("list_item", 11, "- Build the image"),
        ("list_item", 13, "- Push it to the registry."),
        ("quote", 15, "> Never deploy on Fridays."),
        ("code", 17, "```bash"),
        ("table", 21, "| env | replicas |"),
        ("heading", 25, "Rollback"),
        ("paragraph", 28, "Run make rollback within 30 minutes."),
    ]
    by_line = {b.format_metadata["line"]: b for b in r.blocks}
    assert by_line[1].format_metadata["front_matter"] is True
    assert by_line[17].format_metadata["lang"] == "bash"
    assert by_line[11].section_path == ["Ops guide", "Deploy"]
    assert by_line[28].section_path == ["Ops guide", "Rollback"]  # setext h2 replaces the h2 above it
    assert r.page_count is None
    assert r.metadata["title"] == "Ops guide" and r.metadata["line_count"] == 28


def test_every_block_is_an_exact_slice_of_the_decoded_text(tmp_path: Path) -> None:
    raw = GUIDE_MD.encode()
    text, _ = decode_text(raw)
    lines = text.split("\n")
    r = _extract(tmp_path, raw)
    for b, (start, end, l0, l1) in zip(r.blocks, _text_regions(r), strict=True):
        assert text[start:end] == b.content  # code-point offsets, astral chars included
        assert lines[l0 - 1].startswith(b.content.split("\n")[0])
        assert l1 - l0 == b.content.count("\n")


def test_block_ids_are_stable(tmp_path: Path) -> None:
    a = [b.block_id for b in _extract(tmp_path, GUIDE_MD).blocks]
    b = [b.block_id for b in _extract(tmp_path, GUIDE_MD, "g.md").blocks]
    assert a == b and len(set(a)) == len(a) and a[1].startswith("md:4:1:")


# --- plain text ------------------------------------------------------------------------------------


def test_plain_text_paragraphs_and_headings(tmp_path: Path) -> None:
    src = (
        "TERMS AND CONDITIONS\n\n"
        "1. Definitions.\n\n"
        "A paragraph that wraps\nover two lines.\n\n"
        "Section title\n=============\n\n"
        "# not markdown here\n"
    )
    r = _extract(tmp_path, src, "f.txt")
    assert [(b.type, b.content) for b in r.blocks] == [
        ("heading", "TERMS AND CONDITIONS"),
        ("heading", "1. Definitions."),
        ("paragraph", "A paragraph that wraps\nover two lines."),
        ("heading", "Section title\n============="),
        ("paragraph", "# not markdown here"),
    ]
    assert r.blocks[2].section_path == ["1. Definitions."]
    assert r.blocks[0].block_id.startswith("txt:1:0:")


def test_long_paragraph_is_split_without_losing_text(tmp_path: Path) -> None:
    sentence = "The quick brown fox jumps over the lazy dog again and again. "
    src = "Intro.\n\n" + sentence * 120 + "\n" + "x" * (MAX_BLOCK_CHARS * 2 + 5)
    text = src
    r = _extract(tmp_path, src, "f.txt")
    assert all(len(b.content) <= MAX_BLOCK_CHARS for b in r.blocks)
    regions = _text_regions(r)
    for b, (s, e, _, _) in zip(r.blocks, regions, strict=True):
        assert text[s:e] == b.content
    # Pieces of the long paragraph tile it: no gap except whitespace at the cut.
    for (_, e1, _, _), (s2, _, _, _) in zip(regions[1:], regions[2:], strict=False):
        assert text[e1:s2].strip() == ""
    assert r.blocks[1].content.endswith("again.")  # cut at a sentence boundary


@pytest.mark.parametrize(
    ("data", "limits", "code"),
    [
        (b"", LIMITS, "no_text"),
        (b" \n\t\n", LIMITS, "no_text"),
        (b"a" * 101, ExtractLimits(max_pages=1, max_chars=100), "too_long"),
        (b"\x00\x01binary", LIMITS, "not_text"),
    ],
)
def test_text_failures(tmp_path: Path, data: bytes, limits: ExtractLimits, code: str) -> None:
    with pytest.raises(InvalidFile) as e:
        _extract(tmp_path, data, "f.txt", limits)
    assert e.value.code == code


def test_text_extract_runs_in_sandbox(tmp_path: Path) -> None:
    from backend.extraction.formats.text.handler import MARKDOWN

    p = tmp_path / "g.md"
    p.write_text(GUIDE_MD)
    r = run_sandboxed(MARKDOWN.extract, p, LIMITS, timeout_s=60, mem_mb=1024)
    assert len(r.blocks) == 11
    assert MARKDOWN.extent(None, r.metadata) == "28 lines"


# --- locations and citations -----------------------------------------------------------------------


def test_locate_quote_inside_block(tmp_path: Path) -> None:
    raw = GUIDE_MD.encode()
    text, _ = decode_text(raw)
    para = _extract(tmp_path, raw).blocks[2]
    quote = "restarts nightly 😀.\nLogs rotate"
    i = para.content.index(quote)
    loc = locate("text", para.content, None, para.format_metadata, i, i + len(quote))
    (region,) = loc["regions"]
    assert text[region["char_start"] : region["char_end"]] == quote
    assert (region["line_start"], region["line_end"]) == (6, 7)
    assert describe(loc) == "lines 6–7"
    one = locate("text", para.content, None, para.format_metadata, 0, 3)
    assert describe(one) == "line 6"


def test_validator_cites_text_blocks_with_line_refs(tmp_path: Path) -> None:
    blocks = {
        f"b{i}": EvidenceBlock(b.block_id, "text", b.content, None, b.format_metadata)
        for i, b in enumerate(_extract(tmp_path, GUIDE_MD).blocks)
    }
    v = validate_segment(
        "Logs rotate after 14 days.", [{"block_id": "b2", "quote": "Logs rotate after 14 days."}], blocks, 90
    )
    assert v.ok
    c = v.citations[0].public()
    assert c["location"]["kind"] == "text" and c["ref"] == "line 7" and c["page"] is None
    bad = validate_segment("Logs rotate after 15 days.", [{"block_id": "b2", "quote": "Logs rotate"}], blocks, 90)
    assert not bad.ok and bad.reason == "unverified_number"


def test_plain_text_run_in_numbered_titles_set_the_section(tmp_path: Path) -> None:
    src = "1. Definitions.\n\nTerms.\n\n2. Grant of License. Subject to the terms,\nyou may copy.\n\nMore text.\n"
    r = _extract(tmp_path, src, "f.txt")
    assert [(b.type, b.section_path) for b in r.blocks] == [
        ("heading", ["1. Definitions."]),
        ("paragraph", ["1. Definitions."]),
        ("paragraph", ["2. Grant of License."]),  # run-in title: stays a paragraph, starts a section
        ("paragraph", ["2. Grant of License."]),
    ]
