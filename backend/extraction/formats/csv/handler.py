from pathlib import Path
from typing import Any

from backend.document_ir.models import ExtractLimits, ExtractResult
from backend.extraction.formats.csv.extractor import extract_csv
from backend.extraction.formats.text.decode import looks_like_text


class CsvHandler:
    name: str = "csv"
    label: str = "CSV"
    extensions: tuple[str, ...] = (".csv", ".tsv")
    media_type: str = "text/csv"

    def sniff(self, head: bytes) -> bool:
        # CSV has no magic bytes: it must look like text. The parse test happens in extract().
        return looks_like_text(head[:4096])

    def extract(self, path: Path, limits: ExtractLimits) -> ExtractResult:
        return extract_csv(path, limits)

    def extent(self, page_count: int | None, meta: dict[str, Any]) -> str | None:
        rows, cols = meta.get("data_rows"), meta.get("column_count")
        if rows is None or cols is None:
            return None
        return f"{rows:,} row{'' if rows == 1 else 's'}, {cols:,} column{'' if cols == 1 else 's'}"
