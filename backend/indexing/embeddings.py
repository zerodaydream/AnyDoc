"""Embedder boundary. Local sentence-transformers by default; a hashing fake for tests."""

import asyncio
import hashlib
import logging
import math
import threading
from functools import lru_cache
from typing import Any, Protocol

from backend.core.config import get_settings

log = logging.getLogger(__name__)


class Embedder(Protocol):
    model_id: str
    dim: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...


def pick_device(pref: str) -> str:
    if pref != "auto":
        return pref
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class LocalEmbedder:
    """harrier-oss-v1: queries take a retrieval instruction, documents take none (model card)."""

    QUERY_PROMPT = "Instruct: Given a question, retrieve passages from a document that answer it\nQuery: "

    def __init__(self, model_id: str, dim: int, device: str, batch_size: int) -> None:
        self.model_id, self.dim, self._device_pref, self._batch = model_id, dim, device, batch_size
        self._model: Any = None
        self._lock = threading.Lock()
        # One encode at a time per process: bounds memory on small machines.
        self._sem = asyncio.Semaphore(1)

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                import torch
                from sentence_transformers import SentenceTransformer

                device = pick_device(self._device_pref)
                kwargs = {"torch_dtype": torch.float16} if device in ("cuda", "mps") else {}
                self._model = SentenceTransformer(self.model_id, device=device, model_kwargs=kwargs)
                got = self._model.get_sentence_embedding_dimension()
                if got != self.dim:
                    raise RuntimeError(f"EMBED_DIM={self.dim} but {self.model_id} outputs {got}")
                log.info("embedder_loaded", extra={"model": self.model_id, "device": device})
            return self._model

    def _encode(self, texts: list[str], prompt: str | None) -> list[list[float]]:
        vecs = self._load().encode(
            texts, prompt=prompt, batch_size=self._batch, normalize_embeddings=True, convert_to_numpy=True
        )
        return [[float(x) for x in v] for v in vecs]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        async with self._sem:
            return await asyncio.to_thread(self._encode, texts, None)

    async def embed_query(self, text: str) -> list[float]:
        async with self._sem:
            return (await asyncio.to_thread(self._encode, [text], self.QUERY_PROMPT))[0]


class HashEmbedder:
    """Deterministic bag-of-words hashing. Test/offline only: no semantic quality."""

    model_id = "hash"

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for w in text.lower().split():
            v[int(hashlib.md5(w.encode(), usedforsecurity=False).hexdigest(), 16) % self.dim] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    if s.embed_provider == "fake":
        return HashEmbedder(s.embed_dim)
    return LocalEmbedder(s.embed_model, s.embed_dim, s.embed_device, s.embed_batch_size)
