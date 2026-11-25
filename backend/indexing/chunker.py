"""Structure-aware chunks: consecutive blocks of one section, capped by tokens, tied to block ids."""

from dataclasses import dataclass

from backend.document_ir.models import IRBlock

MAX_CHUNK_TOKENS = 350


@dataclass(slots=True)
class ChunkDraft:
    block_ids: list[str]
    text: str


def chunk_blocks(blocks: list[IRBlock], max_tokens: int = MAX_CHUNK_TOKENS) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    ids: list[str] = []
    parts: list[str] = []
    tokens = 0
    section: list[str] = []

    def flush() -> None:
        nonlocal ids, parts, tokens
        if ids:
            prefix = f"{section[0]}\n" if section and parts and parts[0] != section[0] else ""
            chunks.append(ChunkDraft(ids, prefix + "\n".join(parts)))
        ids, parts, tokens = [], [], 0

    for b in blocks:
        if b.type == "heading" or b.section_path != section or tokens + b.token_estimate > max_tokens:
            flush()
            section = b.section_path
        ids.append(b.block_id)
        parts.append(b.content)
        tokens += b.token_estimate
    flush()
    return chunks
