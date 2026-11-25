"""Text normalisation for quote matching, keeping a map from normalised index -> raw index."""

import re
import unicodedata

_LETTER_HYPHEN = re.compile(r"(?<=[^\W\d_])- ?(?=[^\W\d_])")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def normalize(text: str) -> tuple[str, list[int]]:
    """NFKC + casefold + unify quotes/dashes + join line-end hyphens + collapse whitespace.

    Returns (normalised, index_map) where index_map[i] is the raw index of normalised char i.
    """
    out: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKC", ch).translate(_QUOTES).casefold():
            if c.isspace():
                if out and out[-1] != " ":
                    out.append(" ")
                    idx.append(i)
                continue
            out.append(c)
            idx.append(i)
    # Hyphens between letters are dropped (with the line-break space the extractor keeps), so
    # "trans- former" == "transformer" and "left-to- right" == "left-to-right". Minus signs on numbers stay.
    s = "".join(out)
    keep = [True] * len(s)
    for m in _LETTER_HYPHEN.finditer(s):
        keep[m.start() : m.end()] = [False] * (m.end() - m.start())
    norm = "".join(c for c, k in zip(s, keep, strict=True) if k).strip()
    kept = [j for j, k in zip(idx, keep, strict=True) if k]
    lead = len(s) - len(s.lstrip())
    return norm, kept[lead : lead + len(norm)]
