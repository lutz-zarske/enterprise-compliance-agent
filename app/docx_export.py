"""Verfahrensdokumentation als Word-Datei (.docx) zum Ergänzen und Fortschreiben.

Die Verfahrensdokumentation ist ein lebendes Dokument des Unternehmens: Platzhalter
(„[vom Unternehmen zu ergänzen]“) werden in Word ausgefüllt, Änderungen versioniert.
Erzeugt wird ein schlankes Office-Open-XML-Paket ohne Zusatzabhängigkeit; Platzhalter
sind gelb hervorgehoben, die Fußzeile trägt „Seite x von y“.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any
from xml.sax.saxutils import escape

from app.config import APP_TITLE

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_TEXT_WIDTH = 9752  # A4 (11906 twips) minus 2 x 1077 twips Rand

_LABELS = {
    "de": {"page": "Seite", "of": "von", "lang": "de-DE"},
    "en": {"page": "Page", "of": "of", "lang": "en-GB"},
    "es": {"page": "Página", "of": "de", "lang": "es-ES"},
}


def _x(value: Any) -> str:
    return escape(_INVALID_XML.sub("", "–" if value in (None, "") else str(value)))


def _run(text: str, *, bold: bool = False, highlight: bool = False, mono: bool = False,
         size: int | None = None, color: str | None = None, italic: bool = False) -> str:
    props = ""
    if mono:
        props += '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/>'
    if bold:
        props += "<w:b/>"
    if italic:
        props += "<w:i/>"
    if color:
        props += f'<w:color w:val="{color}"/>'
    if size:
        props += f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
    if highlight:
        props += '<w:highlight w:val="yellow"/>'
    rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{_x(text)}</w:t></w:r>'


def _runs(text: str, todo: str, **style: Any) -> str:
    """Text als Läufe; der Platzhalter wird gelb hervorgehoben (in Word überschreiben)."""
    pieces = str(text).split(todo) if todo else [str(text)]
    out = []
    for index, piece in enumerate(pieces):
        if piece:
            out.append(_run(piece, **style))
        if index < len(pieces) - 1:
            out.append(_run(todo, highlight=True, **style))
    return "".join(out) or _run("", **style)


def _p(content: str, *, style: str | None = None, keep_next: bool = False, page_break: bool = False,
       bullet: bool = False, extra: str = "") -> str:
    ppr = ""
    if style:
        ppr += f'<w:pStyle w:val="{style}"/>'
    if keep_next:
        ppr += "<w:keepNext/>"
    if page_break:
        ppr += "<w:pageBreakBefore/>"
    if bullet:
        ppr += '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
    ppr += extra
    return f"<w:p>{f'<w:pPr>{ppr}</w:pPr>' if ppr else ''}{content}</w:p>"


def _table(head: list[str], rows: list[list[Any]], todo: str, *, widths: list[int] | None = None) -> str:
    columns = len(head) if head else max((len(row) for row in rows), default=1)
    widths = widths or [_TEXT_WIDTH // columns] * columns
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)

    def cell(content: str, width: int, *, header: bool = False) -> str:
        shade = '<w:shd w:val="clear" w:color="auto" w:fill="F1F5F9"/>' if header else ""
        return f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shade}</w:tcPr>{content}</w:tc>'

    parts = []
    if head:
        cells = "".join(
            cell(_p(_run(label, bold=True, size=16, color="475569"), keep_next=True), widths[i], header=True)
            for i, label in enumerate(head)
        )
        parts.append(f"<w:tr><w:trPr><w:cantSplit/><w:tblHeader/></w:trPr>{cells}</w:tr>")
    for row in rows:
        cells = "".join(
            cell(_p(_runs(str(value), todo, size=18)), widths[i]) for i, value in enumerate(list(row)[:columns])
        )
        parts.append(f"<w:tr><w:trPr><w:cantSplit/></w:trPr>{cells}</w:tr>")
    return (
        '<w:tbl><w:tblPr><w:tblStyle w:val="EcaTabelle"/><w:tblW w:w="5000" w:type="pct"/>'
        '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" w:noHBand="1" w:noVBand="1"/>'
        f"</w:tblPr><w:tblGrid>{grid}</w:tblGrid>{''.join(parts)}</w:tbl>"
        + _p("", extra='<w:spacing w:after="60"/>')
    )


def _body(doc: dict[str, Any], ui: dict[str, str], todo: str) -> str:
    out = [
        _p(_run("GoBD Rz. 151 ff. · § 147 AO · VO (EU) 2024/1689"), style="Kicker"),
        _p(_run(doc["title"]), style="Title"),
        _p(_run(doc["subtitle"], italic=True, color="475569")),
        _p(_run(f"{ui['stand']} {_date(doc['generated_at'], str(doc.get('lang') or 'de'))} · {APP_TITLE} v{doc['version']} · "
                f"{ui['ruleset']} {doc['ruleset_version']}", size=17, color="64748B")),
        _p(_run(doc["status"], bold=True) + "<w:r><w:br/></w:r>" + _run(doc["retention"]), style="Hinweis"),
        _p(_run(doc["basis"]), style="Klein"),
    ]
    for section in doc["sections"]:
        out.append(_p(_run(f"{section['number']}  {section['title']}"), style="Heading1"))
        for block in section["blocks"]:
            out.append(_p(_run(block["heading"]), style="Heading2"))
            if "table" in block:
                out.append(_table(block["table"]["head"], block["table"]["rows"], todo))
            for item in block.get("list", []):
                out.append(_p(_runs(item, todo), bullet=True))
            if "text" in block:
                out.append(_p(_runs(block["text"], todo)))
    annex = doc.get("annex")
    if annex:
        out.append(_p(_run(annex["title"]), style="Heading1", page_break=True))
        out.append(_table([ui["col_key"], ui["col_val"]], annex["rows"], todo, widths=[2800, _TEXT_WIDTH - 2800]))
        ledger_rows = [
            [e["seq"], e["event"], e["timestamp"], e["actor"], e["score"], f"{e['entry_hash'][:16]}…",
             "Ed25519" if e["signed"] else "–"]
            for e in annex["ledger"]
        ] or [[ui["no_ledger"], "", "", "", "", "", ""]]
        out.append(_table(
            ["Seq", ui["col_event"], ui["col_time"], ui["col_actor"], "Score", ui["col_hash"], ui["col_sig"]],
            ledger_rows, todo, widths=[600, 2000, 1700, 1700, 800, 1852, 1100],
        ))
    out.append(_p(_run(ui["footer"]), style="Klein"))
    return "".join(out)


def _styles(lang_tag: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{_W}">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/><w:color w:val="0F172A"/><w:sz w:val="20"/><w:szCs w:val="20"/><w:lang w:val="{lang_tag}"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="100" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:before="60" w:after="80"/></w:pPr><w:rPr><w:b/><w:sz w:val="40"/><w:szCs w:val="40"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:pBdr><w:bottom w:val="single" w:sz="4" w:space="4" w:color="E2E8F0"/></w:pBdr><w:spacing w:before="360" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="220" w:after="60"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="Kicker"><w:name w:val="ECA Kicker"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:caps/><w:color w:val="64748B"/><w:spacing w:val="20"/><w:sz w:val="15"/><w:szCs w:val="15"/></w:rPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="Klein"><w:name w:val="ECA Klein"/><w:basedOn w:val="Normal"/><w:rPr><w:color w:val="475569"/><w:sz w:val="17"/><w:szCs w:val="17"/></w:rPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="Hinweis"><w:name w:val="ECA Hinweis"/><w:basedOn w:val="Normal"/><w:pPr><w:pBdr><w:top w:val="dashed" w:sz="4" w:space="6" w:color="94A3B8"/><w:left w:val="dashed" w:sz="4" w:space="6" w:color="94A3B8"/><w:bottom w:val="dashed" w:sz="4" w:space="6" w:color="94A3B8"/><w:right w:val="dashed" w:sz="4" w:space="6" w:color="94A3B8"/></w:pBdr><w:spacing w:before="200" w:after="200"/><w:ind w:left="120" w:right="120"/></w:pPr><w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
<w:style w:type="table" w:customStyle="1" w:styleId="EcaTabelle"><w:name w:val="ECA Tabelle"/><w:tblPr><w:tblBorders><w:bottom w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/><w:insideH w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/></w:tblBorders><w:tblCellMar><w:top w:w="50" w:type="dxa"/><w:left w:w="90" w:type="dxa"/><w:bottom w:w="50" w:type="dxa"/><w:right w:w="90" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
</w:styles>"""


_NUMBERING = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="{_W}"><w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="360" w:hanging="240"/></w:pPr></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>"""


def _footer(left: str, page: str, of: str) -> str:
    small = '<w:rPr><w:color w:val="64748B"/><w:sz w:val="15"/><w:szCs w:val="15"/></w:rPr>'

    def text(value: str) -> str:
        return f'<w:r>{small}<w:t xml:space="preserve">{_x(value)}</w:t></w:r>'

    def field(code: str) -> str:
        return f'<w:fldSimple w:instr=" {code} \\* MERGEFORMAT "><w:r>{small}<w:t>1</w:t></w:r></w:fldSimple>'

    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:ftr xmlns:w="{_W}"><w:p><w:pPr>'
        f'<w:tabs><w:tab w:val="right" w:pos="{_TEXT_WIDTH}"/></w:tabs></w:pPr>{text(left)}'
        f'<w:r>{small}<w:tab/></w:r>{text(page + " ")}{field("PAGE")}{text(" " + of + " ")}{field("NUMPAGES")}</w:p></w:ftr>'
    )


def _date(value: Any, lang: str) -> str:
    """ISO-Zeitstempel als Datum der Sprache (17.11.2026 bzw. 2026-11-17)."""
    iso = str(value or "")[:10]
    if lang == "en" or len(iso) != 10:
        return iso
    return f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}"


def render_docx(doc: dict[str, Any], ui: dict[str, str]) -> bytes:
    """Verfahrensdokumentation als .docx (Word, LibreOffice); ``ui`` sind die Texte der Sprache."""
    lang = str(doc.get("lang") or "de")
    labels = _LABELS.get(lang, _LABELS["de"])
    todo = str(doc.get("todo") or ui.get("todo") or "")
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document xmlns:w="{_W}" xmlns:r="{_R}"><w:body>'
        f"{_body(doc, ui, todo)}"
        '<w:sectPr><w:footerReference w:type="default" r:id="rId3"/><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1247" w:right="1077" w:bottom="1247" w:left="1077" w:header="567" w:footer="567" w:gutter="0"/>'
        "</w:sectPr></w:body></w:document>"
    )
    created = str(doc.get("generated_at") or "")[:19] + "Z"
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
            '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            "</Relationships>"
        ),
        "word/_rels/document.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
            "</Relationships>"
        ),
        "word/document.xml": document,
        "word/styles.xml": _styles(labels["lang"]),
        "word/numbering.xml": _NUMBERING,
        "word/footer1.xml": _footer(f"{doc['title']} · {ui['stand']} {_date(doc['generated_at'], lang)}", labels["page"], labels["of"]),
        "docProps/core.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f"<dc:title>{_x(doc['title'])}</dc:title><dc:creator>{_x(APP_TITLE)}</dc:creator>"
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{_x(created)}</dcterms:created>'
            "</cp:coreProperties>"
        ),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content.encode("utf-8"))
    return buffer.getvalue()
