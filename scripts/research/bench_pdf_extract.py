"""Bench PDF word extraction: speed, peak RSS, word count, bbox agreement."""
import resource
import sys
import time


def plumber(path):
    import pdfplumber
    out = []
    with pdfplumber.open(path) as pdf:
        for i, p in enumerate(pdf.pages):
            for w in p.extract_words(keep_blank_chars=False, use_text_flow=True):
                out.append((i, w["text"], w["x0"], w["top"], w["x1"], w["bottom"]))
            p.flush_cache()
    return out


def pdfium(path):
    import pypdfium2 as pdfium
    out = []
    doc = pdfium.PdfDocument(path)
    for i in range(len(doc)):
        page = doc[i]
        h = page.get_height()
        tp = page.get_textpage()
        n = tp.count_chars()
        cur, box = [], None
        for c in range(n):
            ch = tp.get_text_range(c, 1)
            if ch.strip() == "":
                if cur:
                    out.append((i, "".join(cur), *box))
                cur, box = [], None
                continue
            l, b, r, t = tp.get_charbox(c, loose=False)
            bb = (l, h - t, r, h - b)
            box = bb if box is None else (min(box[0], bb[0]), min(box[1], bb[1]), max(box[2], bb[2]), max(box[3], bb[3]))
            cur.append(ch)
        if cur:
            out.append((i, "".join(cur), *box))
        tp.close()
        page.close()
    doc.close()
    return out


def mupdf(path):
    import pymupdf
    out = []
    with pymupdf.open(path) as doc:
        for i, p in enumerate(doc):
            for w in p.get_text("words", sort=True):
                out.append((i, w[4], w[0], w[1], w[2], w[3]))
    return out


if __name__ == "__main__":
    name, path = sys.argv[1], sys.argv[2]
    fn = {"plumber": plumber, "pdfium": pdfium, "mupdf": mupdf}[name]
    t = time.perf_counter()
    words = fn(path)
    dt = time.perf_counter() - t
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
    print(f"{name:8s} {path.split('/')[-1]:14s} words={len(words):6d} time={dt*1000:7.0f}ms rss={rss:5.0f}MB sample={[w[1] for w in words[100:106]]}")
