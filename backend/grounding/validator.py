"""Citation validation (ARCHITECTURE §8). Only citations that pass reach the client."""

import re
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from backend.extraction.registry import locate
from backend.grounding.normalize import normalize

MIN_FUZZY_QUOTE = 12
LOW_CONFIDENCE = 0.8
_NUM = re.compile(r"(?<![\w.])[-−]?\d[\d,]*(?:\.\d+)?%?")
_WORD = re.compile(r"[^\W_]{3,}")
_STOP = frozenset(
    [
        "the",
        "and",
        "for",
        "are",
        "was",
        "were",
        "with",
        "that",
        "this",
        "from",
        "have",
        "has",
        "had",
        "not",
        "but",
        "its",
        "their",
        "they",
        "them",
        "which",
        "what",
        "when",
        "where",
        "who",
        "will",
        "would",
        "can",
        "could",
        "should",
        "may",
        "might",
        "also",
        "into",
        "than",
        "then",
        "there",
        "these",
        "those",
        "such",
        "been",
        "being",
        "more",
        "most",
        "other",
        "some",
        "only",
        "over",
        "each",
        "about",
        "after",
        "before",
        "between",
        "both",
        "does",
        "did",
        "very",
    ]
)


@dataclass(frozen=True, slots=True)
class EvidenceBlock:
    block_id: str
    kind: str
    content: str
    page: int | None
    format_metadata: dict[str, Any]
    confidence: float | None = None


@dataclass(slots=True)
class Citation:
    block_id: str
    quote: str  # the verbatim span from OUR block text, not the model's string
    page: int | None
    location: dict[str, Any]
    match: str  # exact | normalized | fuzzy
    score: float
    flags: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "quote": self.quote,
            "page": self.page,
            "location": self.location,
            "match": self.match,
            "score": round(self.score, 1),
            "flags": self.flags,
        }


@dataclass(slots=True)
class SegmentVerdict:
    citations: list[Citation]
    rejected: list[dict[str, str]]  # {block_id, reason} — logged, never shown as citations
    ok: bool
    reason: str | None = None


def match_quote(quote: str, content: str, fuzzy_min: float) -> tuple[int, int, str, float] | None:
    """Find quote in content. Returns raw (start, end, method, score) or None."""
    q = quote.strip()
    if not q:
        return None
    i = content.find(q)
    if i >= 0:
        return i, i + len(q), "exact", 100.0
    qn, _ = normalize(q)
    cn, cmap = normalize(content)
    if not qn or not cn:
        return None
    j = cn.find(qn)
    if j >= 0:
        return cmap[j], cmap[j + len(qn) - 1] + 1, "normalized", 100.0
    if len(qn) < MIN_FUZZY_QUOTE:
        return None
    al = fuzz.partial_ratio_alignment(qn, cn, score_cutoff=fuzzy_min)
    if al is None or al.dest_end <= al.dest_start:
        return None
    return cmap[al.dest_start], cmap[al.dest_end - 1] + 1, "fuzzy", al.score


def _numbers(text: str) -> set[str]:
    return {m.group().replace(",", "").replace("−", "-").rstrip("%") for m in _NUM.finditer(text)}


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.casefold()) if w not in _STOP}


def validate_segment(
    text: str, evidence: list[dict[str, str]], blocks: dict[str, EvidenceBlock], fuzzy_min: float
) -> SegmentVerdict:
    """`blocks` must contain only blocks of this document version owned by the caller."""
    citations: list[Citation] = []
    rejected: list[dict[str, str]] = []
    for ev in evidence:
        bid, quote = str(ev.get("block_id", "")), str(ev.get("quote", ""))
        block = blocks.get(bid)
        if block is None:
            rejected.append({"block_id": bid, "reason": "unknown_block"})
            continue
        m = match_quote(quote, block.content, fuzzy_min)
        if m is None:
            rejected.append({"block_id": bid, "reason": "quote_not_found"})
            continue
        start, end, method, score = m
        flags = []
        if block.confidence is not None and block.confidence < LOW_CONFIDENCE:
            flags.append("low_confidence")
        citations.append(
            Citation(
                bid,
                block.content[start:end],
                block.page,
                locate(block.kind, block.page, block.format_metadata, start, end),
                method,
                score,
                flags,
            )
        )

    if not citations:
        return SegmentVerdict([], rejected, ok=False, reason="no_valid_evidence")

    cited_text = " ".join(blocks[c.block_id].content for c in citations)
    missing = _numbers(text) - _numbers(cited_text)
    if missing:
        return SegmentVerdict([], rejected, ok=False, reason="unverified_number")

    seg_words = _content_words(text)
    if seg_words and len(seg_words & _content_words(cited_text)) / len(seg_words) < 0.2:
        for c in citations:
            c.flags.append("weak_support")
    # Deduplicate identical spans the model cited twice.
    unique = list({(c.block_id, c.quote): c for c in citations}.values())
    return SegmentVerdict(unique, rejected, ok=True)
