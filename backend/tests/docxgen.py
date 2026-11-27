"""Minimal, deterministic DOCX writer for tests and the synthetic eval document.

The sample includes what Word itself writes and a reader trips on: words split across runs, proof-error and
bookmark markers, complex fields (TOC/PAGE), tracked insertions and deletions, content controls, hyperlinks,
tabs and line breaks, merged cells and a nested table. Text is written by us (fictional company).

Usage (writes the eval document + the viewer parity fixture):
  uv run python -m backend.tests.docxgen
"""

import io
import json
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
_DATE = (2026, 1, 1, 0, 0, 0)


def t(s: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{escape(s)}</w:t></w:r>'


def p(*runs: str, style: str | None = None, num: bool = False, outline: int | None = None) -> str:
    props = ""
    if style:
        props += f'<w:pStyle w:val="{style}"/>'
    if num:
        props += '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
    if outline is not None:
        props += f'<w:outlineLvl w:val="{outline}"/>'
    body = "".join(r if r.startswith("<") else t(r) for r in runs)
    return f"<w:p>{f'<w:pPr>{props}</w:pPr>' if props else ''}{body}</w:p>"


def cell(*paras: str, merge: str | None = None) -> str:
    pr = f'<w:tcPr><w:vMerge w:val="{merge}"/></w:tcPr>' if merge == "restart" else ""
    pr = "<w:tcPr><w:vMerge/></w:tcPr>" if merge == "continue" else pr
    return f"<w:tc>{pr}{''.join(paras) or '<w:p/>'}</w:tc>"


def table(*rows: list[str]) -> str:
    return (
        '<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="0" w:type="auto"/></w:tblPr>'
        + "".join(f"<w:tr>{''.join(r)}</w:tr>" for r in rows)
        + "</w:tbl>"
    )


STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W}">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Georgia" w:hAnsi="Georgia"/><w:sz w:val="22"/></w:rPr>
  </w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="276" w:lineRule="auto"/></w:pPr>
  </w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>
  <w:rPr><w:sz w:val="48"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/>
  <w:rPr><w:color w:val="595959"/><w:sz w:val="26"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
  <w:pPr><w:spacing w:before="360" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr>
  <w:rPr><w:b/><w:sz w:val="30"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>
  <w:pPr><w:spacing w:before="240" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr>
  <w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Clause"><w:name w:val="Clause Heading"/><w:basedOn w:val="Heading2"/></w:style>
<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/>
  <w:pPr><w:ind w:left="720"/></w:pPr><w:rPr><w:i/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/>
  <w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="720"/></w:pPr></w:style>
<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders>
  <w:top w:val="single" w:sz="4" w:color="808080"/><w:left w:val="single" w:sz="4" w:color="808080"/>
  <w:bottom w:val="single" w:sz="4" w:color="808080"/><w:right w:val="single" w:sz="4" w:color="808080"/>
  <w:insideH w:val="single" w:sz="4" w:color="808080"/><w:insideV w:val="single" w:sz="4" w:color="808080"/>
  </w:tblBorders><w:tblCellMar><w:left w:w="108" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar>
  </w:tblPr></w:style>
</w:styles>"""

NUMBERING = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="{W}"><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/>
<w:numFmt w:val="bullet"/><w:lvlText w:val="\u2022"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/>
</w:pPr></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>"""


def make_docx(
    body: str, *, styles: str | None = STYLES, main_type: str = MAIN, links: dict[str, str] | None = None
) -> bytes:
    links = links or {}
    doc = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document xmlns:w="{W}" xmlns:r="{R}">'
        f'<w:body>{body}<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>'
    )
    doc_rels = "".join(
        f'<Relationship Id="{rid}" Type="{R}/hyperlink" Target="{escape(url)}" TargetMode="External"/>'
        for rid, url in links.items()
    )
    if styles:
        doc_rels += f'<Relationship Id="rIdStyles" Type="{R}/styles" Target="styles.xml"/>'
        doc_rels += f'<Relationship Id="rIdNum" Type="{R}/numbering" Target="numbering.xml"/>'
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/word/document.xml" ContentType="{main_type}"/></Types>'
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
            f'2006/relationships"><Relationship Id="rId1" Type="{R}/officeDocument" Target="word/document.xml"/>'
            "</Relationships>"
        ),
        "word/_rels/document.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
            f'2006/relationships">{doc_rels}</Relationships>'
        ),
        "word/document.xml": doc,
    }
    if styles:
        parts["word/styles.xml"] = styles
        parts["word/numbering.xml"] = NUMBERING
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(zipfile.ZipInfo(name, _DATE), data)
    return buf.getvalue()


# Word-isms, spelled out once.
FIELD_PAGE = (
    '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' + t("3") + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
)
PROOF = '<w:proofErr w:type="spellStart"/>'
BOOKMARK = '<w:bookmarkStart w:id="0" w:name="_Toc1"/>'
TAB = "<w:r><w:tab/></w:r>"
BR = "<w:r><w:br/></w:r>"
PAGE_BREAK = '<w:r><w:br w:type="page"/></w:r>'


def deleted(s: str) -> str:
    return f'<w:del w:id="1" w:author="A"><w:r><w:delText>{escape(s)}</w:delText></w:r></w:del>'


def inserted(s: str) -> str:
    return f'<w:ins w:id="2" w:author="A">{t(s)}</w:ins>'


def link(rid: str, s: str) -> str:
    return f'<w:hyperlink r:id="{rid}">{t(s)}</w:hyperlink>'


def sdt(inner: str) -> str:
    return f"<w:sdt><w:sdtPr/><w:sdtContent>{inner}</w:sdtContent></w:sdt>"


def sample_agreement() -> bytes:
    """A fictional services agreement: the synthetic DOCX eval document and the viewer parity fixture."""
    body = "".join(
        [
            p("Master Services Agreement", style="Title"),
            p(BOOKMARK, "Harbor Lane Logistics and Q", "uill", " Data Systems", style="Subtitle"),
            p(),
            p("1. Scope", style="Heading1"),
            p(
                "Quill Data Systems will operate the shipment tracking platform for Harbor Lane Logistics, ",
                "including hosting, monitoring and ",
                PROOF,
                "on-call support.",
            ),
            p("The platform covers the following services:"),
            p("Real-time parcel tracking for up to 40,000 shipments a day.", style="ListParagraph", num=True),
            p("Monthly capacity reports delivered by the fifth business day.", style="ListParagraph", num=True),
            p("A customer portal available in English and Spanish.", style="ListParagraph", num=True),
            p("2. Service levels", style="Heading1"),
            p("2.1 Availability", style="Clause"),
            p(
                "The platform must be available 99.9% of each calendar month, ",
                deleted("excluding weekends, "),
                "measured at the public status page.",
            ),
            p("Planned maintenance windows:", TAB, "Sundays 02:00–04:00 UTC", BR, "announced 7 days ahead."),
            p("2.2 Response times", style="Clause"),
            table(
                [cell(p("Severity")), cell(p("First response")), cell(p("Resolution target"))],
                [cell(p("Critical")), cell(p("15 minutes")), cell(p("4 hours"))],
                [cell(p("High")), cell(p("1 hour")), cell(p("1 business day"))],
                [cell(p("Low")), cell(p("1 business day"), p("by email only")), cell(p("Next release"))],
            ),
            p("3. Fees", style="Heading1"),
            p(
                "Harbor Lane Logistics will pay a fixed monthly fee of EUR 18,500, invoiced on the first day of ",
                "each month and due within 30 days.",
            ),
            sdt(p("Service credits: 5% of the monthly fee for each full 0.1% below the availability target, ")),
            p("capped at 25% of that month's fee.", inserted(" Credits are the sole remedy for downtime.")),
            p("Rate card for additional work (page ", FIELD_PAGE, "):", PAGE_BREAK),
            table(
                [cell(p("Role")), cell(p("Day rate"))],
                [cell(p("Platform engineer"), merge="restart"), cell(p("EUR 950"))],
                [cell(merge="continue"), cell(p("EUR 1,150 on weekends"))],
                [cell(p("Data analyst")), cell(table([cell(p("EUR 780")), cell(p("remote"))]))],
            ),
            p("4. Term and termination", style="Heading1"),
            p("This agreement starts on 1 March 2027 and runs for an initial term of 36 months."),
            p(
                "Either party may end the agreement with 90 days' written notice after the first 12 months. ",
                "Notices go to ",
                link("rIdMail", "legal@harborlane.example"),
                ".",
            ),
            p("Termination does not affect fees already due.", style="Quote"),
            p("5. Data protection", style="Heading1"),
            p(
                "Shipment data is stored in the EU (Frankfurt region) and deleted within 60 days after the ",
                "agreement ends, unless the law requires longer retention.",
            ),
            p("Signed for Harbor Lane Logistics:", TAB, "Mara Ellison, Chief Operating Officer"),
        ]
    )
    return make_docx(body, links={"rIdMail": "mailto:legal@harborlane.example"})


def main() -> None:
    from backend.document_ir.models import ExtractLimits
    from backend.extraction.formats.docx.extractor import extract_docx

    root = Path(__file__).resolve().parents[2]
    data = sample_agreement()
    targets = [
        root / "eval/data/public/harbor-lane-msa.docx",
        root / "frontend/web/src/viewers/docx/fixtures/sample.docx",
    ]
    for path in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    # Viewer parity: every rendered paragraph's text, in order, as the backend counts them.
    paras = _paragraph_texts(data)
    (root / "frontend/web/src/viewers/docx/fixtures/sample.paragraphs.json").write_text(
        json.dumps(paras, indent=1) + "\n"
    )
    r = extract_docx(targets[0], ExtractLimits(max_pages=500, max_chars=2_000_000))
    print(f"{len(r.blocks)} blocks, {len(paras)} paragraphs", file=sys.stderr)


def _paragraph_texts(data: bytes) -> list[str]:
    from xml.etree import ElementTree as ET

    from backend.extraction.formats.docx.extractor import _child, _Walker

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        doc = ET.fromstring(z.read("word/document.xml"))  # noqa: S314 - our own test file
    w = _Walker({})
    body = _child(doc, "body")
    assert body is not None
    w.body(body)
    return [para.text for para in w.paras]


if __name__ == "__main__":
    main()
