"""Shared by format extractors: cut long text into blocks at natural boundaries."""

MAX_BLOCK_CHARS = 2000  # longer blocks are split, preferring line then sentence then word boundaries


def cut(text: str, start: int, end: int, limit: int = MAX_BLOCK_CHARS) -> list[tuple[int, int]]:
    """Split [start, end) into pieces of at most `limit` chars at the best natural boundary."""
    pieces: list[tuple[int, int]] = []
    while end - start > limit:
        window = text[start : start + limit]
        floor = limit // 2
        cut = window.rfind("\n", floor)
        if cut < 0:
            cut = max(window.rfind(". ", floor), window.rfind("? ", floor), window.rfind("! ", floor))
            cut = cut + 1 if cut >= 0 else window.rfind(" ", floor)
        cut = start + (cut + 1 if cut > 0 else limit)
        pieces.append((start, cut))
        start = cut
    pieces.append((start, end))
    return pieces
