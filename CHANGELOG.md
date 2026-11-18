# Changelog

Wesentliche Änderungen je Version (Versionierung nach [SemVer](https://semver.org/lang/de/)).
Details zu Aufbau und Entscheidungen: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## v2.7.2 – 18.11.2026

- **Neuprüfung mit aktuellem Parser:** „Neu prüfen“ liest das gespeicherte Original neu ein – XML-Datensatz, Lesefassung und Abgleich mit dem PDF-Bildteil. Belege, die unter einer älteren Version hochgeladen wurden, erhalten so dieselben Befunde wie ein frischer Upload. Das Prüfprotokoll vermerkt die Parser-Version (`einvoice_parser`) und, ob neu eingelesen wurde (`einvoice_reread`); Regelwerk 2026.3.
- **XRechnung-Konformität:** Weist sich ein Beleg als XRechnung aus und verletzt eine BR-DE-Regel oder nutzt eine nicht mehr gültige XRechnung-Version, lautet die Empfehlung „Freigabe unter Vorbehalt – XRechnung-Standard nicht eingehalten“ (gelb, ohne Punktabzug). Begründung im Befund: Pflichtangaben erfüllt, aber nicht konform zum angegebenen Standard; Eingangsplattformen öffentlicher Auftraggeber prüfen gegen diese Regeln. Reine EN-16931-/ZUGFeRD-Profile sind nicht betroffen.
- README erklärt die Trennung: Der Score misst Pflichtangaben und Rechenwerte, die Ampel bildet die Freigabeentscheidung ab.

## v2.7.1 – 18.11.2026

Praxistest mit offiziellen Musterrechnungen der KoSIT (XRechnung-Testsuite) und des Mustangproject.

**E-Rechnung**

- Leistungszeitpunkt (§ 14 Abs. 4 Satz 1 Nr. 6 UStG) wird aus Lieferdatum (BT-72), Rechnungszeitraum (BG-14) **und** Positionszeiträumen (BG-26) gelesen – in UBL und CII. Fehlt der Zeitraum in einzelnen Positionen, erscheint ein Hinweis auf die KoSIT-Regel BR-DE-TMP-32 ohne Punktabzug.
- Abgleich XML ↔ PDF-Bildteil liest Beträge nur hinter Summen-Bezeichnern („Rechnungssumme ohne USt.“, „Summe netto“, „Steuerbetrag“, „Bruttosumme“ …). Datumsangaben und Zahlungsbedingungen („netto bis 15.12.2024“) zählen nie als Betrag; im Zweifel heißt es „nicht eindeutig wiedergefunden“ ohne Abzug statt einer Abweichung mit Abzug.
- Hinweis ohne Punktabzug bei XRechnung-Versionen, die nicht mehr in Kraft sind (laut KoSIT gilt XRechnung 3.0 seit 01.02.2024); neue Geschäftsregel BR-DE-2 (Kontaktangaben des Verkäufers).
- Prüfumfang ehrlich benannt (README, Einstellungen › Über): Pflichtangaben und Rechenwerte – keine vollständige Schematron-Validierung nach EN 16931 bzw. XRechnung.

**Ampel**

- Ampel und Etikett folgen der Freigabeentscheidung: Grün („Vollständig verkehrsfähig & konform“) nur ohne Mangel und ohne Vorbehalt, sonst „Nachforderung nötig“ bzw. „Freigabe unter Vorbehalt“ in Gelb. Ältere gespeicherte Ergebnisse werden in Liste, Scorecard und Berichten genauso angezeigt.
- Verfahrensdokumentation nennt das Siegel lesbar („Freigegeben und versiegelt“) statt `SEALED_APPROVED`.

**Tests**

- Drei offizielle Testbelege als Regressionstests (Herkunft und Lizenz in `tests/fixtures/NOTICE`), dazu CII-Fälle für BG-14, BG-26 und BT-72; 351 Tests.
- Key-Formulare mit verstecktem Benutzerfeld (Chrome-Hinweis zu Passwortformularen).

## v2.7.0 – 18.11.2026

**Ergebnisse und Prüfprotokoll**

- Eine gescheiterte Neuprüfung überdeckt kein gültiges Ergebnis mehr: Status, Score und Siegel bleiben, ein dezenter Hinweis nennt Datum und Ursache („Letzte Neuprüfung am … fehlgeschlagen – gültiges Ergebnis bleibt bestehen“). Belege, die eine ältere Version so hinterlassen hat, repariert der Start automatisch (Status zurück, Fehlertext ohne Klassennamen).
- Siegel im Protokoll lesbar: „Freigegeben und versiegelt durch …“ statt `SEALED_APPROVED`; die Entscheidung bleibt maschinenlesbar in den Details.
- Änderungen an der KI-Kaskade heißen, was sie sind („Ausweich-Kaskade geändert: Ausweichmodell … → …“), statt „Modellwechsel A → A“. Ältere Einträge werden in der Anzeige aus ihren Details genauso beschrieben.
- Prüfer-Einträge aus Versionen vor der Ed25519-Signatur tragen den Hinweis „ohne Signatur (ältere Version)“.
- Copilot-Hinweis zählt einheitlich: „4 Mängel: 2 fehlende Pflichtangaben nach § 14 UStG, 2 Rechenfehler“.

**Texte**

- Umlaute statt ae/oe/ue in allen sichtbaren Meldungen und API-Beschreibungen; gespeicherte Alttexte (z. B. „Auffaelligkeiten“, „Ueberlast“) werden in der Anzeige korrigiert.
- Begrüßung und Tour ohne Zertifizierungsanspruch: „KI-Dokumentenvorprüfung mit revisionssicherem Protokoll – an GoBD und EU AI Act ausgerichtet“; „Aktionsleiste“.
- Copilot-Vorschläge passend zum Beleg (bei vollständigen Rechnungen „Sind alle Pflichtangaben … vorhanden?“, Korrekturanforderung nur bei Mängeln); Seitenmarker im Belegtext in der Sprache der Oberfläche.

**Oberfläche**

- Ketten-Status mit eigenem Symbol (Kette statt Schild) – nicht mehr mit dem Logo zu verwechseln; Kopf-Hash mit #-Symbol.
- Tour: Überschriften bleiben unter der Kopfleiste sichtbar, Hervorhebungen am Fensterrand werden nicht angeschnitten, „Zurück“ erst ab Schritt 2.
- Updater: sichtbarer Ladezustand beim Suchen und „Zuletzt geprüft um …“.
- API-Key-Felder in eigenen Formularen ohne Passwort-Autovervollständigung.
- Belegliste: ungeprüfte Belege zeigen „offen“ und „Noch nicht geprüft“ statt „–“; Statuschip „Versiegelt“.

## v2.6.4 – 18.11.2026

- **Update-Hinweis:** Die Änderungen stehen vollständig als Stichpunkte im Update-Dialog (aus den Commit-Texten bis zum neuen Release) statt als aufklappbare Commit-Liste. Git-Ausgaben werden als UTF-8 gelesen – unter Windows erschienen Umlaute vorher verfälscht.
- **Copilot:** Kopierknopf unter jeder Antwort (ohne Markdown-Sternchen, Zeilenverweise bleiben). Die Abschnitte des Kontexts heißen „Belegtext“ und „Prüfergebnis“ mit Umlauten; das Modell nennt sie nicht mehr wörtlich und beantwortet Fragen zur eigenen Arbeitsweise knapp und zutreffend.
- **Updater:** Ab dieser Version startet auch ein `npm install` beim Neustart unsichtbar (geprüft). Beim Update *auf* v2.6.3 lief der Neustart noch mit dem alten Code der vorherigen Version.

## v2.6.3 – 17.11.2026

**Prüfzertifikat und Verfahrensdokumentation**

- Prüfzertifikat als A4-Druckvorlage neu gesetzt: Seite 1 zeigt Score, Freigabeempfehlung, Kurzbefunde je Bereich (§ 14 UStG, Rechenprüfung, EU AI Act, DSGVO), das Siegel der Prüfperson und die Prüfkette; ab Seite 2 folgen die nummerierten Abschnitte. Beim Drucken bzw. „Als PDF speichern“ tragen alle Seiten Kopf- und Fußzeile mit „Seite x von y“; am Bildschirm erscheinen A4-Blätter. Hinweise ohne Punktabzug zählen nicht als Mangel.
- Verfahrensdokumentation im selben Layout, der Anhang zum Beleg auf eigener Seite.
- Neu: Verfahrensdokumentation als Word-Datei (`format=docx`) – Platzhalter „[vom Unternehmen zu ergänzen]“ gelb markiert und in Word direkt ausfüllbar, Fußzeile mit Seitenzahlen. Ohne zusätzliche Abhängigkeit erzeugt.
- Downloads tragen Beleg und Datum im Namen (z. B. `Pruefdatenpaket_<Beleg>_2026-11-17.zip`); „Als PDF speichern“ schlägt `Pruefzertifikat_<Beleg>_<Prüfdatum>` vor.

**Einstellungen**

- Cloud-Tageslimit direkt in den Einstellungen wählbar (ohne Limit bis 5 Mio. Tokens). Setzt der Server `CLOUD_DAILY_TOKEN_LIMIT`, ist das die Obergrenze; höhere Werte lehnt die API ab.
- Ausweich-Schlüssel in der Reihenfolge Anbieter → API-Key → Modell; das Modell kommt aus der Modell-Liste des Anbieters statt aus einem Freitextfeld.
- Modell-Listen werden beim Start vorgeladen – die KI-Einrichtung öffnet ohne Ladezustand.
- „Über“ erklärt Zweck, Einsatz und Methodik (Lesen, Schützen, Prüfen, Bewerten, Belegen) und nennt Entwickler, Lizenz und Quellcode.

**Oberfläche**

- Start über den Starter öffnet immer „Prüfung“; die Ansicht gilt nur noch je Browser-Tab.
- Segmentschalter gleiten nur noch bei einem echten Wechsel – beim Umschalten der Ansichten steht die Auswahl sofort.
- KPI-Leiste in den Spalten der Workbench; der Ø-Score ist als Durchschnitt aller Belege erklärt.
- Copilot-Eingabe mit integriertem Sendeknopf; Kopf-Hash im Protokoll mit eigenem Symbol.

**Updater**

- Der Neustart nach einem Update läuft unsichtbar: Unter Windows 11 übernahm Windows Terminal die Konsole, `-WindowStyle Hidden` griff dort nicht. Jetzt startet der Prozess mit `SW_HIDE`.

## v2.6.2 – 17.11.2026

**KI-Einrichtung**

- Einstellungen in der Reihenfolge Anbieter → API-Key → Modelle: Der Key lässt sich erst nach Wahl des Anbieters eingeben, die Modell-Liste erst nach gespeichertem Key wählen (der Anbieter liefert sie nur mit Key).
- Ein Knopf „Speichern“: speichert und prüft danach die Verbindung; währenddessen gesperrt, das Ergebnis steht als „Verbunden“ mit Haken daneben. Ohne Änderung bleibt der Knopf nach erfolgreichem Test gesperrt.
- Verbindungstest im Backend gegen Mehrfachklicks geschützt: Derselbe Test (Anbieter, Modell, Schlüssel) wird 15 s lang aus dem Speicher beantwortet und nie parallel ausgeführt – kein verbrauchtes Anfragelimit beim Anbieter mehr.
- Reiter „KI-Einrichtung“ mit eigenem Symbol; Ausweich-Kaskade als Stufenfolge; „Cloud-Verbrauch heute“ statt Variablenname, Tageslimit mit Fortschrittsbalken.

**Texte und Oberfläche**

- Einstellungen sprachlich gestrafft; Konfigurationsvariablen (z. B. `CLOUD_DAILY_TOKEN_LIMIT`, `HEURISTIC_FALLBACK`, `DLP_TERMS`) nicht mehr im Fließtext, sondern nur noch in Tooltips bzw. der Dokumentation. Auch Fehlerhinweise des Backends nennen keine Variablen mehr.
- „Über“ zeigt „Version 2.6.2“ und „Aktuellste Version.“ statt doppeltem „installiert“.
- Copilot ohne Verlauf mit ruhigem Einstieg und Vorschlagskarten; Scores im Prüfprotokoll nach Ampel eingefärbt.

**Sicherheit**

- Next.js 15.5.25 → 15.5.29 (u. a. GHSA-2464-fhr4-w9xw, GHSA-4jqv-mc3x-m676), PostCSS über `overrides` auf 8.5.32, `sharp` und `source-map-js` aktualisiert: `npm audit --omit=dev` meldet 0 Schwachstellen.

## v2.6.1 – 17.11.2026

**Updater und Start**

- In-App-Update mit nicht schließbarer Vollbild-Sperre (`role="alertdialog"`, Hintergrund `inert`, kein Escape, Fokus gefangen) und drei Phasen: Sicherung und Code-Stand, Neustart mit Production-Build, Warten auf die neue Version. Neu geladen wird erst, wenn das Backend die Zielversion meldet und die Oberfläche selbst wieder HTTP 200 liefert; dauert es ungewöhnlich lange, erscheint eine ruhige Anleitung für den manuellen Neustart.
- Ohne Windows-Starter (`restart_required`) kein irreführender Auto-Reload, sondern ein klarer Hinweis auf den manuellen Neustart. Meldet das Backend nach einem Verbindungsverlust eine andere Version, lädt die Oberfläche einmalig neu – nie läuft ein altes Client-Bundle gegen ein neues Backend.
- Windows-Starter ohne Flackern (`$ProgressPreference = "SilentlyContinue"` gegen den blauen Fortschrittsbalken von `Invoke-WebRequest`), mit Fenstertitel, ruhigem Statuslayout und zwei Sekunden Lesepause vor dem Schließen.

**Oberfläche**

- Neue Vektor-Bildmarke (Schild mit Prüfhaken) statt der Rastergrafik; SVG-Favicon und Apple-Touch-Icon.
- Light Mode überarbeitet: kühles Papiergrau als Grund, klarere Konturen, neutrale KPI-Kacheln, sichtbare Navigationskapsel.
- Schaltflächen ohne Klick-Versatz; Modellnamen in Produktschreibweise („Gemini 3.8 Flash“ statt Versalien).
- Einstellungen mit fünf Ein-Wort-Kategorien: KI (Modelle | Ausweich-Kaskade), Compliance, Darstellung, Verbindung (Status, Zugangsschutz, Schlüssel nur bei Bedarf), Über (Release-Status sofort beim Öffnen).
- Protokoll-Zusammenfassungen, Anbieter-Fehler und Hinweise in der Anzeige übersetzt (EN/ES); gespeichert bleiben sie unverändert, die Hash-Kette bleibt gültig.

**Qualität**

- Ungenutzte Komponenten, Konstanten und Logo-Dateien entfernt, Versionsvermerke aus Kommentaren bereinigt, Tests nach Themen benannt; Test für das Neustart-Verhalten des Release-Assistenten.

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
