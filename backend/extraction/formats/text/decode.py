"""Bytes -> text for TXT/MD. The viewer (viewers/text/text.ts) mirrors this exactly, so offsets agree.

Order: BOM (UTF-8, UTF-16 LE/BE) -> strict UTF-8 -> strict Windows-1252 -> reject.
Python's strict cp1252 rejects the 5 bytes WHATWG maps to C1 controls, so every accepted file
decodes to the same string in the browser's TextDecoder. Newlines are normalised to "\\n".
"""

import codecs

from backend.core.errors import InvalidFile

_UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)
_BOMS = (
    (codecs.BOM_UTF8, "utf-8", "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le", "utf-16le"),
    (codecs.BOM_UTF16_BE, "utf-16-be", "utf-16be"),
)
_ALLOWED_CONTROLS = frozenset("\t\n\r\f")
MAX_CONTROL_RATIO = 0.01


def _control_ratio(text: str) -> float:
    if not text:
        return 0.0
    bad = sum(1 for c in text if (c < " " and c not in _ALLOWED_CONTROLS) or c == "\x7f")
    return bad / len(text)


def looks_like_text(head: bytes) -> bool:
    """Magic-byte check for formats that have no magic bytes: decodable, no NUL, almost no control chars."""
    if head.startswith(_UTF16_BOMS):
        return True
    if b"\x00" in head:
        return False
    try:
        text = codecs.getincrementaldecoder("utf-8")().decode(head, final=False)  # head may end mid-character
    except UnicodeDecodeError:
        try:
            text = head.decode("cp1252")
        except UnicodeDecodeError:
            return False
    return _control_ratio(text) <= MAX_CONTROL_RATIO


def decode_text(data: bytes) -> tuple[str, str]:
    """Return (text, encoding label as the browser's TextDecoder names it)."""
    for bom, codec, label in _BOMS:
        if data.startswith(bom):
            try:
                text = data[len(bom) :].decode(codec)
            except UnicodeDecodeError:
                raise InvalidFile("malformed_text", f"This file says it is {label.upper()} but isn't valid.") from None
            break
    else:
        text, label = _decode_unmarked(data)
    if "\x00" in text or _control_ratio(text) > MAX_CONTROL_RATIO:
        raise InvalidFile("not_text", "This file contains binary data, not text.")
    return text.replace("\r\n", "\n").replace("\r", "\n"), label


def _decode_unmarked(data: bytes) -> tuple[str, str]:
    if b"\x00" in data:
        raise InvalidFile("not_text", "This file contains binary data, not text.")
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252"), "windows-1252"
    except UnicodeDecodeError:
        raise InvalidFile(
            "unsupported_encoding", "This file's text encoding isn't supported. Save it as UTF-8 and retry."
        ) from None
