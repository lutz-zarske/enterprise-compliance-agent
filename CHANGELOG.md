# Changelog

Wesentliche Änderungen je Version (Versionierung nach [SemVer](https://semver.org/lang/de/)).
Details zu Aufbau und Entscheidungen: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## v2.6.0 – 17.11.2026

**Mehrsprachigkeit (DE / EN / ES)**

- Vollständiger Sprachschalter (**Deutsch | English | Español**) unter **Einstellungen › Darstellung & Sprache**, vor dem ersten Bildaufbau aktiv (`localStorage` `eca-lang`, `<html lang>`).
- Zentrales i18n-Wörterbuch (`frontend/src/lib/i18n.tsx`) für Navigation, Inspektor, KI-Einstellungen, Statusmeldungen, Fehlermeldungen, Tour, Tastaturkürzel, Datums-/Währungsformate und dynamische Regelwerk-/DSGVO-Hinweise.
- Mehrsprachige Backend-Exports & Copilot (`?lang=de|en|es` mit Default `de`): Audit-Zertifikate (`HTML`, `Markdown`, `JSON`), GoBD-Verfahrensdokumentation (`HTML`, `Markdown`), GoBD-Prüfdatenpaket (`ZIP`) sowie lokalisierte Referenz- und Live-Copilot-Antworten.

**UI-Feinschliff & Barrierefreiheit**

- Modal-Dialoge mit Tab-Focus-Trap, Hintergrund-`inert` auf `#eca-app-shell` und Fokus-Rückgabe beim Schließen.
- `@media (forced-colors: active)` High-Contrast-Regeln, `@media (pointer: coarse)` vergrößerte Touch-Ziele (`36 × 36 px`) sowie permanente Sichtbarkeit von Anpinnen/Archivieren auf Touch-Geräten (`@media (hover: none)`).
- Eindeutige `<h1>`-Hierarchie pro Ansicht, einheitliche Schriftgrößen (`>= 12px`), mehrzeiliges Wrapping langer KPI-Labels (`min-h-16`) und dunkler Logo-Emblem-Container im Light Mode.

**Performance & Windows-Schnellstart**

- `Start_Compliance_Agent.ps1` verschlankt: SHA-256-gecachter Production-Build (`.run/frontend-build.sha256` -> `npm run start`), automatischer Stale-Check veralteter Backend-Versionen auf `:8001`, paralleler Start von Backend & Frontend mit 250-ms-Bereitschaftsprüfung ohne künstliche Wartezeit.
- Schnellerer App-Start durch parallele Initialabfragen (`Promise.all` für Health, Dokumente, KPIs, Ledger, Einstellungen) und direkten Splash-Abbau (`SPLASH_MIN_MS = 0`).

## v2.5.1 – 14.11.2026

- Compliance Copilot: Stoppknopf (und `Esc`) bricht laufende Anfragen sofort im Browser und serverseitig ab (`POST /api/v1/copilot/cancel/{id}`), inklusive „Erneut senden“ am abgebrochenen Turn.
- Konkrete Live-Arbeitsschritte im Copilot: Aufbereitung der Belegstellen, Privacy-Vault-Pseudonymisierung, Modellprüfung sowie ursachengenaue Retry-Meldungen („ausgelastet“ vs. „antwortet nicht rechtzeitig“).
- Gemini-Verbindungstest (`POST /api/settings/test-connection`) führt nun einen leichten 1-Token-Inferenz-Ping (`:generateContent`) aus, sodass Überlastungen (`HTTP 503`) direkt auffallen; `gemini-3.5-flash-lite` als schnelles Standard-Ausweichmodell und Cloud-Timeout auf `45 s` verkürzt.
- Release-Assistent & Modale: `Modal`-Dialoge rendern per Portal auf `document.body` (kein Abschneiden durch die `backdrop-filter`-Kopfzeile); Updates lassen sich direkt per Klick ohne manuelle Freigabe-Felder installieren (`git fetch --tags --force`), wobei lokale Daten (`data/agent.db`, `.env`) vollständig erhalten bleiben.

## v2.5.0 – 13.11.2026

**Ausfallsicherheit und Betrieb**

- KI-Kaskade: Jede Stufe wiederholt bei HTTP 408, 429, 5xx, Verbindungsfehler
  oder Zeitüberschreitung (2 s, 5 s), dann folgen Ausweichmodell desselben
  Anbieters, bis zu sechs Ausweich-Schlüssel (Fernet-verschlüsselt),
  Anbieter-Fallbacks und als letzte Stufe ein gekennzeichnetes Regelwerk-Audit.
  Kein Wechsel bei 401/403 oder Schemafehlern; jeder Wechsel steht als
  `provider_failover` in der Hash-Kette.
- Hintergrund-Jobs: `POST /documents/{id}/extract` antwortet sofort mit
  HTTP 202; vier Phasen mit Fortschritt und geglätteter Restzeit, Abbruch mit
  Erhalt des vorherigen Stands, Batch-Prüfung, Erkennung hängender Jobs.
- Lokale KI per Klick starten und stoppen (nur direkt am Server); fehlt das
  lokale Modell, wird ein installiertes vorgeschlagen, nie still gewechselt.
- Optionales Cloud-Tagesbudget; Ollama-Kontext 32 768 Tokens; `localhost`
  wird intern auf `127.0.0.1` normalisiert.
- Fehlermeldungen nennen die Ursache je Status (Anfragelimit, Überlast,
  Störung) und ohne Ausweich-Stufe den nächsten Schritt; Meldungen,
  API-Beschreibungen und Prompts durchgehend mit Umlauten.

**Oberfläche**

- Drei Ansichten (Prüfung, Copilot, Protokoll) mit Keep-Alive, Job-Monitor in
  der Kopfzeile, Hinweise nur bei Handlungsbedarf.
- Copilot als Arbeitsbereich mit Live-Arbeitsschritten, Denkstufe und
  klickbaren Zeilenverweisen; Vorschläge passend zum Beleg.
- Zweispaltige Einstellungen mit effektiver Kaskade; Farbschema Dark, Light
  oder System; Schriften lokal, Zahlen in Tabellenziffern.

**Dokumentation und Qualität**

- Architekturüberblick, verbindliche Regeln für Änderungen, englische
  Kurzfassung, MIT-Lizenz; 327 Tests ohne Netz und ohne Sprachmodell.

## v2.4.1 – 12.11.2026

- Windows-Starter robuster: fehlende Python-Pakete werden nachinstalliert,
  Python 3.12/3.11 bevorzugt, Start auch aus anderen Ordnern.
- Logo-Dateien komprimiert, Branding vereinheitlicht.

## v2.4.0 – 05.11.2026

- Erste Ausweich-Kaskade über Anbieter; Modellwechsel und Modell-Katalog im
  Ledger, Archiv für Belege.
- DLP-Gateway `POST /api/v1/redact` für andere Anwendungen; Release-Assistent
  mit Bestätigung des Commit-Hashes und Datenbanksicherung.
- Logo, Kaltstart-Splash, Glas-Kopfzeile, Onboarding-Tour.

## v2.3.0 – 15.10.2026

- Prüf-Workbench: Breitbild-Layout, bidirektionale Fundstellen zwischen
  Kriterium und Belegzeile, Tastaturkürzel, Aktionsleiste.
- USt-IdNr. live bei VIES prüfen (Momentaufnahme, ohne Score-Einfluss).

## v2.2.0 – 06.10.2026

- Begründete Übersteuerung der KI-Einstufung nach Art. 14 Abs. 4 lit. d
  AI Act, Ed25519-signiert im Ledger; Score wird neu berechnet.
- GoBD-Verfahrensdokumentation nach Rz. 153; Aufbewahrungsfristen nach BEG IV.

## v2.1.0 – 05.10.2026

- E-Rechnung nach EN 16931: CII und UBL, ZUGFeRD-/Factur-X-Anhänge,
  XML-Vorrang bei hybriden Rechnungen, Leitweg-ID mit Prüfziffer.
- Prüfdatenpaket als ZIP mit Ed25519-signiertem Manifest und Offline-Prüfung.
- Juristische Einordnung 2026 (AI Act, E-Rechnung, GoBD, DSGVO).

## v2.0.0 – 04.10.2026

- Hash-verkettetes Prüfprotokoll, Multi-Provider-Inferenz mit Privacy Gateway,
  deterministische Scorecard, Prüfzertifikat, menschliche Aufsicht.
- Musterdaten mit Referenz-Audits – nutzbar ohne Sprachmodell.
- Frontend mit Dark und Light Mode, Docker-Stack, CI.

## v1.0.0 – 09.09.2026

- FastAPI-Backend mit Pydantic-v2-Verträgen und lokaler Inferenz über Ollama,
  Next.js-Frontend.

## Konzeption & Prototyp (vor v1.0) – 07/2026 – 08/2026

- Fachliche Anforderungsanalyse zu § 14 UStG, EN 16931 (ZUGFeRD/XRechnung),
  EU AI Act, DSGVO und GoBD; Entwurf des deterministischen Scoring-Modells.
- Erste lokale Extraktions-Prototypen (Ollama, strukturierte Pydantic-Schemata)
  und Architekturkonzept vor dem initialen Repository-Aufbau.
