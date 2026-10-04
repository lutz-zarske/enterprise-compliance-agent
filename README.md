# Enterprise KI-Compliance- & Dokumenten-Agent

Institutionelles Backend zur automatisierten Prüfung von Geschäftsdokumenten:
**Rechnungs- und Vertragsextraktion**, **EU-AI-Act-Klassifizierung** nach
Anhang III und **DSGVO-Audit** mit Erkennung besonderer Datenkategorien —
vollständig lokal, ohne dass ein Dokument den Rechner verlässt.

| | |
|---|---|
| **Stack** | Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 Core · httpx · pdfplumber |
| **Inferenz** | Ollama REST API (`/api/chat`), `qwen2.5:14b-instruct`, `format=json`, `temperature=0`, `num_ctx=16384` |
| **Persistenz** | SQLite (Default), austauschbar gegen PostgreSQL/Supabase über `DATABASE_URL` |
| **Lizenzlage** | Alle Laufzeitabhängigkeiten MIT / BSD / Apache-2.0 |

---

## Architektur

```
                     ┌────────────────────────────────────────────┐
  multipart/PDF  ──► │  main.py    5 Endpunkte, Auth, Fehlerformat │
                     └───────────────┬────────────────────────────┘
                                     │
                     ┌───────────────▼────────────────────────────┐
                     │  services.py   Orchestrierung + Regelwerk   │
                     └───┬───────────────┬───────────────┬────────┘
                         │               │               │
            ┌────────────▼───┐  ┌────────▼───────┐  ┌────▼─────────────┐
            │ pdf_reader.py  │  │    llm.py      │  │  redaction.py    │
            │ pdfplumber,    │  │ Ollama HTTP,   │  │ Maskierung +     │
            │ Scan-Erkennung │  │ JSON-Repair    │  │ Regex-PII-Scan   │
            └────────────────┘  └────────┬───────┘  └──────────────────┘
                                         │
                              ┌──────────▼──────────┐
                              │  Ollama (127.0.0.1) │
                              │ qwen2.5:14b-instruct│
                              └─────────────────────┘

            schemas.py  ── Pydantic v2: LLM-Vertrag *und* OpenAPI-Vertrag
            db.py       ── DocumentRepository-Protocol (SQLite ⇄ PostgreSQL)
```

**Kein LangChain, kein CrewAI.** Der Pfad vom Dokument bis in die Datenbank ist
ein lesbarer HTTP-Call plus Schemavalidierung — nachvollziehbar, testbar und
ohne Framework-Abstraktionen, die im Compliance-Kontext niemand auditieren will.

---

## Schnellstart

### 1. Voraussetzungen

```bash
ollama pull qwen2.5:14b-instruct
```

### 2. Installation

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
```

Unter Linux/macOS entsprechend `source .venv/bin/activate` und `cp`.

### 3. Inferenzstrecke prüfen

```bash
python scripts/smoke_test_ollama.py
```

Prüft in drei Stufen Erreichbarkeit, Modellverfügbarkeit und einen echten
Inferenzlauf gegen ein deutsches Beispieldokument. `--quick` überspringt Stufe 3.

### 4. Server starten

```bash
uvicorn app.main:app --reload
```

* Swagger UI: <http://127.0.0.1:8000/docs>
* ReDoc: <http://127.0.0.1:8000/redoc>
* OpenAPI-Schema: <http://127.0.0.1:8000/openapi.json>

---

## Endpunkte

| Methode | Pfad | Zweck |
|---|---|---|
| `GET` | `/health` | Zustand von Datenbank, Ollama-Erreichbarkeit und Modell |
| `POST` | `/documents/upload` | PDF-Upload mit Typ-, Größen- und Textlayer-Validierung |
| `POST` | `/documents/{id}/extract` | Extraktion + Compliance-Audit (zwei LLM-Läufe) |
| `GET` | `/documents/{id}` | Detailansicht inklusive Audit und Textvorschau |
| `GET` | `/documents` | Tabellarische Übersicht mit Compliance-Kennzahlen |

### Beispielablauf

```bash
curl -s http://127.0.0.1:8000/health

curl -s -X POST http://127.0.0.1:8000/documents/upload \
     -F "file=@rechnung.pdf;type=application/pdf"

curl -s -X POST http://127.0.0.1:8000/documents/<ID>/extract

curl -s "http://127.0.0.1:8000/documents?limit=20&status=extracted"
```

Ist in der `.env` ein `API_KEY` gesetzt, verlangen alle `/documents`-Endpunkte
den Header `-H "X-API-Key: <wert>"`. `/health` bleibt bewusst offen, damit
Monitoring ohne Secret funktioniert.

### Fehlerformat

Jeder Fehler verlässt die Anwendung im selben, maschinenlesbaren Format:

```json
{
  "error": {
    "code": "no_text_layer",
    "message": "Es konnten nur 0 Zeichen extrahiert werden (Mindestanforderung: 40).",
    "hint": "Das Dokument enthaelt keinen Textlayer und ist vermutlich ein Scan. Bitte vorab per OCR (z. B. OCRmyPDF) in ein durchsuchbares PDF wandeln."
  }
}
```

| Code | HTTP | Bedeutung |
|---|---|---|
| `invalid_upload` | 415 | Keine PDF-Endung oder falscher Content-Type |
| `file_too_large` | 413 | Über `MAX_UPLOAD_BYTES` |
| `invalid_pdf` | 422 | PDF-Signatur fehlt oder Datei beschädigt |
| `no_text_layer` | 422 | Scan ohne Textlayer — OCR nötig |
| `document_not_found` | 404 | Unbekannte ID |
| `unauthorized` | 401 | `X-API-Key` fehlt oder falsch |
| `llm_invalid_response` | 502 | Modellantwort auch nach Reparaturrunde unbrauchbar |
| `ollama_unavailable` | 503 | Ollama nicht erreichbar |

---

## Wie das Compliance-Ergebnis entsteht

`POST /documents/{id}/extract` führt **zwei** fokussierte LLM-Läufe aus statt
eines gemischten — bei einem 14B-Modell messbar stabiler:

1. **Extraktion** — `doc_type`, `sender`, `recipient`, `document_number`,
   `document_date`, `due_date`, `total_amount`, `currency`, `iban`, `summary`,
   `issues`.
2. **Compliance-Audit** — EU AI Act (Anhang III) und DSGVO (Art. 9/10).

Danach greifen **deterministische Kontrollen**, die dem Modell nicht blind
vertrauen:

| Kontrolle | Wirkung |
|---|---|
| **IBAN-Prüfsumme (MOD-97)** | `iban_valid` im Ergebnis; ungültige IBAN erzeugt einen Eintrag in `issues` |
| **§ 14 UStG-Pflichtangaben** | Fehlende Rechnungsnummer, fehlendes Datum, fehlender Betrag oder Datumswidersprüche werden ergänzt |
| **Regex-PII-Scan** | Zweitmeinung zum Modell: IBANs (prüfsummenvalidiert), E-Mail, Telefon, Steuer-ID, Ausweis-, Sozialversicherungsnummer, Geburtsdatum sowie Schlüsselwörter für Gesundheit, Religion, Gewerkschaft, Politik, Herkunft und Strafrecht |
| **Zusammenführung** | Deckungsgleiche Treffer werden zu einem Befund mit `source: "both"` und erhöhter Konfidenz verschmolzen |
| **Maskierungszwang** | Liefert das Modell einen Klartextwert, wird er vor dem Schreiben maskiert (`DE89********3000`) — auch der Kontexttext |
| **Risiko-Eskalation DSGVO** | Belegte besondere Kategorien heben die Stufe auf `high`; abgesenkt wird nie |
| **Risiko-Eskalation AI Act** | Ist eine Anhang-III-Kategorie belegt, gilt `high` (Art. 6 Abs. 2) — auch wenn das Modell `limited` schrieb; die Korrektur wird in `reasoning` protokolliert |

Reproduzierbarkeit: `temperature=0` plus fester `seed` — dieselbe Eingabe
liefert dieselbe Bewertung. Für ein Audit ist das die Mindestanforderung.

### Abgedeckte Anhang-III-Kategorien

Alle acht Bereiche sind modelliert; der Prompt betont die drei praxisrelevanten:

* **Nr. 4 — Beschäftigung/Personalmanagement**: CV-Screening, Recruiting, Leistungsbewertung
* **Nr. 2 — Kritische Infrastruktur**: Steuerung von Strom, Wasser, Gas, Verkehr
* **Nr. 5 — Wesentliche Dienste**: Kreditwürdigkeits- und Bonitätsprüfung, Scoring

---

## Datenschutz

* **Lokale Inferenz.** Ausschließlich `127.0.0.1:11434`; kein Dokumentinhalt
  verlässt den Rechner.
* **Maskierte Persistenz.** PII-Treffer werden nur maskiert gespeichert
  (`MASK_PII_IN_STORAGE=true`), inklusive Kontextausschnitten.
* **Volltext bewusst gespeichert.** Der extrahierte Text liegt in der Datenbank,
  damit eine erneute Auswertung ohne neues PDF-Parsing möglich ist. `data/` ist
  über `.gitignore` ausgeschlossen — in einem Produktivsystem gehört dazu
  Festplattenverschlüsselung und ein Löschkonzept nach Art. 17 DSGVO.

---

## Wechsel auf PostgreSQL / Supabase

Die Anwendung spricht nur über das `DocumentRepository`-Protocol mit der
Datenbank. Das Schema ist portabel definiert (keine SQLite-Spezialitäten):

```bash
pip install "psycopg[binary]"
```

```env
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/compliance
```

Mehr ist nicht nötig — kein Schema-Bruch, keine Codeänderung. Für pgvector
genügt später eine zusätzliche `embedding`-Spalte in `documents_table`; die
bestehenden Spalten bleiben unangetastet.

---

## Tests

```bash
python -m pytest
```

68 Tests, Laufzeit ca. 5 Sekunden, **ohne laufendes Ollama** — der Dienst wird
auf HTTP-Ebene über `httpx.MockTransport` nachgestellt. Dadurch laufen
Payload-Aufbau, JSON-Extraktion, Schemavalidierung und Reparaturrunde in jedem
Test real mit, statt wegabstrahiert zu werden. PDF-Fixtures werden zur Laufzeit
erzeugt (kein reportlab, keine Binärdateien im Repository).

| Datei | Schwerpunkt |
|---|---|
| `tests/test_schemas.py` | Deutsche Zahlen-/Datumsformate, Platzhaltertexte, halluzinierte Enums, JSON-Roundtrip |
| `tests/test_pdf_reader.py` | Textlayer, Mehrseitigkeit, Scans, beschädigte und getarnte Dateien |
| `tests/test_redaction.py` | Maskierung, Regex-Scan, Prüfsummenfilter, Befundzusammenführung |
| `tests/test_llm.py` | Request-Payload, Reparaturrunde, fehlendes Modell, Dienstausfall |
| `tests/test_api.py` | Alle fünf Endpunkte, Fehlerformat, Auth, Eskalationsregeln, OpenAPI |

---

## Docker

```bash
docker compose up --build                 # API im Container, Ollama auf dem Host
docker compose --profile full up --build  # zusätzlich ein Ollama-Container
```

Beim Profil `full` das Modell einmalig laden:

```bash
docker compose exec ollama ollama pull qwen2.5:14b-instruct
```

Das Image läuft als unprivilegierter Benutzer (UID 10001). Datenbank und
Uploads liegen im benannten Volume `app-data` und überleben Container-Neubauten.
Ein Bind-Mount von `./data` ist bewusst nicht vorgesehen: Auf Linux-Hosts fehlen
dem Container-Benutzer dort die Schreibrechte. Wer die Daten dennoch im
Host-Dateisystem braucht, muss das Verzeichnis vorher mit
`sudo chown -R 10001:10001 ./data` vorbereiten.

Sicherung der Daten:

```bash
docker run --rm -v enterprise-compliance-agent_app-data:/data -v "$PWD":/backup \
  alpine tar czf /backup/app-data.tgz -C /data .
```

---

## Projektstruktur

```
app/
  config.py       pydantic-settings, abgeleitete Pfade und URLs
  schemas.py      Pydantic v2: Extraktion, Compliance, Health, Fehler
  db.py           SQLAlchemy-Core-Schema + DocumentRepository-Protocol
  pdf_reader.py   pdfplumber mit getrennten Fehlerklassen je Ursache
  redaction.py    Maskierungszwang und regelbasierte PII-Erkennung
  llm.py          Ollama-Client, Prompts, JSON-Reparaturrunde
  services.py     Orchestrierung und deterministisches Regelwerk
  main.py         FastAPI: 5 Endpunkte, Auth, Fehlerabbildung, OpenAPI
scripts/
  smoke_test_ollama.py
tests/
data/
  agent.db        SQLite (wird beim ersten Start angelegt)
  uploads/        abgelegte PDFs
```

---

## Grenzen

Das System erzeugt eine **technische Vorprüfung**, keine Rechtsberatung. Die
Einstufung nach EU AI Act und DSGVO ist ein Vorschlag zur Entlastung der
fachlichen Prüfung und ersetzt weder Rechtsabteilung noch Datenschutzbeauftragte.

Weitere bewusste Grenzen:

* **Kein OCR.** Gescannte PDFs ohne Textlayer werden erkannt und mit
  Handlungshinweis abgelehnt, statt Systemabhängigkeiten wie Tesseract
  einzuführen.
* **Synchrone Extraktion.** Ein `POST /extract` blockiert für die Dauer beider
  LLM-Läufe (bei 14B je nach Hardware einige Sekunden bis Minuten). Für höhere
  Last wäre eine Queue der nächste Schritt.
* **Keine Migrationen.** `metadata.create_all` legt fehlende Tabellen an; für
  Schemaänderungen im Betrieb gehört Alembic dazu.

## Lizenz

MIT.
