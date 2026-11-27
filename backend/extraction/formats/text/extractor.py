"""TXT / Markdown -> IR blocks. Block content is the exact source slice, so locations are plain offsets.

Markdown block structure comes from markdown-it-py's CommonMark parser: every block token carries
the source line range it came from (`token.map`). Nothing is rendered; the viewer shows the source.
Runs inside the parsing sandbox: pure function, no DB, no network.
"""

import hashlib
import re
from bisect import bisect_right
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt

from backend.core.errors import InvalidFile
from backend.document_ir.models import BlockType, ExtractLimits, ExtractResult, IRBlock, TextLocation, TextRegion
from backend.extraction.formats.text.decode import decode_text
from backend.extraction.split import MAX_BLOCK_CHARS as MAX_BLOCK_CHARS
from backend.extraction.split import cut

_MD_VERSION = version("markdown-it-py")
_UNDERLINE = re.compile(r"^\s*(=+|-+)\s*$")
_NUMBERED = re.compile(r"^\s*\d+(\.\d+)*\.?\s+\S")
# "2. Grant of Copyright License. Subject to ..." -> a run-in section title at the start of a paragraph.
_RUN_IN = re.compile(r"^\s*(\d+(?:\.\d+)*\.\s+[A-Z][^.\n]{2,78}\.)(?:\s|$)")
_ATX = re.compile(r"^\s{0,3}#{1,6}\s*|\s+#+\s*$")


@dataclass(slots=True)
class Span:
    """A block candidate as 0-based [line_start, line_end) source lines."""

    line_start: int
    line_end: int
    type: BlockType
    heading: str | None = None  # clean heading text (no markers); may be set on a paragraph (run-in title)
    level: int = 1
    meta: dict[str, Any] = field(default_factory=dict)


def _plain_spans(lines: list[str]) -> list[Span]:
    """Paragraphs are runs of non-blank lines. Headings are guessed conservatively (see limitations)."""
    spans: list[Span] = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j].strip():
            j += 1
        first = lines[i].strip()
        underlined = j - i == 2 and len(lines[i + 1].strip()) >= 3 and bool(_UNDERLINE.match(lines[i + 1]))
        letters = [c for c in first if c.isalpha()]
        single = j - i == 1 and len(first) <= 80 and len(letters) >= 2
        all_caps = single and all(c.isupper() for c in letters) and first[-1] not in ".,;:"
        numbered = single and bool(_NUMBERED.match(first)) and len(first.split()) <= 6
        if underlined or all_caps or numbered:
            spans.append(Span(i, j, "heading", heading=first, level=2 if underlined and "-" in lines[i + 1] else 1))
        else:
            run_in = _RUN_IN.match(lines[i])
            spans.append(Span(i, j, "paragraph", heading=run_in.group(1) if run_in else None))
        i = j
    return spans


def _front_matter_end(lines: list[str]) -> int:
    """YAML front matter (`---` ... `---`/`...` at the very top) -> number of lines it spans, else 0."""
    if not lines or lines[0].strip() != "---":
        return 0
    for k in range(1, min(len(lines), 500)):
        if lines[k].strip() in ("---", "..."):
            return k + 1
    return 0


def _markdown_spans(lines: list[str]) -> list[Span]:
    fm = _front_matter_end(lines)
    spans = [Span(0, fm, "code", meta={"front_matter": True})] if fm else []
    # Blank the front matter (keeps line numbers) so CommonMark doesn't read it as a rule + setext heading.
    src = "\n" * fm + "\n".join(lines[fm:])
    tokens = MarkdownIt("commonmark").enable("table").parse(src)
    containers: list[str] = []
    in_table = False
    for k, t in enumerate(tokens):
        if t.type in ("list_item_open", "blockquote_open"):
            containers.append(t.type)
        elif t.type in ("list_item_close", "blockquote_close"):
            containers.pop()
        elif t.type == "table_close":
            in_table = False
        if in_table or not t.map:
            continue
        a, b = t.map
        if t.type == "heading_open":
            text = tokens[k + 1].content.strip() if k + 1 < len(tokens) else ""
            spans.append(Span(a, b, "heading", heading=_ATX.sub("", text) or text, level=int(t.tag[1:])))
        elif t.type == "paragraph_open":
            kind: BlockType = "paragraph"
            if containers:
                kind = "list_item" if containers[-1] == "list_item_open" else "quote"
            spans.append(Span(a, b, kind))
        elif t.type in ("fence", "code_block"):
            lang = t.info.strip().split()[0] if t.info.strip() else None
            spans.append(Span(a, b, "code", meta={"lang": lang} if lang else {}))
        elif t.type == "table_open":
            in_table = True
            spans.append(Span(a, b, "table"))
        elif t.type == "html_block":
            spans.append(Span(a, b, "paragraph", meta={"html": True}))
    return spans


def _trimmed(text: str, start: int, end: int) -> tuple[int, int]:
    while end > start and text[end - 1].isspace():
        end -= 1
    while start < end and text[start] in "\n":
        start += 1
    return start, end


def extract_text(path: Path, limits: ExtractLimits, markdown: bool) -> ExtractResult:
    text, encoding = decode_text(path.read_bytes())
    if len(text) > limits.max_chars:
        raise InvalidFile("too_long", f"This file has {len(text):,} characters; the limit is {limits.max_chars:,}.")
    if not text.strip():
        raise InvalidFile("no_text", "This file has no text in it.")

    lines = text.split("\n")  # not splitlines(): only "\n" ends a line, exactly as in the viewer
    starts = [0]
    for ln in lines[:-1]:
        starts.append(starts[-1] + len(ln) + 1)
    prefix = "md" if markdown else "txt"

    blocks: list[IRBlock] = []
    heads: list[tuple[int, str]] = []  # (level, text) stack -> section_path
    for sp in _markdown_spans(lines) if markdown else _plain_spans(lines):
        if sp.heading:
            while heads and heads[-1][0] >= sp.level:
                heads.pop()
            heads.append((sp.level, sp.heading[:200]))
        start = starts[sp.line_start]
        end = starts[sp.line_end - 1] + len(lines[sp.line_end - 1])
        start, end = _trimmed(text, start, end)
        if start >= end:
            continue
        for a, b in cut(text, start, end, MAX_BLOCK_CHARS):
            a, b = _trimmed(text, a, b)
            if a >= b:
                continue
            content = text[a:b]
            line_start = bisect_right(starts, a)
            line_end = bisect_right(starts, b - 1)
            meta: dict[str, Any] = {"start": a, "line": line_start, **sp.meta}
            if sp.type == "heading":
                meta["level"] = sp.level
            digest = hashlib.sha1(content.encode(), usedforsecurity=False).hexdigest()[:8]
            blocks.append(
                IRBlock(
                    block_id=f"{prefix}:{line_start}:{len(blocks)}:{digest}",
                    ordinal=len(blocks),
                    type=sp.type,
                    content=content,
                    page=None,
                    source_location=TextLocation(
                        regions=[TextRegion(char_start=a, char_end=b, line_start=line_start, line_end=line_end)]
                    ),
                    format_metadata=meta,
                    section_path=[h for _, h in heads],
                )
            )

    if not blocks:
        raise InvalidFile("no_text", "This file has no text in it.")
    title = next((b.section_path[-1] for b in blocks if b.format_metadata.get("level") == 1 and b.section_path), "")
    return ExtractResult(
        page_count=None,
        blocks=blocks,
        metadata={
            "title": title,
            "encoding": encoding,
            "line_count": len(lines) - (1 if text.endswith("\n") else 0),
            "char_count": len(text),
            "extractor": f"markdown-it-py-{_MD_VERSION}" if markdown else "plain-text",
        },
    )
