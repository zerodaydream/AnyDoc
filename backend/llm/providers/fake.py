"""Deterministic offline provider for tests and no-key local runs. Quotes the best-overlapping block."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from backend.llm.base import Delta

_BLOCK = re.compile(r'<document_block id="([^"]+)"[^>]*>\n?(.*?)\n?</document_block>', re.S)
_QUESTION = re.compile(r"<question>\n?(.*?)\n?</question>", re.S)
_WORD = re.compile(r"[^\W_]{3,}")


class FakeProvider:
    model_id = "fake"

    async def stream_json(
        self,
        system: str,
        prompt: str,
        schema: type[BaseModel],
        usage: dict[str, Any],
        *,
        model: str | None = None,
        thinking: str | None = None,
    ) -> AsyncIterator[Delta]:
        if thinking:
            for piece in ("Looking for the passage ", "that answers the question."):
                yield ("thought", piece)
        q = _QUESTION.search(prompt)
        qwords = set(_WORD.findall((q.group(1) if q else "").lower()))
        best, best_score = None, 0
        for bid, content in _BLOCK.findall(prompt):
            score = len(qwords & set(_WORD.findall(content.lower())))
            if score > best_score:
                best, best_score = (bid, content), score
        out: dict[str, Any]
        if best is None:
            out = {"status": "insufficient_evidence", "segments": []}
        else:
            quote = " ".join(best[1].split()[:12])
            out = {
                "status": "answered",
                "segments": [
                    {
                        "text": f"The document says: {quote}",
                        "evidence": [{"block_id": best[0], "quote": quote}],
                    }
                ],
                "suggestion": "You could ask what else this part of the document covers.",
            }
        raw = json.dumps(out)
        for i in range(0, len(raw), 24):
            yield ("text", raw[i : i + 24])
        usage.update(model=model or self.model_id, input_tokens=len(prompt) // 4, output_tokens=len(raw) // 4)

    async def describe_models(self, model_ids: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "id": m,
                "name": m,
                "input_token_limit": 1_048_576,
                "output_token_limit": 65_536,
                "thinking": True,
                "available": True,
            }
            for m in model_ids
        ]

    async def check(self) -> dict[str, Any]:
        return {"fake": True}
