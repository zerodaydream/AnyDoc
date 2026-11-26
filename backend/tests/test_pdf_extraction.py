from pathlib import Path

import pytest

from backend.core.errors import InvalidFile
from backend.extraction.formats.pdf.extractor import extract_pdf
from backend.extraction.registry import detect
from backend.extraction.sandbox import run_sandboxed
from backend.tests.pdfgen import Page, Text, make_pdf, sample_report


def _write(tmp_path: Path, data: bytes, name: str = "f.pdf") -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_blocks_headings_and_sections(tmp_path: Path) -> None:
    r = extract_pdf(_write(tmp_path, sample_report()), 500)
    assert r.page_count == 2
    kinds = [(b.page, b.type, b.content[:20]) for b in r.blocks]
    assert kinds[0] == (1, "heading", "Quarterly Report")
    para = r.blocks[1]
    # Two lines 14pt apart join into one paragraph; the line 46pt lower is a new block.
    assert para.content.startswith("Revenue for the third quarter was $4.2 million, up 12% from the second quarter.")
    assert para.source_location.kind == "pdf" and len(para.source_location.regions[0].rects) == 2
    assert para.section_path == ["Quarterly Report"]
    outlook = next(b for b in r.blocks if b.content == "Outlook")
    assert outlook.type == "heading"  # bold, body-ish size
    assert r.blocks[-1].section_path == ["Outlook"]
    assert all(b.block_id.startswith(f"pdf:{b.page}:") for b in r.blocks)


def test_block_ids_are_stable(tmp_path: Path) -> None:
    a = extract_pdf(_write(tmp_path, sample_report()), 500)
    b = extract_pdf(_write(tmp_path, sample_report(), "g.pdf"), 500)
    assert [x.block_id for x in a.blocks] == [x.block_id for x in b.blocks]


@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
@pytest.mark.parametrize("crop", [None, (50, 60, 562, 732)])
def test_word_boxes_in_unrotated_user_space(
    tmp_path: Path, rotate: int, crop: tuple[float, float, float, float] | None
) -> None:
    """Boxes must be PDF user space regardless of /Rotate and /CropBox: pdf.js applies both itself."""
    pdf = make_pdf([Page([Text(100, 500, 12, "Hello world")], rotate=rotate, crop=crop)])
    b = extract_pdf(_write(tmp_path, pdf), 500).blocks[0]
    (s0, e0, l, bot, r, top), _ = b.format_metadata["words"]
    assert b.content[s0:e0] == "Hello"
    assert abs(l - 100) < 1.5
    assert 497 <= bot <= 501 and 506 <= top <= 513
    assert r < 140


def test_malformed_pdf(tmp_path: Path) -> None:
    with pytest.raises(InvalidFile) as e:
        extract_pdf(_write(tmp_path, b"%PDF-1.7\nthis is not a pdf\n%%EOF"), 500)
    assert e.value.code == "malformed_pdf"


def test_truncated_pdf_fails_gracefully(tmp_path: Path) -> None:
    data = sample_report()
    with pytest.raises(InvalidFile):
        extract_pdf(_write(tmp_path, data[: len(data) // 3]), 500)


def test_no_text_layer(tmp_path: Path) -> None:
    with pytest.raises(InvalidFile) as e:
        extract_pdf(_write(tmp_path, make_pdf([Page([])])), 500)
    assert e.value.code == "no_text_layer"


def test_page_limit(tmp_path: Path) -> None:
    with pytest.raises(InvalidFile) as e:
        extract_pdf(_write(tmp_path, make_pdf([Page([Text(72, 700, 11, "x")])] * 3)), 2)
    assert e.value.code == "too_many_pages"


def test_detect_requires_extension_and_magic() -> None:
    assert detect("a.PDF", b"%PDF-1.7 ...").name == "pdf"
    with pytest.raises(InvalidFile) as e:
        detect("a.pdf", b"PK\x03\x04 zip")
    assert e.value.code == "type_mismatch"
    with pytest.raises(InvalidFile) as e:
        detect("a.exe", b"%PDF-")
    assert e.value.code == "unsupported_format"


def _sleep(_: object) -> None:
    import time

    time.sleep(10)


def _crash(_: object) -> None:
    import os

    os._exit(3)


def test_sandbox_timeout_and_crash() -> None:
    with pytest.raises(InvalidFile) as e:
        run_sandboxed(_sleep, None, timeout_s=1, mem_mb=512)
    assert e.value.code == "parse_timeout"
    with pytest.raises(InvalidFile) as e:
        run_sandboxed(_crash, None, timeout_s=10, mem_mb=512)
    assert e.value.code == "parse_crashed"


def test_sandbox_runs_extractor(tmp_path: Path) -> None:
    from backend.document_ir.models import ExtractLimits
    from backend.extraction.formats.pdf.handler import PdfHandler

    limits = ExtractLimits(max_pages=500, max_chars=10_000)
    r = run_sandboxed(PdfHandler().extract, _write(tmp_path, sample_report()), limits, timeout_s=60, mem_mb=1024)
    assert r.page_count == 2
    with pytest.raises(InvalidFile) as e:
        run_sandboxed(
            PdfHandler().extract,
            _write(tmp_path, b"%PDF-1.4 junk", "bad.pdf"),
            limits,
            timeout_s=60,
            mem_mb=1024,
        )
    assert e.value.code == "malformed_pdf"
