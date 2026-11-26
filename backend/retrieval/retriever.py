"""Router + hybrid retrieval baseline (ARCHITECTURE §7). Every query is owner-scoped."""

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Block, Chunk
from backend.indexing.embeddings import Embedder
from backend.observability.tracing import trace_metadata, traced
from backend.security.auth import Principal

RRF_K = 60
CANDIDATES = 30
# OR the stemmed lexemes: websearch/plainto AND every term, which drops most natural questions.
_OR_TSQUERY = "replace(plainto_tsquery('english', :q)::text, '&', '|')::tsquery"
_LEXICAL_SQL = text(
    "SELECT id FROM chunks WHERE version_id = :v AND owner_id = :o AND workspace_id = :w "  # noqa: S608 - constants only
    f"AND tsv @@ {_OR_TSQUERY} ORDER BY ts_rank_cd(tsv, {_OR_TSQUERY}) DESC LIMIT :n"
)


@dataclass(slots=True)
class Retrieved:
    blocks: list[Block]
    route: str  # full_context | hybrid
    ranked_block_ids: list[str]


def _blocks_q(principal: Principal, version_id: uuid.UUID) -> Select[Block]:
    return select(Block).where(
        Block.version_id == version_id,
        Block.owner_id == principal.owner_id,
        Block.workspace_id == principal.workspace_id,
    )


async def lexical_chunk_ids(
    session: AsyncSession, principal: Principal, version_id: uuid.UUID, q: str, limit: int
) -> list[int]:
    rows = await session.execute(
        _LEXICAL_SQL,
        {"v": version_id, "o": principal.owner_id, "w": principal.workspace_id, "q": q, "n": limit},
    )
    return [r[0] for r in rows]


async def vector_chunk_ids(
    session: AsyncSession, principal: Principal, version_id: uuid.UUID, qvec: list[float], limit: int
) -> list[int]:
    rows = await session.execute(
        select(Chunk.id)
        .where(
            Chunk.version_id == version_id,
            Chunk.owner_id == principal.owner_id,
            Chunk.workspace_id == principal.workspace_id,
            Chunk.embedding.is_not(None),
        )
        .order_by(Chunk.embedding.cosine_distance(qvec))
        .limit(limit)
    )
    return [r[0] for r in rows]


def rrf(*rankings: list[int]) -> list[int]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
    return sorted(scores, key=lambda c: -scores[c])


@traced("retrieve", run_type="retriever")
async def retrieve(
    session: AsyncSession,
    principal: Principal,
    version_id: uuid.UUID,
    question: str,
    embedder: Embedder,
    budget_tokens: int,
    top_k: int,
) -> Retrieved:
    total = await session.scalar(
        select(func.coalesce(func.sum(Block.token_estimate), 0)).where(
            Block.version_id == version_id,
            Block.owner_id == principal.owner_id,
            Block.workspace_id == principal.workspace_id,
        )
    )
    if (total or 0) <= budget_tokens:
        blocks = list((await session.scalars(_blocks_q(principal, version_id).order_by(Block.ordinal))).all())
        trace_metadata(route="full_context", total_tokens=total, blocks=len(blocks))
        return Retrieved(blocks, "full_context", [])

    lex = await lexical_chunk_ids(session, principal, version_id, question, CANDIDATES)
    vec = await vector_chunk_ids(session, principal, version_id, await embedder.embed_query(question), CANDIDATES)
    top = rrf(lex, vec)[:top_k]
    chunks = {c.id: c for c in (await session.scalars(select(Chunk).where(Chunk.id.in_(top)))).all()}
    ranked = [bid for cid in top if cid in chunks for bid in chunks[cid].block_ids]

    # Neighbour expansion: +-1 block around every hit, by ordinal. A block's rank is (best hit's rank, neighbour?),
    # so a hit outranks the neighbours that share its rank.
    rows = await session.execute(
        select(Block.block_id, Block.ordinal).where(Block.version_id == version_id, Block.block_id.in_(ranked))
    )
    ordinal_of = {bid: ordinal for bid, ordinal in rows}
    rank: dict[int, tuple[int, int]] = {}
    for i, bid in enumerate(ranked):
        if bid in ordinal_of:
            for d in (-1, 0, 1):
                o = ordinal_of[bid] + d
                rank[o] = min(rank.get(o, (i, 1)), (i, int(d != 0)))
    wanted = set(rank)
    blocks = list(
        (
            await session.scalars(
                _blocks_q(principal, version_id).where(Block.ordinal.in_(wanted)).order_by(Block.ordinal)
            )
        ).all()
    )
    # Small budgets (Groq's free plan) can't take every hit: keep the best-ranked blocks that fit, in reading order.
    if sum(b.token_estimate for b in blocks) > budget_tokens:
        kept: set[int] = set()
        used = 0
        for b in sorted(blocks, key=lambda b: rank[b.ordinal]):
            if not kept or used + b.token_estimate <= budget_tokens:  # always keep the best hit
                kept.add(b.ordinal)
                used += b.token_estimate
        blocks = [b for b in blocks if b.ordinal in kept]
    trace_metadata(
        route="hybrid",
        total_tokens=total,
        lexical_hits=len(lex),
        vector_hits=len(vec),
        chunk_ids=top,
        blocks=len(blocks),
    )
    return Retrieved(blocks, "hybrid", ranked)


async def closest_blocks(
    session: AsyncSession, principal: Principal, version_id: uuid.UUID, q: str, n: int = 3
) -> list[Block]:
    """Lexical best matches, used to show 'closest passages' when the answer abstains."""
    ids = await lexical_chunk_ids(session, principal, version_id, q, n)
    if not ids:
        return []
    chunks = (await session.scalars(select(Chunk).where(Chunk.id.in_(ids)))).all()
    first_ids = [c.block_ids[0] for c in sorted(chunks, key=lambda c: ids.index(c.id))]
    by_id = {
        b.block_id: b
        for b in (await session.scalars(_blocks_q(principal, version_id).where(Block.block_id.in_(first_ids)))).all()
    }
    return [by_id[i] for i in first_ids if i in by_id]
