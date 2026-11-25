"""Measure local embedder load time, throughput and peak RSS on real PDF chunks.

Usage: uv run python scripts/research/bench_embedder.py <pdf> [device]
"""

import asyncio
import resource
import sys
import time
from pathlib import Path

from backend.extraction.formats.pdf.extractor import extract_pdf
from backend.indexing.chunker import chunk_blocks
from backend.indexing.embeddings import LocalEmbedder, pick_device


async def main(pdf: str, device: str) -> None:
    chunks = chunk_blocks(extract_pdf(Path(pdf), 500).blocks)
    emb = LocalEmbedder("microsoft/harrier-oss-v1-270m", 640, device, 16)
    t = time.perf_counter()
    await emb.embed_documents(["warmup"])
    load = time.perf_counter() - t
    t = time.perf_counter()
    vecs = await emb.embed_documents([c.text for c in chunks])
    dt = time.perf_counter() - t
    q = await emb.embed_query("How many attention heads does the base model use?")
    best = max(range(len(vecs)), key=lambda i: sum(a * b for a, b in zip(q, vecs[i], strict=True)))
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20  # macOS reports bytes
    print(f"device={pick_device(device)} chunks={len(chunks)} load={load:.1f}s embed={dt:.1f}s "
          f"({len(chunks) / dt:.1f} chunks/s) peak_rss={rss:.0f}MB dim={len(vecs[0])}")
    print("top hit for query:", chunks[best].text[:160].replace("\n", " "))


asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "auto"))
