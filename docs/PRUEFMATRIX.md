# Prüfmatrix typischer Rechnungen

Erwartungen je Fall für die Regressionstests in [`tests/test_pruefmatrix.py`](../tests/test_pruefmatrix.py)
(Stand v2.8.3, Regelwerk 2026.6). Alle Belege sind frei erfunden.

**Wie geprüft wird:** Jeder PDF-Fall läuft als Text-PDF mit fest vorgegebener KI-Antwort, und zwar in zwei
Varianten: mit **gefüllten** Beträgen und mit **leeren** Beträgen. Leere Beträge entstehen im Cloud-Betrieb, wenn
das Privacy Gateway Beträge durch Platzhalter ersetzt und das Modell `null` liefert. Netto, Umsatzsteuer und
Gesamtbetrag stammen dann aus dem Belegtext. Bei einzelnen Fällen kommt eine typische Fehlextraktion hinzu.
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

Weitere offizielle Testbelege der KoSIT und des Mustangproject: [`tests/test_official_samples.py`](../tests/test_official_samples.py),
Herkunft und Lizenz in [`tests/fixtures/NOTICE`](../tests/fixtures/NOTICE).
