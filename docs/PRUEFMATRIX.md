# Prüfmatrix typischer Rechnungen

Erwartungen je Fall für die Regressionstests in [`tests/test_pruefmatrix.py`](../tests/test_pruefmatrix.py)
(Stand v2.8.4, Regelwerk 2026.7). Alle Belege sind frei erfunden.

**Wie geprüft wird:** Jeder PDF-Fall läuft als Text-PDF in fünf Varianten:
- mit fest vorgegebener KI-Antwort mit **gefüllten** Beträgen,
- mit **leeren** Beträgen (im Cloud-Betrieb, wenn das Privacy Gateway Beträge durch Platzhalter ersetzt und das
  Modell `null` liefert; Netto, Umsatzsteuer und Gesamtbetrag stammen dann aus dem Belegtext),
- im **Regelwerk-Pfad** ohne Sprachmodell (so, wie jeder das Repository ohne API-Key erlebt),
- gefüllt und im Regelwerk-Pfad jeweils auch in **ASCII-Schreibweise** (ae/oe/ue/ss statt Umlauten).

Bei einzelnen Fällen kommt eine typische Fehlextraktion hinzu.
Die E-Rechnungs-Fälle laufen als UBL-Datensatz (EN 16931) über den deterministischen XML-Pfad ohne KI.

**Score und Ampel:** Der Score misst Pflichtangaben und Rechenwerte (Basis 100, feste Abzüge). Die Ampel zeigt
die Freigabeentscheidung.

## Text-PDF (KI-Extraktion)

| Fall | Beleg | Erwartung | Begründung |
|---|---|---|---|
| Hotel 7 % + 19 % | Übernachtung 270,00 (7 %), Frühstück 45,00 (19 %), Summe netto 315,00, zwei USt-Zeilen 18,90 + 8,55, Gesamt 342,45 | 100 · freigegeben · Summen- und Steuerprüfung bestanden | Jede USt-Zeile wird geprüft (Basis × Satz). Die USt-Summe ist die Summe der Zeilen. Netto + USt = Brutto. |
| … KI liest nur erste USt-Zeile | USt 18,90, Satz 7 % | 100 · freigegeben · Hinweis „Umsatzsteuer aus dem Belegtext übernommen“ | Nur mit der Summe aller Steuerzeilen geht die Rechnung auf. |
| Bewirtung 7 % + 19 % | Speisen 240,00 (7 %), Getränke 95,00 (19 %), Summe netto 335,00, USt 16,80 + 18,05, Gesamt 369,85 | 100 · freigegeben | Wie Hotel: Speisen 7 %, Getränke 19 %. |
| Mischsatz mit Porto | Fachbuch 80,00 (7 %), Lampe 50,00 (19 %), Porto steuerfrei 6,90, Summe netto 136,90, USt 5,60 + 9,50, Gesamt 152,00 | 100 · freigegeben · Kleinbetragsrechnung · kein § 14c | Netto enthält den steuerfreien Posten. Die Steuer wird nur auf die steuerpflichtigen Zeilen gerechnet. |
| Kleinbetragsrechnung (§ 33 UStDV) | Quittung 23,80 inkl. 19 % USt 3,80, ohne Empfänger und Rechnungsnummer | 100 · freigegeben · Kleinbetragsrechnung | Bis 250 € brutto gilt der reduzierte Katalog. Empfänger, Nummer, Netto und Steuerbetrag sind entbehrlich. |
| Kleinunternehmer (§ 19 UStG) | Logo-Entwurf 600,00, „Gemäß § 19 UStG wird keine Umsatzsteuer berechnet“ | 100 · freigegeben · kein § 14c | Die Befreiung gilt für den ganzen Beleg: Netto = Gesamtbetrag, USt 0. |
| Reverse Charge (§ 13b UStG) | Trockenbau 4.000,00 netto, Hinweis Steuerschuldnerschaft des Leistungsempfängers, keine USt | 100 · freigegeben · kein § 14c | Korrekter Ausweis ohne Umsatzsteuer. |
| Innergemeinschaftliche Lieferung | Fräsmaschine 12.500,00 an AT-Unternehmen mit UID, § 4 Nr. 1b i. V. m. § 6a UStG | 100 · freigegeben · kein § 14c | Steuerfrei, korrekt ohne USt ausgewiesen. |
| Skonto-Hinweis | 2.000,00 + 19 % = 2.380,00, „2 % Skonto (47,60 EUR)“ | 100 · freigegeben | Zahlungsbedingungen tragen keine Summen. Der Skontobetrag ist kein Rechnungsbetrag. |
| Rechnungskorrektur (negativ) | Gutschrift für Rücksendung: −100,00 netto, −19,00 USt, −119,00 gesamt | 100 · freigegeben | Negative Beträge rechnen wie positive: Netto + USt = Brutto, USt = Netto × Satz. |
| Abschlagsrechnung | 5.000,00 + 19 % = 5.950,00, Leistungszeitraum Oktober 2026 | 100 · freigegeben | Eine reguläre Rechnung über die Teilleistung. |
| Schlussrechnung | Gesamtleistung 10.000,00 + 1.900,00 = 11.900,00, abzüglich Abschlag 5.950,00, Restforderung 5.950,00 | 100 · freigegeben | Prüfgegenstand ist die Gesamtleistung (§ 14 Abs. 5 S. 2 UStG). Die Restforderung ist kein Gesamtbetrag. |
| … KI liest Restforderung als Brutto | Gesamtbetrag 5.950,00 | 100 · freigegeben · Hinweis „Gesamtbetrag aus dem Belegtext übernommen“ | Nur mit dem „Gesamtbetrag“ des Belegs geht Netto + USt = Brutto auf. |
| Hotel ohne „Pos.“ | „Übernachtung 2 Nächte x 89,00 EUR = 178,00 EUR (7 %)“, „Frühstück 2 x 15,00 EUR = 30,00 EUR (19 %)“, Kurtaxe nicht steuerbar 6,00, Summe netto 214,00, USt 12,46 + 5,70, Gesamt 232,16 | 100 · freigegeben · Leistungsbeschreibung erkannt | Positionen werden auch ohne „Pos.“ erkannt (Menge × Preis, Nächte, Stück, Bezeichnung mit Betrag). |
| Bewirtung mit Bruttopreisen | Speisen (7 %) 64,20, Getränke (19 %) 23,80, Gesamt 88,00, „Darin enthalten: Netto 7 % 60,00, MwSt 7 % 4,20; Netto 19 % 20,00, MwSt 19 % 3,80“ | 100 · freigegeben · Netto 80,00, USt 8,00 | Der Aufschlüsselungsblock wird je Steuersatz zugeordnet. |
| Kleinbetrag „inkl. USt“ | „Betrag 59,50 EUR inkl. 19 % USt“ | 100 · freigegeben · Netto 50,00, USt 9,50 | Der Bruttobetrag wird erkannt, Netto und USt werden herausgerechnet (mit Hinweis). |
| Porto als durchlaufender Posten | Papier 100,00 (19 %), Porto 4,95, Summe netto 104,95, „19 % USt auf 100,00: 19,00“, Gesamt 123,95 | 100 · freigegeben · Netto 104,95 | Netto umfasst den steuerfreien Posten. |
| … KI liest Bemessungsgrundlage als Netto | Netto 100,00 | 100 · Netto 104,95 mit Hinweis | Die „Summe netto“ des Belegs gilt; ohne sie wird Netto um die steuerfreien Posten ergänzt. |
| Echter Summenfehler | 1.000,00 + 190,00, ausgewiesen 1.290,00 | **85 · gesperrt (Nachforderung nötig)** · Summenprüfung −15 | Netto + USt ≠ Brutto. Kein Wert des Belegs gleicht das aus. |
| Echter Steuerfehler | 1.000,00 netto, „19 % USt: 180,00“, Gesamt 1.180,00 | **90 · gesperrt (Nachforderung nötig)** · Steuerprüfung −10 | USt ≠ Netto × Satz. Die Summenprüfung ist bestanden. |

## E-Rechnung (UBL, EN 16931)

| Fall | Datensatz | Erwartung |
|---|---|---|
| Hotel 7 % + 19 % | Zwei Steuergruppen (S 7 %, S 19 %) | 100 · freigegeben |
| Reverse Charge | Kategorie AE, Befreiungsgrund § 13b | 100 · freigegeben · kein § 14c |
| Innergemeinschaftliche Lieferung | Kategorie K, Käufer AT mit USt-IdNr. | 100 · freigegeben |
| Kleinunternehmer | Kategorie E, Befreiungsgrund § 19 UStG | 100 · freigegeben |
| Gutschrift | CreditNote, Typ 381 | 100 · freigegeben |

## Praxistest mit öffentlichen Testbelegen

[`scripts/praxiskorpus.py`](../scripts/praxiskorpus.py) lädt die öffentlichen Testbelege von Mustangproject (inkl.
der offiziellen ZUGFeRD-2.5.2-Beispiele), KoSIT (XRechnung-Testsuite) und EU-Kommission (EN-16931-Beispiele)
und schickt jeden Beleg ohne Sprachmodell durch den Agenten. Stand v2.8.4 (368 Belege):

- **350 geprüft, 18 abgewiesen.** Abgewiesen wurden ZUGFeRD 1.0, Bild-PDFs ohne Textlayer und Nicht-Rechnungen
  (z. B. Bestellungen); jeweils mit verständlicher Begründung.
- **0 Fehlalarme im Abgleich XML ↔ PDF-Bildteil.**
- **Beträge aus dem Bildteil:** Bei hybriden Rechnungen liest das Regelwerk Netto, Umsatzsteuer und Gesamtbetrag
  in 224 von 234 Fällen genauso wie der XML-Datensatz. 10 bleiben leer, 0 sind falsch: Versicherungen ohne
  Umsatzsteuer, steuerfreie Exporte und französische Belege.
- **Verbleibende Abzüge sind Befunde in den Testdaten.** Dazu gehören:
  - fehlendes Leistungsdatum (die KoSIT warnt dort selbst mit BR-DE-TMP-32),
  - Platzhalter-IBANs mit ungültiger Prüfziffer,
  - Test-Leitweg-IDs mit falscher Prüfziffer,
  - MINIMUM- und BASIC-WL-Profile ohne Positionen,
  - absichtlich ungültige Validator-Testdateien.

Was der Praxistest aufgedeckt hat und in v2.8.4 behoben ist:
- zwei Steuerzeilen mit gleichem Satz,
- Rabatt- und Zuschlagszeilen,
- die Steuertabelle der ZUGFeRD-Visualisierung,
- Netto, Steuer und Brutto in einer Zeile,
- englische Rechnungen,
- Kontokennungen ohne IBAN-Form,
- mehrere oder verschmolzene Bankverbindungen im Bildteil,
- die Rundungstoleranz nach BR-CO-17,
- Rechnungslayouts ohne „An:“ und ohne „Rechnungsnummer“-Bezeichner.

Alle diese Fälle sind als nachgebaute Zeilenmuster in [`tests/test_praxiskorpus.py`](../tests/test_praxiskorpus.py) abgesichert.

Weitere offizielle Testbelege der KoSIT und des Mustangproject: [`tests/test_official_samples.py`](../tests/test_official_samples.py),
Herkunft und Lizenz in [`tests/fixtures/NOTICE`](../tests/fixtures/NOTICE).
