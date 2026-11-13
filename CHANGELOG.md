# Changelog

Wesentliche Änderungen je Version (Versionierung nach [SemVer](https://semver.org/lang/de/)).
Details zu Aufbau und Entscheidungen: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

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
