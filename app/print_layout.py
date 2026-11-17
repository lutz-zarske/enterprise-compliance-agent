"""Gemeinsames A4-Drucklayout für Prüfzertifikat und Verfahrensdokumentation.

Die Berichte sind eigenständige HTML-Dateien (ohne Skripte, CSP ``default-src 'none'``).
Am Bildschirm erscheinen sie als A4-Blätter, beim Drucken bzw. „Als PDF speichern“
setzt der Browser Seitenränder, Kopf- und Fußzeile mit Seitenzahl (CSS Paged Media).
"""

from __future__ import annotations

FONT_STACK = 'Inter, "Segoe UI", system-ui, -apple-system, Helvetica, Arial, sans-serif'


def css_string(value: str) -> str:
    """Wert als CSS-Zeichenkette: Anführungszeichen, Backslash und ``<`` maskiert (kein Ausbruch aus <style>)."""
    cleaned = " ".join(str(value).split())
    escaped = cleaned.replace("\\", "\\\\").replace('"', '\\"').replace("<", "\\3c ").replace(">", "\\3e ")
    return f'"{escaped}"'


def page_rules(*, top_left: str, top_right: str, bottom_left: str, page_label: str, of_label: str) -> str:
    """@page mit laufender Kopf- und Fußzeile; Seitenzahl als „Seite x von y“."""
    box = f"font-family: {FONT_STACK}; font-size: 7.5pt; color: #64748b;"
    return f"""@page {{
  size: A4;
  margin: 22mm 16mm 20mm;
  @top-left {{ content: {css_string(top_left)}; {box} font-weight: 600; vertical-align: bottom; padding-bottom: 6mm; }}
  @top-right {{ content: {css_string(top_right)}; {box} vertical-align: bottom; padding-bottom: 6mm; }}
  @bottom-left {{ content: {css_string(bottom_left)}; {box} vertical-align: top; padding-top: 6mm; }}
  @bottom-right {{ content: {css_string(page_label)} " " counter(page) " " {css_string(of_label)} " " counter(pages); {box} vertical-align: top; padding-top: 6mm; }}
}}"""


BASE_CSS = """
:root { --ink: #0f172a; --muted: #475569; --subtle: #64748b; --line: #e2e8f0; --hair: #eef2f6; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; background: #e8ecf1; color: var(--ink); font-family: Inter, "Segoe UI", system-ui, -apple-system, Helvetica, Arial, sans-serif;
  font-size: 10pt; line-height: 1.5; font-variant-numeric: tabular-nums; }
.hint { max-width: 210mm; margin: 18px auto 0; padding: 0 12px; font-size: 9pt; color: var(--subtle); text-align: center; }
.sheet { background: #fff; width: 210mm; max-width: calc(100% - 24px); min-height: 297mm; margin: 14px auto 24px; padding: 18mm 16mm 18mm;
  box-shadow: 0 1px 2px rgba(15, 23, 42, .06), 0 10px 30px rgba(15, 23, 42, .08); }
.running { display: flex; justify-content: space-between; gap: 12px; margin: -6mm 0 9mm; padding-bottom: 6px; border-bottom: 1px solid var(--line);
  font-size: 7.5pt; color: var(--subtle); }
.running span:first-child { font-weight: 600; }
.kicker { font-size: 7.5pt; letter-spacing: .14em; text-transform: uppercase; color: var(--subtle); font-weight: 600; }
h1 { font-size: 20pt; line-height: 1.15; margin: 6px 0 0; letter-spacing: -.01em; font-weight: 650; overflow-wrap: anywhere; }
h2 { display: flex; gap: 10px; align-items: baseline; font-size: 11.5pt; margin: 26px 0 8px; padding-bottom: 6px; border-bottom: 1px solid var(--line); }
h2 .no { min-width: 1.4em; color: var(--subtle); font-weight: 600; }
h3 { font-size: 10pt; margin: 16px 0 4px; }
p { margin: 6px 0; }
ul { margin: 6px 0; padding-left: 18px; }
li { margin: 3px 0; }
.lead { margin-top: 6px; color: var(--muted); font-size: 9pt; }
.small { font-size: 8.5pt; color: var(--muted); }
.label { margin-bottom: 4px; font-size: 7.5pt; letter-spacing: .1em; text-transform: uppercase; color: var(--subtle); font-weight: 600; }
.mono { font-family: "JetBrains Mono", Consolas, "Courier New", monospace; font-size: 8pt; word-break: break-all; font-variant-numeric: normal; }
table { width: 100%; border-collapse: collapse; margin-top: 6px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--hair); vertical-align: top; }
thead th { font-size: 7.5pt; font-weight: 600; text-transform: uppercase; letter-spacing: .08em; color: var(--subtle); border-bottom: 1px solid var(--line); }
.num { text-align: right; }
.facts { display: grid; grid-template-columns: 38mm minmax(0, 1fr); gap: 5px 14px; margin: 8px 0 0; font-size: 9pt; }
.facts dt { color: var(--subtle); }
.facts dd { margin: 0; min-width: 0; }
.note { margin-top: 14px; padding: 10px 12px; border: 1px dashed #94a3b8; border-radius: 8px; font-size: 9pt; color: #334155; }
footer.legal { margin-top: 26px; padding-top: 10px; border-top: 1px solid var(--line); font-size: 7.5pt; line-height: 1.5; color: var(--subtle); }
@media screen and (max-width: 820px) {
  .sheet { min-height: 0; padding: 10mm 6mm; }
  .facts { grid-template-columns: 1fr; gap: 0 0; }
  .facts dd { margin-bottom: 6px; }
}
@media print {
  body { background: #fff; }
  .hint, .running { display: none; }
  .sheet { width: auto; max-width: none; min-height: 0; margin: 0; padding: 0; box-shadow: none; }
  .sheet + .sheet { break-before: page; }
  h2, h3 { break-after: avoid; }
  tr, .keep, .facts > * { break-inside: avoid; }
  thead { display: table-header-group; }
}
"""
