"""Eigenständige A4-PDF-Erzeugung für Prüfzertifikat und Verfahrensdokumentation.

Verwendet ReportLab (BSD-Lizenz, Standard-PDF-Schriften ohne OS-Abhängigkeiten)
mit festem A4-Layout, laufender Kopf-/Fußzeile („Seite x von y“), wiederholten
Tabellenköpfen über Seitenumbrüche und zusammengehaltenen Überschriften/Blöcken.
"""

from __future__ import annotations

import html
import io
import re
import unicodedata
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Flowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import APP_TITLE
from app.procedural_doc import procedural_layout_text, procedural_ui
from app.reporting import report_layout_data

_PAGE_W, _PAGE_H = A4
_MARGIN_L = 15 * mm
_MARGIN_R = 15 * mm
_MARGIN_T = 20 * mm
_MARGIN_B = 18 * mm
_CONTENT_W = _PAGE_W - _MARGIN_L - _MARGIN_R  # 180 mm (~510.2 pt)

_C_INK = colors.HexColor("#0f172a")
_C_MUTED = colors.HexColor("#475569")
_C_SUBTLE = colors.HexColor("#64748b")
_C_LINE = colors.HexColor("#e2e8f0")
_C_HAIR = colors.HexColor("#eef2f6")
_C_DASH = colors.HexColor("#94a3b8")

_TONE_PALETTE = {
    "pass": (colors.HexColor("#047857"), colors.HexColor("#34d399"), colors.HexColor("#f0fdf4"), "#ecfdf5", "#047857"),
    "green": (colors.HexColor("#047857"), colors.HexColor("#34d399"), colors.HexColor("#f0fdf4"), "#ecfdf5", "#047857"),
    "warn": (colors.HexColor("#b45309"), colors.HexColor("#fbbf24"), colors.HexColor("#fffbeb"), "#fffbeb", "#b45309"),
    "amber": (colors.HexColor("#b45309"), colors.HexColor("#fbbf24"), colors.HexColor("#fffbeb"), "#fffbeb", "#b45309"),
    "fail": (colors.HexColor("#be123c"), colors.HexColor("#fb7185"), colors.HexColor("#fff1f2"), "#fff1f2", "#be123c"),
    "red": (colors.HexColor("#be123c"), colors.HexColor("#fb7185"), colors.HexColor("#fff1f2"), "#fff1f2", "#be123c"),
    "neutral": (colors.HexColor("#475569"), colors.HexColor("#cbd5e1"), colors.HexColor("#f8fafc"), "#f1f5f9", "#475569"),
    "not_applicable": (colors.HexColor("#475569"), colors.HexColor("#cbd5e1"), colors.HexColor("#f8fafc"), "#f1f5f9", "#475569"),
}

_CHAR_MAP = str.maketrans({
    "→": "->",
    "←": "<-",
    "↔": "<->",
    "⇒": "=>",
    "≥": ">=",
    "≤": "<=",
    "≠": "!=",
    "−": "-",
    "‐": "-",
    "\u00a0": " ",
    "Ł": "L",
    "ł": "l",
    "Đ": "D",
    "đ": "d",
    "Ø": "O",
    "ø": "o",
    "İ": "I",
    "ı": "i",
})


_CTRL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _w(value: Any, *, empty: str = "–") -> str:
    """Normalisiert beliebigen Unicode-Text verlustarm in WinAnsi (CP1252) für Helvetica/Courier."""
    if value is None or value == "":
        return empty
    text = _CTRL_CHARS.sub("", str(value)).translate(_CHAR_MAP)
    out: list[str] = []
    for ch in text:
        try:
            ch.encode("cp1252")
            out.append(ch)
        except UnicodeEncodeError:
            decomposed = unicodedata.normalize("NFKD", ch)
            ascii_chars = "".join(c for c in decomposed if ord(c) < 128 and not unicodedata.combining(c))
            out.append(ascii_chars or "?")
    return "".join(out)


def _xml(value: Any, *, empty: str = "–", max_len: int | None = 2500) -> str:
    text = _w(value, empty=empty)
    if max_len is not None and len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return html.escape(text)


def _truncate(text: str, limit: int = 72) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Stile & Gemeinsame Flowables
# ---------------------------------------------------------------------------


def _styles() -> dict[str, ParagraphStyle]:
    return {
        "kicker": ParagraphStyle("kicker", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=_C_SUBTLE),
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=_C_INK, spaceBefore=3),
        "subtitle": ParagraphStyle("subtitle", fontName="Helvetica-Oblique", fontSize=9.5, leading=13, textColor=_C_MUTED, spaceBefore=2),
        "lead": ParagraphStyle("lead", fontName="Helvetica", fontSize=8.5, leading=12, textColor=_C_MUTED, spaceBefore=4),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9, leading=13, textColor=_C_INK),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8, leading=11.5, textColor=_C_MUTED),
        "risk": ParagraphStyle("risk", fontName="Helvetica", fontSize=8, leading=11, textColor=colors.HexColor("#9f1239"), spaceBefore=2),
        "mono": ParagraphStyle("mono", fontName="Courier", fontSize=7.8, leading=10.5, textColor=_C_INK),
        "hash": ParagraphStyle("hash", fontName="Courier", fontSize=7.2, leading=10, textColor=_C_INK),
        "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=7.2, leading=9.5, textColor=_C_SUBTLE),
        "th_num": ParagraphStyle("th_num", fontName="Helvetica-Bold", fontSize=7.2, leading=9.5, textColor=_C_SUBTLE, alignment=2),
        "td": ParagraphStyle("td", fontName="Helvetica", fontSize=8.2, leading=11.2, textColor=_C_INK),
        "td_small": ParagraphStyle("td_small", fontName="Helvetica", fontSize=7.8, leading=10.8, textColor=_C_MUTED),
        "td_num": ParagraphStyle("td_num", fontName="Helvetica", fontSize=8.2, leading=11.2, textColor=_C_INK, alignment=2),
        "td_mono": ParagraphStyle("td_mono", fontName="Courier", fontSize=7.6, leading=10.5, textColor=_C_INK),
        "h2_num": ParagraphStyle("h2_num", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=_C_SUBTLE),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=_C_INK),
        "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=9.5, leading=13, textColor=_C_INK, spaceBefore=8, spaceAfter=2, keepWithNext=True),
        "legal": ParagraphStyle("legal", fontName="Helvetica", fontSize=7.2, leading=10.5, textColor=_C_SUBTLE),
        "callout": ParagraphStyle("callout", fontName="Helvetica", fontSize=8.2, leading=11.5, textColor=colors.HexColor("#334155")),
        "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=8.8, leading=12.5, textColor=_C_INK, leftIndent=12, bulletIndent=4, spaceAfter=2),
    }


class _NumberedCanvas(canvas.Canvas):
    """Zwei-Durchlauf-Canvas für einheitliche Kopf-/Fußzeile inkl. „Seite x von y“."""

    def __init__(self, *args: Any, top_left: str, top_right: str, bottom_left: str,
                 page_label: str, of_label: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []
        self._top_left = _w(top_left)
        self._top_right = _w(_truncate(top_right, 60))
        self._bottom_left = _w(bottom_left)
        self._page_label = _w(page_label)
        self._of_label = _w(of_label)

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_chrome(total)
            super().showPage()
        super().save()

    def _fit_left_right(self, text: str, font_name: str, font_size: float, max_width: float) -> str:
        text = _w(text)
        if max_width <= 0:
            return ""
        if self.stringWidth(text, font_name, font_size) <= max_width:
            return text
        ellipsis = "…"
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.stringWidth(text[:mid] + ellipsis, font_name, font_size) <= max_width:
                lo = mid
            else:
                hi = mid - 1
        return (text[:lo] + ellipsis) if lo > 0 else ""

    def _draw_chrome(self, total_pages: int) -> None:
        page_num = self._pageNumber
        self.saveState()
        # Kopfzeile – mindestens 8 mm Abstand zwischen linkem Titel und rechtem Dateinamen
        top_y = _PAGE_H - 11.5 * mm
        self.setFillColor(_C_SUBTLE)
        self.setFont("Helvetica-Bold", 7.3)
        self.drawString(_MARGIN_L, top_y, self._top_left)
        left_w = self.stringWidth(self._top_left, "Helvetica-Bold", 7.3)
        right_str = self._fit_left_right(self._top_right, "Helvetica", 7.3, _CONTENT_W - left_w - 8 * mm)
        self.setFont("Helvetica", 7.3)
        if right_str:
            self.drawRightString(_PAGE_W - _MARGIN_R, top_y, right_str)
        self.setStrokeColor(_C_LINE)
        self.setLineWidth(0.6)
        self.line(_MARGIN_L, _PAGE_H - 14.5 * mm, _PAGE_W - _MARGIN_R, _PAGE_H - 14.5 * mm)

        # Fußzeile – Seitenzahl darf linken Metatext nie überschreiben
        bot_rule_y = 13.5 * mm
        self.line(_MARGIN_L, bot_rule_y, _PAGE_W - _MARGIN_R, bot_rule_y)
        bot_y = 9.5 * mm
        self.setFillColor(_C_SUBTLE)
        self.setFont("Helvetica", 7.3)
        page_txt = f"{self._page_label} {page_num} {self._of_label} {total_pages}"
        page_w = self.stringWidth(page_txt, "Helvetica", 7.3)
        bot_left = self._fit_left_right(self._bottom_left, "Helvetica", 7.3, _CONTENT_W - page_w - 8 * mm)
        if bot_left:
            self.drawString(_MARGIN_L, bot_y, bot_left)
        self.drawRightString(_PAGE_W - _MARGIN_R, bot_y, page_txt)
        self.restoreState()


class _DashedBox(Flowable):
    """Abgerundeter Hinweiskasten mit gestricheltem Rahmen (wie HTML .refnote / .note)."""

    def __init__(self, text_html: str, style: ParagraphStyle, width: float = _CONTENT_W) -> None:
        super().__init__()
        self._para = Paragraph(text_html, style)
        self._w = width
        self._pad_x = 9
        self._pad_y = 7
        _, ph = self._para.wrap(width - 2 * self._pad_x, 1000)
        self._h = ph + 2 * self._pad_y

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        return self._w, self._h

    def draw(self) -> None:
        c = self.canv
        c.saveState()
        c.setStrokeColor(_C_DASH)
        c.setLineWidth(0.8)
        c.setDash(3, 2.5)
        c.roundRect(0, 0, self._w, self._h, 6, stroke=1, fill=0)
        c.restoreState()
        self._para.drawOn(c, self._pad_x, self._pad_y)


class _ScoreHero(Flowable):
    """Score-Karte links + Freigabeempfehlung & 4 Domänen-Kacheln rechts (Executive Summary)."""

    def __init__(
        self,
        *,
        score_val: str,
        of_100: str,
        band: str,
        band_label: str,
        rec_label: str,
        rec_text: str,
        blocked: bool,
        tiles: list[tuple[str, str, str]],
        st: dict[str, ParagraphStyle],
        width: float = _CONTENT_W,
    ) -> None:
        super().__init__()
        self._w = width
        self._left_w = 38 * mm
        self._gap = 4.5 * mm
        self._right_w = width - self._left_w - self._gap

        fg, stroke, fill, _, _ = _TONE_PALETTE.get(band, _TONE_PALETTE["red"])
        self._score_colors = (fg, stroke, fill)
        self._score_val = _w(score_val)
        self._of_100 = _w(of_100)
        self._band_para = Paragraph(
            _xml(band_label),
            ParagraphStyle("band", fontName="Helvetica-Bold", fontSize=7.8, leading=10, textColor=fg, alignment=1),
        )
        _, band_h = self._band_para.wrap(self._left_w - 8, 200)

        self._rec_label = _w(rec_label).upper()
        if blocked:
            v_fg, v_stroke, v_fill = colors.HexColor("#9f1239"), colors.HexColor("#fecdd3"), colors.HexColor("#fff1f2")
        elif band == "amber":
            v_fg, v_stroke, v_fill = colors.HexColor("#92400e"), colors.HexColor("#fde68a"), colors.HexColor("#fffbeb")
        else:
            v_fg, v_stroke, v_fill = colors.HexColor("#065f46"), colors.HexColor("#a7f3d0"), colors.HexColor("#ecfdf5")
        self._verdict_colors = (v_stroke, v_fill)
        self._verdict_para = Paragraph(
            _xml(rec_text),
            ParagraphStyle("verdict", fontName="Helvetica-Bold", fontSize=9.8, leading=13, textColor=v_fg),
        )
        _, v_h = self._verdict_para.wrap(self._right_w - 16, 200)
        self._verdict_box_h = max(v_h + 12, 24)

        tile_gap = 2.5 * mm
        self._tile_gap = tile_gap
        self._tile_w = (self._right_w - 3 * tile_gap) / 4
        self._tiles: list[tuple[str, Paragraph, Any]] = []
        max_tile_val_h = 0.0
        for lbl, tone, val in tiles:
            t_fg = _TONE_PALETTE.get(tone, _TONE_PALETTE["neutral"])[0]
            vp = Paragraph(
                _xml(val),
                ParagraphStyle("tv", fontName="Helvetica-Bold", fontSize=8.0, leading=10.5, textColor=t_fg),
            )
            _, th = vp.wrap(self._tile_w - 10, 200)
            max_tile_val_h = max(max_tile_val_h, th)
            self._tiles.append((_w(lbl).upper(), vp, t_fg))
        self._tile_h = max(max_tile_val_h + 22, 32)

        right_total = 11 + self._verdict_box_h + 7 + self._tile_h
        left_min = 42 + band_h + 16
        self._h = max(right_total, left_min, 37 * mm)

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        return self._w, self._h

    def draw(self) -> None:
        c = self.canv
        c.saveState()
        # Score-Box links
        fg, stroke, fill = self._score_colors
        c.setFillColor(fill)
        c.setStrokeColor(stroke)
        c.setLineWidth(1.2)
        c.roundRect(0, 0, self._left_w, self._h, 8, stroke=1, fill=1)

        bw, bh = self._band_para.width, self._band_para.height
        block_h = 26 + 11 + 6 + bh
        base_y = (self._h - block_h) / 2
        self._band_para.drawOn(c, 4, base_y)
        c.setFillColor(fg)
        c.setFont("Helvetica", 8.5)
        c.drawCentredString(self._left_w / 2, base_y + bh + 6, self._of_100)
        c.setFont("Helvetica-Bold", 26)
        c.drawCentredString(self._left_w / 2, base_y + bh + 18, self._score_val)

        # Rechte Seite: Label + Freigabe-Pill
        rx = self._left_w + self._gap
        c.setFillColor(_C_SUBTLE)
        c.setFont("Helvetica-Bold", 6.8)
        c.drawString(rx, self._h - 8, self._rec_label)

        vy = self._h - 11 - self._verdict_box_h
        v_stroke, v_fill = self._verdict_colors
        c.setFillColor(v_fill)
        c.setStrokeColor(v_stroke)
        c.setLineWidth(0.8)
        c.roundRect(rx, vy, self._right_w, self._verdict_box_h, 7, stroke=1, fill=1)
        self._verdict_para.drawOn(c, rx + 8, vy + (self._verdict_box_h - self._verdict_para.height) / 2)

        # 4 Domänen-Kacheln darunter
        for idx, (lbl, vp, _) in enumerate(self._tiles):
            tx = rx + idx * (self._tile_w + self._tile_gap)
            c.setFillColor(colors.white)
            c.setStrokeColor(_C_LINE)
            c.setLineWidth(0.75)
            c.roundRect(tx, 0, self._tile_w, self._tile_h, 6, stroke=1, fill=1)
            c.setFillColor(_C_SUBTLE)
            c.setFont("Helvetica-Bold", 6.3)
            c.drawString(tx + 5.5, self._tile_h - 11, lbl)
            vp.drawOn(c, tx + 5.5, self._tile_h - 15 - vp.height)
        c.restoreState()


class _SealBox(Flowable):
    """Prüfer-Siegel (grün/rot mit Vektor-Emblem) oder gestrichelter Entwurfshinweis."""

    def __init__(self, *, sign: dict[str, Any] | None, t: dict[str, str], fmt_ts: Any,
                 st: dict[str, ParagraphStyle], width: float = _CONTENT_W) -> None:
        super().__init__()
        self._w = width
        self._sign = sign
        if not sign:
            self._draft = Paragraph(_xml(t["draft_banner"]), ParagraphStyle("dr", fontName="Helvetica", fontSize=8.5, leading=12, textColor=_C_MUTED, alignment=1))
            _, dh = self._draft.wrap(width - 20, 200)
            self._h = max(dh + 18, 28)
            return

        self._approved = sign["status"] == "SEALED_APPROVED"
        fg, stroke, fill, _, _ = _TONE_PALETTE["pass" if self._approved else "fail"]
        self._colors = (fg, stroke, fill)
        title = t["seal_approved"] if self._approved else t["seal_rejected"]
        lines = [
            Paragraph(_xml(title), ParagraphStyle("st", fontName="Helvetica-Bold", fontSize=8.8, leading=11.5, textColor=fg)),
            Paragraph(
                f"{_xml(t['auditor_lbl'])}: <b>{_xml(sign['auditor_name'])}</b> · {_xml(t['sealed_lbl'])}: {_xml(fmt_ts(sign['sealed_at']))}",
                ParagraphStyle("sb", fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=_C_INK, spaceBefore=2),
            ),
        ]
        if sign.get("note"):
            lines.append(Paragraph(f"{_xml(t['note'])}: {_xml(sign['note'])}", ParagraphStyle("sn", fontName="Helvetica", fontSize=8, leading=11, textColor=_C_MUTED, spaceBefore=2)))
        lines.append(
            Paragraph(
                f"{_xml(t['seal_hash'])} {_xml(sign['ledger_entry_hash'])} · Ed25519",
                ParagraphStyle("sh", fontName="Courier", fontSize=7.2, leading=9.5, textColor=_C_MUTED, spaceBefore=3),
            )
        )
        text_w = width - 30 * mm
        total_h = 0.0
        for p in lines:
            _, ph = p.wrap(text_w, 300)
            total_h += ph + p.getSpaceBefore()
        self._lines = lines
        self._h = max(total_h + 18, 22 * mm)

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        return self._w, self._h

    def draw(self) -> None:
        c = self.canv
        c.saveState()
        if not self._sign:
            c.setStrokeColor(_C_DASH)
            c.setLineWidth(0.8)
            c.setDash(3, 2.5)
            c.roundRect(0, 0, self._w, self._h, 7, stroke=1, fill=0)
            self._draft.drawOn(c, 10, (self._h - self._draft.height) / 2)
            c.restoreState()
            return

        fg, stroke, fill = self._colors
        c.setFillColor(fill)
        c.setStrokeColor(stroke)
        c.setLineWidth(1.2)
        c.roundRect(0, 0, self._w, self._h, 8, stroke=1, fill=1)

        # Vektor-Siegelkreis links
        cx = 13 * mm
        cy = self._h / 2
        c.setStrokeColor(fg)
        c.setLineWidth(1.4)
        c.circle(cx, cy, 7.5 * mm, stroke=1, fill=0)
        c.saveState()
        c.setLineWidth(0.6)
        c.setDash(2, 2)
        c.circle(cx, cy, 6.1 * mm, stroke=1, fill=0)
        c.restoreState()
        c.setLineWidth(2.0)
        c.setLineCap(1)
        c.setLineJoin(1)
        if self._approved:
            p = c.beginPath()
            p.moveTo(cx - 3.0 * mm, cy - 0.1 * mm)
            p.lineTo(cx - 0.8 * mm, cy - 2.3 * mm)
            p.lineTo(cx + 3.4 * mm, cy + 2.3 * mm)
            c.drawPath(p, stroke=1, fill=0)
        else:
            c.line(cx - 2.4 * mm, cy - 2.4 * mm, cx + 2.4 * mm, cy + 2.4 * mm)
            c.line(cx - 2.4 * mm, cy + 2.4 * mm, cx + 2.4 * mm, cy - 2.4 * mm)

        # Textblöcke rechts vom Siegelkreis
        y = self._h - 9
        tx = 25 * mm
        for para in self._lines:
            y -= para.getSpaceBefore() + para.height
            para.drawOn(c, tx, y)
        c.restoreState()


def _section_heading(number: str | int, title: str, st: dict[str, ParagraphStyle]) -> Table:
    """Nummerierte Abschnittsüberschrift mit unterer Haarlinie (keepWithNext)."""
    tbl = Table(
        [[Paragraph(_xml(str(number)), st["h2_num"]), Paragraph(_xml(title), st["h2"])]],
        colWidths=[8 * mm, _CONTENT_W - 8 * mm],
    )
    tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, _C_LINE),
    ]))
    tbl.keepWithNext = True
    return tbl


def _keep_next_block(flowables: list[Any]) -> Table:
    """Bündelt Einleitungselemente untrennbar und hält sie an der folgenden Tabelle fest."""
    tbl = Table([[item] for item in flowables], colWidths=[_CONTENT_W])
    tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("NOSPLIT", (0, 0), (-1, -1)),
    ]))
    tbl.keepWithNext = True
    return tbl


def _styled_table(
    rows_data: list[list[Any]],
    col_widths: list[float],
    *,
    num_cols: set[int] | None = None,
    status_cells: dict[tuple[int, int], str] | None = None,
    repeat_header: bool = True,
) -> Table:
    num_cols = num_cols or set()
    status_cells = status_cells or {}
    tbl = Table(rows_data, colWidths=col_widths, repeatRows=1 if repeat_header else 0, splitByRow=1, splitInRow=1)
    cmds: list[Any] = [
        ("LEFTPADDING", (0, 0), (-1, -1), 4.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4.5),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, _C_LINE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, _C_HAIR),
    ]
    for col in num_cols:
        cmds.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
    for (row_idx, col_idx), tone in status_cells.items():
        bg = _TONE_PALETTE.get(tone, _TONE_PALETTE["neutral"])[3]
        cmds.append(("BACKGROUND", (col_idx, row_idx), (col_idx, row_idx), colors.HexColor(bg)))
    tbl.setStyle(TableStyle(cmds))
    return tbl


def _status_badge(label: str, tone: str) -> Paragraph:
    _, _, _, bg, fg_hex = _TONE_PALETTE.get(tone, _TONE_PALETTE["neutral"])
    return Paragraph(
        f'<font color="{fg_hex}"><b>{_xml(label)}</b></font>',
        ParagraphStyle("stb", fontName="Helvetica-Bold", fontSize=7.4, leading=10, alignment=1),
    )


def _build_pdf(
    story: list[Any],
    *,
    top_left: str,
    top_right: str,
    bottom_left: str,
    page_label: str,
    of_label: str,
    title: str,
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=_MARGIN_L,
        rightMargin=_MARGIN_R,
        topMargin=_MARGIN_T,
        bottomMargin=_MARGIN_B,
        title=_w(title),
        author=APP_TITLE,
    )
    doc.build(
        story,
        canvasmaker=lambda *a, **kw: _NumberedCanvas(
            *a,
            top_left=top_left,
            top_right=top_right,
            bottom_left=bottom_left,
            page_label=page_label,
            of_label=of_label,
            **kw,
        ),
    )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Prüfzertifikat (PDF)
# ---------------------------------------------------------------------------


def render_report_pdf(report: dict[str, Any], *, lang: str | None = None) -> bytes:
    """Erzeugt das A4-Compliance-Prüfzertifikat direkt als druckfertiges PDF."""
    data = report_layout_data(report, lang)
    t = data["text"]
    lt = data["layout"]
    status_labels = data["status_labels"]
    source_labels = data["source_labels"]
    visual_labels = data["visual_labels"]
    fmt_date = data["fmt_date"]
    fmt_ts = data["fmt_ts"]
    st = _styles()

    score = report["score"] or {}
    doc_info = report["document"]
    sign = report["sign_off"]
    ai = report["ai_act"]
    ai_applicable = bool(ai.get("applicable", ai.get("risk_level") != "not_applicable"))
    audited = report["inference"].get("audited_at") or report["ledger"].get("timestamp_utc")

    story: list[Any] = [
        Paragraph(_xml(t["kicker"]).upper(), st["kicker"]),
        Paragraph(_xml(doc_info["filename"]), st["title"]),
        Paragraph(
            f"Audit-ID <font name='Courier' size='8'>{_xml(report['audit_id'])}</font> · "
            f"{_xml(t['audit_time'])} {_xml(fmt_ts(audited))}",
            st["lead"],
        ),
        Spacer(1, 3.5 * mm),
    ]
    if report["inference"].get("reference_audit"):
        story += [_DashedBox(_xml(data["reference_note"]), st["callout"]), Spacer(1, 3 * mm)]
    if report["inference"].get("structured"):
        story += [_DashedBox(_xml(data["structured_note"]), st["callout"]), Spacer(1, 3 * mm)]
    if report["inference"].get("heuristic"):
        story += [_DashedBox(_xml(data["heuristic_note"]), st["callout"]), Spacer(1, 3 * mm)]

    rec_text = report["release_recommendation"] + (f" · {score['cap_applied']}" if score.get("cap_applied") else "")
    story += [
        _ScoreHero(
            score_val=str(score.get("score", "–")),
            of_100=lt["of_100"],
            band=str(score.get("band", "red")),
            band_label=str(score.get("band_label") or "–"),
            rec_label=t["rec"],
            rec_text=rec_text,
            blocked=bool(report["release_blocked"]),
            tiles=data["tiles"],
            st=st,
        ),
        Spacer(1, 4.5 * mm),
    ]
    if not ai_applicable:
        story += [Paragraph(_xml(t["ai_not_applicable"]), st["small"]), Spacer(1, 3 * mm)]
    story += [
        _SealBox(sign=sign, t=t, fmt_ts=fmt_ts, st=st),
        Spacer(1, 5.5 * mm),
    ]

    chain_heading = Paragraph(_xml(t["chain_section"]), ParagraphStyle("ch", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=_C_INK, keepWithNext=True))
    story += [
        chain_heading,
        Spacer(1, 1.5 * mm),
    ]
    chain_line = Table([[""]], colWidths=[_CONTENT_W], rowHeights=[1])
    chain_line.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.7, _C_LINE), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    chain_line.keepWithNext = True
    story += [chain_line, Spacer(1, 2 * mm)]

    chain_rows: list[list[Any]] = [
        [Paragraph(_xml(t["sha_doc"]), st["td_small"]), Paragraph(_xml(doc_info["sha256"]), st["hash"])],
        [Paragraph(_xml(t["ledger_entry"]), st["td_small"]), Paragraph(_xml(report["ledger"]["entry_hash"]), st["hash"])],
        [Paragraph(_xml(t["prev_hash"]), st["td_small"]), Paragraph(_xml(report["ledger"]["previous_hash"]), st["hash"])],
        [Paragraph(_xml(t["prompt_hash"]), st["td_small"]), Paragraph(_xml(report["ledger"]["prompt_hash"]), st["hash"])],
        [
            Paragraph(_xml(t["hash_chain_lbl"]), st["td_small"]),
            Paragraph(
                f"{_xml(t['intact'] if report['ledger']['chain_valid'] else t['broken'])} "
                f"({_xml(report['ledger']['chain_entries'])} {_xml(t['entries'])})",
                st["td"],
            ),
        ],
        [Paragraph(_xml(t["model_provider"]), st["td_small"]), Paragraph(f"{_xml(report['inference']['model'])} / {_xml(report['inference']['provider'])}", st["td"])],
        [Paragraph(_xml(t["ruleset"]), st["td_small"]), Paragraph(_xml(score.get("ruleset_version")), st["td"])],
    ]
    retention = report.get("retention")
    if retention:
        ret_text = (
            f"{retention['years']} {t['years']}, {t['until_at_least']} {fmt_date(retention['until'])} "
            f"({retention['basis']}); {t['fin_sector']} {fmt_date(retention['financial_sector_until'])}"
        )
        chain_rows.append([Paragraph(_xml(t["retention"]), st["td_small"]), Paragraph(_xml(ret_text), st["td"])])

    chain_tbl = Table(chain_rows, colWidths=[38 * mm, _CONTENT_W - 38 * mm])
    chain_tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(chain_tbl)
    story.append(PageBreak())

    # --- Ab Seite 2: Detailprüfungen ---------------------------------------
    def check_table(checks: list[dict[str, Any]], first_col_header: str) -> Table:
        rows_data: list[list[Any]] = [[
            Paragraph(_xml(first_col_header).upper(), st["th"]),
            Paragraph(_xml(t["col_norm"]).upper(), st["th"]),
            Paragraph(_xml(t["col_status"]).upper(), st["th"]),
            Paragraph(_xml(t["col_note"]).upper(), st["th"]),
        ]]
        statuses: dict[tuple[int, int], str] = {}
        for row_idx, item in enumerate(checks, start=1):
            note_parts = [_xml(item["detail"])] if item.get("detail") else []
            if item.get("risk_note"):
                note_parts.append(f'<font color="#9f1239" size="7.6">{_xml(item["risk_note"])}</font>')
            if item.get("note"):
                note_parts.append(f'<font color="#475569" size="7.6">{_xml(item["note"])}</font>')
            if not note_parts:
                note_parts.append("–")
            st_key = str(item.get("status") or "not_applicable")
            statuses[(row_idx, 2)] = st_key
            rows_data.append([
                Paragraph(_xml(item.get("label")), st["td"]),
                Paragraph(_xml(item.get("legal_reference")), st["td_small"]),
                _status_badge(status_labels.get(st_key, st_key), st_key),
                Paragraph("<br/>".join(note_parts), st["td"]),
            ])
        if len(rows_data) == 1:
            rows_data.append([Paragraph(_xml(t["no_checks"]), st["td"]), "", "", ""])
        return _styled_table(rows_data, [48 * mm, 42 * mm, 21 * mm, 69 * mm], status_cells=statuses)

    sec_no = 1
    story += [_section_heading(sec_no, t["ustg_h"], st), check_table(report["ustg_matrix"], t["col_item"]), Spacer(1, 5 * mm)]
    sec_no += 1

    einvoice = report.get("einvoice")
    if einvoice and not einvoice.get("error"):
        container = f"{t['embedded_as']} {einvoice['attachment_name']}" if einvoice["source"] == "embedded" else t["pure_xml"]
        meta_tbl = Table(
            [
                [Paragraph(_xml(t["sha_xml"]), st["td_small"]), Paragraph(_xml(einvoice["xml_sha256"]), st["hash"])],
                [Paragraph(_xml(t["spec_bt24"]), st["td_small"]), Paragraph(_xml(einvoice["specification_id"]), st["hash"])],
            ],
            colWidths=[42 * mm, _CONTENT_W - 42 * mm],
        )
        meta_tbl.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ]))
        story.append(_keep_next_block([
            _section_heading(sec_no, t["einvoice_h"], st),
            Paragraph(f"<b>{_xml(einvoice['profile'])}</b> · Syntax {_xml(einvoice['syntax'])} · {_xml(container)}", st["body"]),
            meta_tbl,
        ]))

        bt_rows: list[list[Any]] = [[
            Paragraph("BT", st["th"]),
            Paragraph("BUSINESS TERM", st["th"]),
            Paragraph(_xml(t["bt_val"]).upper(), st["th"]),
        ]]
        for field in einvoice["business_terms"]:
            bt_rows.append([
                Paragraph(_xml(field["bt"]), st["td_mono"]),
                Paragraph(_xml(field["label"]), st["td"]),
                Paragraph(_xml(field["value"]), st["td_mono"]),
            ])
        story += [_styled_table(bt_rows, [20 * mm, 64 * mm, 96 * mm]), Spacer(1, 3 * mm)]

        if einvoice["visual_check"]:
            vis_rows: list[list[Any]] = [[
                Paragraph("BT", st["th"]),
                Paragraph(_xml(t["visual_h"]).upper(), st["th"]),
                Paragraph(_xml(t["visual_col_res"]).upper(), st["th"]),
                Paragraph(_xml(t["bt_val"]).upper(), st["th"]),
            ]]
            vis_statuses: dict[tuple[int, int], str] = {}
            for row_idx, chk in enumerate(einvoice["visual_check"], start=1):
                tone = "pass" if chk["status"] == "match" else "warn" if chk["status"] == "not_found" else "fail"
                vis_statuses[(row_idx, 2)] = tone
                val_txt = str(chk["xml_value"] or "") + (f" / PDF {chk['visual_value']}" if chk.get("visual_value") else "")
                vis_rows.append([
                    Paragraph(_xml(chk["bt"]), st["td_mono"]),
                    Paragraph(_xml(chk["label"]), st["td"]),
                    _status_badge(visual_labels[chk["status"]], tone),
                    Paragraph(_xml(val_txt), st["td_mono"]),
                ])
            story += [_styled_table(vis_rows, [20 * mm, 52 * mm, 36 * mm, 72 * mm], status_cells=vis_statuses), Spacer(1, 5 * mm)]
        else:
            story.append(Spacer(1, 2 * mm))
        sec_no += 1

    # Ohne beschriebenes KI-System kein nummerierter Abschnitt (Zeile im Überblick auf Seite 1).
    if ai_applicable:
        ai_parts: list[Any] = [
            _section_heading(sec_no, t["ai_h"], st),
            Spacer(1, 1.5 * mm),
            Paragraph(
                f"<b>{_xml(ai['risk_label'])}</b>{(' · ' + _xml(', '.join(ai['annex_iii']))) if ai['annex_iii'] else ''}",
                st["body"],
            ),
        ]
        if ai.get("reasoning"):
            ai_parts += [Spacer(1, 1 * mm), Paragraph(_xml(ai["reasoning"]), st["small"])]
        if ai["article_references"]:
            ai_parts += [Spacer(1, 1 * mm), Paragraph(f"{_xml(t['articles_html'])}: {_xml(', '.join(ai['article_references']))}", st["small"])]
        for chk in ai["checks"]:
            if chk.get("note"):
                ai_parts.append(Paragraph(_xml(chk["note"]), st["small"]))
            if chk.get("risk_note"):
                ai_parts.append(Paragraph(_xml(chk["risk_note"]), st["risk"]))
        story += [KeepTogether(ai_parts), Spacer(1, 5 * mm)]
        sec_no += 1

    story += [_section_heading(sec_no, t["math_h"], st), check_table(report["math_checks"], t["col_check"]), Spacer(1, 5 * mm)]
    sec_no += 1

    pii_rows: list[list[Any]] = [[
        Paragraph(_xml(t["col_cat"]).upper(), st["th"]),
        Paragraph(_xml(t["col_val"]).upper(), st["th"]),
        Paragraph(_xml(t["col_src"]).upper(), st["th"]),
        Paragraph(_xml(t["col_conf"]).upper(), st["th_num"]),
    ]]
    for fnd in report["gdpr"]["findings"][:25]:
        pii_rows.append([
            Paragraph(_xml(fnd["category"]), st["td"]),
            Paragraph(_xml(fnd["masked_value"]), st["td_mono"]),
            Paragraph(_xml(source_labels.get(fnd["source"], fnd["source"])), st["td"]),
            Paragraph(f"{fnd['confidence'] * 100:.0f} %", st["td_num"]),
        ])
    if len(pii_rows) == 1:
        pii_rows.append([Paragraph(_xml(t["no_pii"]), st["td"]), "", "", ""])
    story += [_section_heading(sec_no, t["gdpr_html"], st), _styled_table(pii_rows, [50 * mm, 60 * mm, 44 * mm, 26 * mm], num_cols={3}), Spacer(1, 5 * mm)]
    sec_no += 1

    override = report.get("human_override")
    if override:
        ov_rows = [
            [Paragraph(_xml(t["auditor"]), st["td_small"]), Paragraph(f"<b>{_xml(override['auditor_name'])}</b> · {_xml(fmt_ts(override['overridden_at']))}", st["td"])],
            [Paragraph(_xml(t["ai_level"]), st["td_small"]), Paragraph(f"{_xml(override['previous_risk_level'])} -> <b>{_xml(override['new_risk_level'])}</b>", st["td"])],
            [Paragraph("Score", st["td_small"]), Paragraph(f"{_xml(override['previous_score'])} -> <b>{_xml(override['new_score'])}</b>", st["td"])],
            [Paragraph(_xml(t["legal_basis"]), st["td_small"]), Paragraph(_xml(override["legal_basis"]), st["td"])],
            [Paragraph(_xml(t["reason"]), st["td_small"]), Paragraph(_xml(override["reason"]), st["td"])],
            [Paragraph(_xml(t["ledger_entry"]), st["td_small"]), Paragraph(f"{_xml(override['ledger_entry_hash'])} · {_xml(t['ed25519_signed'])}", st["hash"])],
        ]
        ov_tbl = Table(ov_rows, colWidths=[38 * mm, _CONTENT_W - 38 * mm], splitByRow=1, splitInRow=1)
        ov_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef2ff")),
            ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#c7d2fe")),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story += [_section_heading(sec_no, t["override_h"], st), ov_tbl, Spacer(1, 5 * mm)]
        sec_no += 1

    led_rows: list[list[Any]] = [[
        Paragraph(_xml(t["col_seq"]).upper(), st["th_num"]),
        Paragraph(_xml(t["col_event"]).upper(), st["th"]),
        Paragraph(_xml(t["col_time"]).upper(), st["th"]),
        Paragraph(_xml(t["col_person"]).upper(), st["th"]),
        Paragraph("SCORE", st["th_num"]),
        Paragraph(_xml(t["col_ehash"]).upper(), st["th"]),
        Paragraph(_xml(t["col_sig"]).upper(), st["th"]),
    ]]
    for entry in sorted(report["ledger_history"], key=lambda item: item["seq"] or 0):
        evt_txt = str(entry["event_label"]) + (f" · {t['milestone_tag']}" if entry["milestone"] else "")
        led_rows.append([
            Paragraph(_xml(entry["seq"]), st["td_num"]),
            Paragraph(_xml(evt_txt), st["td"]),
            Paragraph(_xml(fmt_ts(entry["timestamp_utc"])), st["td_small"]),
            Paragraph(_xml(entry["actor"]), st["td"]),
            Paragraph(_xml(entry["compliance_score"]), st["td_num"]),
            Paragraph(_xml(f"{entry['entry_hash'][:16]}…"), st["td_mono"]),
            Paragraph("Ed25519" if entry["signed"] else "–", st["td_small"]),
        ])
    if len(led_rows) == 1:
        led_rows.append([Paragraph(_xml(t["no_ledger"]), st["td"]), "", "", "", "", "", ""])
    led_tbl = _styled_table(led_rows, [11 * mm, 41 * mm, 36 * mm, 29 * mm, 13 * mm, 33 * mm, 17 * mm], num_cols={0, 4})
    story += [_section_heading(sec_no, t["ledger_h"], st), led_tbl, Spacer(1, 6 * mm)]

    # Abschließender Hinweisblock
    legal_line = Table([[""]], colWidths=[_CONTENT_W], rowHeights=[1])
    legal_line.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.7, _C_LINE), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    legal_line.keepWithNext = True
    story += [
        KeepTogether([
            legal_line,
            Spacer(1, 2.5 * mm),
            Paragraph(f"{_xml(report['disclaimer'])}<br/>{_xml(t['generated'])} {_xml(fmt_ts(report['generated_at']))} · {_xml(report['generator'])}", st["legal"]),
        ])
    ]

    return _build_pdf(
        story,
        top_left=f"{APP_TITLE} · {t['report_type']}",
        top_right=str(doc_info["filename"]),
        bottom_left=f"Audit-ID {str(report['audit_id'] or '–')[:8]} · {t['generated']} {fmt_date(report['generated_at'])}",
        page_label=lt["page"],
        of_label=lt["of"],
        title=f"{t['report_type']} – {doc_info['filename']}",
    )


# ---------------------------------------------------------------------------
# GoBD-Verfahrensdokumentation (PDF)
# ---------------------------------------------------------------------------


def render_procedural_pdf(doc: dict[str, Any], *, lang: str | None = None) -> bytes:
    """Erzeugt die A4-PDF-Fassung der GoBD-Verfahrensdokumentation (inkl. Anhang A)."""
    lang = lang or str(doc.get("lang") or "de")
    ui = procedural_ui(lang)
    lt = procedural_layout_text(lang)
    st = _styles()
    todo = str(doc.get("todo") or ui["todo"])

    def todo_xml(value: Any) -> str:
        raw = _xml(value)
        token_xml = _xml(todo)
        if not token_xml or token_xml not in raw:
            return raw
        return raw.replace(token_xml, f'<font backColor="#FEF3C7" color="#92400E"><b>{token_xml}</b></font>')

    stand_date = str(doc.get("generated_at") or "")[:10]
    if len(stand_date) == 10 and lang != "en":
        stand_str = f"{stand_date[8:10]}.{stand_date[5:7]}.{stand_date[0:4]}"
    else:
        stand_str = stand_date

    story: list[Any] = [
        Paragraph("GoBD Rz. 151 ff. · § 147 AO · VO (EU) 2024/1689", st["kicker"]),
        Paragraph(_xml(doc["title"]), st["title"]),
        Paragraph(
            f"{_xml(doc['subtitle'])}<br/>{_xml(ui['stand'])} {_xml(stand_str)} · "
            f"{_xml(APP_TITLE)} v{_xml(doc['version'])} · {_xml(ui['ruleset'])} {_xml(doc['ruleset_version'])}",
            st["lead"],
        ),
        Spacer(1, 3 * mm),
        _DashedBox(f"<b>{_xml(doc['status'])}</b><br/>{_xml(doc['retention'])}", st["callout"]),
        Spacer(1, 2.5 * mm),
        Paragraph(_xml(doc["basis"]), st["small"]),
        Spacer(1, 4 * mm),
    ]

    for section in doc["sections"]:
        story.append(_section_heading(section["number"], section["title"], st))
        for block in section["blocks"]:
            story.append(Paragraph(_xml(block["heading"]), st["h3"]))
            if "table" in block:
                head = block["table"]["head"]
                tbl_rows = [[Paragraph(_xml(cell).upper(), st["th"]) for cell in head]]
                for row in block["table"]["rows"]:
                    tbl_rows.append([Paragraph(todo_xml(str(cell)), st["td"]) for cell in row])
                cols = (
                    [48 * mm, _CONTENT_W - 48 * mm]
                    if len(head) == 2
                    else [42 * mm, _CONTENT_W - 84 * mm, 42 * mm]
                )
                story += [_styled_table(tbl_rows, cols), Spacer(1, 2.5 * mm)]
            if "list" in block:
                for item in block["list"]:
                    story.append(Paragraph(f"• {todo_xml(item)}", st["bullet"]))
                story.append(Spacer(1, 1.5 * mm))
            if "text" in block:
                story += [Paragraph(todo_xml(block["text"]), st["body"]), Spacer(1, 2 * mm)]
        story.append(Spacer(1, 3 * mm))

    annex = doc.get("annex")
    doc_name = ""
    if annex:
        doc_name = str(annex["rows"][0][1]) if annex.get("rows") else ""
        story.append(PageBreak())
        story.append(_section_heading("A", annex["title"], st))
        fact_rows = [
            [Paragraph(_xml(k), st["td_small"]), Paragraph(_xml(v), st["hash"] if k == "SHA-256" else st["td"])]
            for k, v in annex["rows"]
        ]
        fact_tbl = Table(fact_rows, colWidths=[38 * mm, _CONTENT_W - 38 * mm])
        fact_tbl.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story += [fact_tbl, Spacer(1, 4 * mm)]

        led_rows: list[list[Any]] = [[
            Paragraph("SEQ", st["th_num"]),
            Paragraph(_xml(ui["col_event"]).upper(), st["th"]),
            Paragraph(_xml(ui["col_time"]).upper(), st["th"]),
            Paragraph(_xml(ui["col_actor"]).upper(), st["th"]),
            Paragraph("SCORE", st["th_num"]),
            Paragraph(_xml(ui["col_hash"]).upper(), st["th"]),
            Paragraph(_xml(ui["col_sig"]).upper(), st["th"]),
        ]]
        for e in annex["ledger"]:
            led_rows.append([
                Paragraph(_xml(e["seq"]), st["td_num"]),
                Paragraph(_xml(e["event"]), st["td"]),
                Paragraph(_xml(e["timestamp"]), st["td_small"]),
                Paragraph(_xml(e["actor"]), st["td"]),
                Paragraph(_xml(e["score"]), st["td_num"]),
                Paragraph(_xml(f"{e['entry_hash'][:16]}…"), st["td_mono"]),
                Paragraph("Ed25519" if e["signed"] else "–", st["td_small"]),
            ])
        if len(led_rows) == 1:
            led_rows.append([Paragraph(_xml(ui["no_ledger"]), st["td"]), "", "", "", "", "", ""])
        story += [_styled_table(led_rows, [11 * mm, 38 * mm, 35 * mm, 34 * mm, 13 * mm, 32 * mm, 17 * mm], num_cols={0, 4}), Spacer(1, 5 * mm)]

    story.append(Paragraph(_xml(ui["footer"]), st["legal"]))

    return _build_pdf(
        story,
        top_left=f"{APP_TITLE} · {doc['title']}",
        top_right=doc_name,
        bottom_left=f"{ui['stand']} {stand_str} · {ui['ruleset']} {doc['ruleset_version']}",
        page_label=lt["page"],
        of_label=lt["of"],
        title=f"{doc['title']}{(' – ' + doc_name) if doc_name else ''}",
    )
