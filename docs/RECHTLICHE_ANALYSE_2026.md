# Rechtliche und regulatorische Analyse (Stand 2026)

Rechtsnormen für die automatisierte Dokumentenprüfung in Deutschland und der EU –
EU AI Act, Umsatzsteuerrecht und E-Rechnung, GoBD sowie Datenschutz – und ihre
Übersetzung in Architekturentscheidungen des Enterprise Compliance Agent.

> Technische Einordnung, keine Rechts- oder Steuerberatung. Die Quellen zu den
> einzelnen Angaben stehen in [`RECHTSQUELLEN.md`](RECHTSQUELLEN.md); wie das
> System die Anforderungen umsetzt, beschreibt der Abschnitt
> [Anmerkungen aus der Umsetzung](#anmerkungen-aus-der-umsetzung-stand-v28-november-2026).

## Inhalt

1. [Paradigmenwechsel in der automatisierten Dokumentenverarbeitung](#1-paradigmenwechsel-in-der-automatisierten-dokumentenverarbeitung)
2. [Der EU AI Act: Produktsicherheit und Grundrechtsschutz](#2-der-eu-ai-act-produktsicherheit-und-grundrechtsschutz)
3. [Steuerrecht und E-Rechnung: die Digitalisierung des Vorsteuerabzugs](#3-steuerrecht-und-e-rechnung-die-digitalisierung-des-vorsteuerabzugs)
4. [Datenschutz, Cloud-Inferenz und Drittlandtransfer](#4-datenschutz-cloud-inferenz-und-drittlandtransfer)
5. [Architektonische Synthese](#5-architektonische-synthese)
6. [Anmerkungen aus der Umsetzung](#anmerkungen-aus-der-umsetzung-stand-v28-november-2026)

---

## 1. Paradigmenwechsel in der automatisierten Dokumentenverarbeitung

Architektur, Implementierung und Betrieb von Systemen zur automatisierten
Dokumentenprüfung durchlaufen 2025 und 2026 eine Zäsur. Die Digitalisierung
geschäftskritischer Prozesse – insbesondere im Personalwesen (Recruiting), im
Finanz- und Rechnungswesen sowie in der Vertragsanalyse – trifft auf die
Konvergenz dreier Regulierungsregime. Die automatisierte Extraktion,
Klassifizierung und Bewertung von Dokumenteninhalten mit Large Language Models
(LLMs) und Optical Character Recognition (OCR) bewegt sich damit im Zentrum des
europäischen Daten- und Technologierechts.

Eine isolierte Betrachtung einzelner Rechtsgebiete greift zu kurz. Die
Extraktion von Rechnungs- oder Bewerbungsdaten durch eine in der Cloud
betriebene KI berührt gleichzeitig

- die Produktsicherheits- und Grundrechtsdogmatik der Verordnung (EU) 2024/1689
  (EU AI Act),
- die umsatzsteuerlichen Dokumentationspflichten nach dem
  Wachstumschancengesetz und dem Vierten Bürokratieentlastungsgesetz (BEG IV)
  sowie
- die Anforderungen der Datenschutz-Grundverordnung (DSGVO) an die
  Rechtmäßigkeit der Verarbeitung und an den Drittlandtransfer nach der
  Schrems-II-Rechtsprechung.

Die folgende Analyse ordnet den Rechtsstand 2025/2026 in diesen drei Domänen ein
und leitet daraus architektonische Leitplanken für das Software-Engineering ab.

## 2. Der EU AI Act: Produktsicherheit und Grundrechtsschutz

Mit dem Inkrafttreten der Verordnung (EU) 2024/1689 am **1. August 2024** hat
der europäische Gesetzgeber den ersten umfassenden, risikobasierten
Rechtsrahmen für Künstliche Intelligenz geschaffen. Das Regelwerk überführt
ethische Grundsätze in sanktionsbewehrtes Produktsicherheitsrecht: Bußgelder
reichen bis zu 35 Mio. Euro oder 7 % des weltweiten Jahresumsatzes bei
verbotenen Praktiken und bis zu 15 Mio. Euro oder 3 % bei Verstößen gegen die
Pflichten für Hochrisiko-Systeme. Die Pflichten skalieren mit dem
Gefährdungspotenzial des jeweiligen KI-Systems.

### 2.1 Anbieter (Art. 16) und Betreiber (Art. 26)

Der AI Act trennt die Wirtschaftsakteure entlang der KI-Wertschöpfungskette
strikt in **Anbieter** (Provider) und **Betreiber** (Deployer). Diese
Unterscheidung bestimmt die gesamte Compliance-Strategie, insbesondere wenn
Dokumente in sensiblen Bereichen wie dem Personalwesen (Hochrisiko-KI nach
Anhang III) automatisiert geprüft werden.

**Anbieter** ist nach Art. 3, wer ein KI-System entwickelt oder entwickeln lässt
und es unter eigenem Namen oder eigener Marke in Verkehr bringt. Er trägt die
primäre Last für die Systemsicherheit: Nach Art. 16 i. V. m. Art. 17–21 muss er
vor dem Markteintritt ein Qualitätsmanagementsystem (Art. 17) mit
Daten-Governance (Art. 10), Risikominderung und Testszenarien einrichten, eine
technische Dokumentation nach Anhang IV erstellen, ein
Konformitätsbewertungsverfahren durchlaufen, das System in der EU-Datenbank
registrieren und es nach dem Inverkehrbringen beobachten (Post-Market
Monitoring, Art. 72). Er gewährleistet Genauigkeit, Robustheit und
Cybersicherheit (Art. 15).

**Betreiber** ist nach Art. 26, wer ein KI-System unter eigener Verantwortung im
Rahmen einer beruflichen oder gewerblichen Tätigkeit einsetzt. Ein deutsches
Unternehmen, das ein lizenziertes KI-Werkzeug zur Auswertung von Lebensläufen
nutzt, handelt als Betreiber. Seine Pflichten ergänzen die des Anbieters und
überführen die Systemsicherheit in eine sichere Anwendung:

- **Art. 26 Abs. 1:** Nutzung strikt nach der Gebrauchsanweisung des Anbieters.
- **Art. 26 Abs. 4:** Die Eingabedaten, über die der Betreiber die Kontrolle
  ausübt, müssen für den Zweck relevant und ausreichend repräsentativ sein.
  Werden verzerrte (biased) Dokumente eingespeist, haftet der Betreiber für die
  resultierende Diskriminierung.
- **Art. 26 Abs. 5:** Laufende Überwachung. Treten Risiken für Gesundheit,
  Sicherheit oder Grundrechte auf, ist das System zu stoppen und sind Anbieter
  und Marktüberwachungsbehörde zu informieren – in Deutschland das bei der
  Bundesnetzagentur angesiedelte Koordinierungs- und Kompetenzzentrum für die
  KI-Verordnung (KoKIVO).
- **Art. 26 Abs. 7:** Vor dem Einsatz eines Hochrisiko-KI-Systems am
  Arbeitsplatz sind Arbeitnehmervertretungen und betroffene Beschäftigte zu
  unterrichten.

| Akteur | Definition nach EU AI Act | Kernpflichten bei Hochrisiko-Systemen |
|---|---|---|
| **Anbieter** (Provider) | Entwickelt ein KI-System und bringt es unter eigenem Namen oder eigener Marke in Verkehr | Art. 16: Qualitätsmanagementsystem (Art. 17), technische Dokumentation (Art. 11), Konformitätsbewertung, CE-Kennzeichnung, Post-Market Monitoring (Art. 72) |
| **Betreiber** (Deployer) | Nutzt das KI-System in eigener Verantwortung für berufliche oder gewerbliche Zwecke | Art. 26: Nutzung gemäß Gebrauchsanweisung, Relevanz der Eingabedaten, Systemüberwachung, Meldung bei Risiken, Information der Beschäftigten |

Zusätzlich verlangt **Art. 27** von bestimmten Betreibern vor dem ersten Einsatz
eine **Grundrechte-Folgenabschätzung** (Fundamental Rights Impact Assessment,
FRIA). Sie trifft Einrichtungen des öffentlichen Rechts, private Erbringer
öffentlicher Dienstleistungen sowie Betreiber von Systemen zur
Kreditwürdigkeitsprüfung und zur Risikobewertung in der Lebens- und
Krankenversicherung. Die Abschätzung bewertet schriftlich die Einsatzprozesse,
die betroffenen Personengruppen (insbesondere vulnerable Gruppen) und die
technischen und organisatorischen Schutzmaßnahmen.

### 2.2 Zeitplan nach dem „Digital Omnibus“ und Anhang III

Die Pflichten gelten gestaffelt. Die Verbote unannehmbarer Praktiken (Art. 5)
und die Pflicht zur KI-Kompetenz (Art. 4) gelten seit dem **2. Februar 2025**,
die Regeln für KI-Modelle mit allgemeinem Verwendungszweck (GPAI) seit dem
**2. August 2025**. Weil die harmonisierten Normen der europäischen
Normungsorganisationen (CEN/CENELEC) für Hochrisiko-Systeme nicht rechtzeitig
vorlagen, legte die EU-Kommission Ende 2025 das Gesetzgebungspaket „Digital
Omnibus“ vor.

Die daraus hervorgegangene Änderungsverordnung **VO (EU) 2026/1744** trat nach
der politischen Einigung im Mai 2026 am **27. Juli 2026** in Kraft und
verschiebt die Stichtage für Hochrisiko-Systeme. Der allgemeine
Anwendungsbeginn – insbesondere die Transparenz- und Kennzeichnungspflichten
für KI-generierte Inhalte und Chatbots nach Art. 50 – bleibt der
**2. August 2026**.

Für die automatisierte Dokumentenprüfung ist **Anhang III Nr. 4** maßgeblich:
KI-Systeme im Bereich „Beschäftigung, Personalmanagement und Zugang zur
Selbstständigkeit“. Software, die Bewerbungen analysiert, filtert, Kandidaten
bewertet oder Entscheidungen über Arbeitsverhältnisse vorbereitet, fällt
originär in diese Hochrisikoklasse. Die Konformitäts-, Dokumentations- und
Aufsichtspflichten (einschließlich der Folgenabschätzung nach Art. 27) für
eigenständige Anhang-III-Systeme gelten nach dem Omnibus ab dem
**2. Dezember 2027** statt ab August 2026; für Systeme, die als
Sicherheitsbauteile in regulierte Produkte eingebettet sind (Anhang I), ab dem
**2. August 2028**.

| Stichtag | Regelungsgegenstand | Betroffene Akteure |
|---|---|---|
| 02.02.2025 | Verbotene Praktiken (Art. 5) und KI-Kompetenz (Art. 4) | Alle Anbieter und Betreiber |
| 02.08.2025 | Pflichten für GPAI-Modelle (Art. 53 ff.) | Anbieter von Basismodellen |
| 02.08.2026 | Allgemeine Anwendbarkeit, Transparenz (Art. 50), Marktüberwachung | Anbieter und Betreiber |
| 02.12.2027 | Hochrisiko-Systeme nach Anhang III (z. B. Recruiting-KI, Scoring) | Anbieter (Art. 16) und Betreiber (Art. 26, 27) |
| 02.08.2028 | Hochrisiko-Systeme nach Anhang I (eingebettete Sicherheitsbauteile) | Produkthersteller und Anbieter |

**Art. 6 Abs. 3** eröffnet eine für die Dokumentenverarbeitung bedeutsame
Ausnahme: Ein System, das nominell unter Anhang III fällt, gilt nicht als
Hochrisiko-KI, wenn es kein erhebliches Risiko für die Grundrechte birgt –
insbesondere, wenn es nur eine „enge verfahrenstechnische Aufgabe“ oder eine
vorbereitende Aufgabe erfüllt. Extrahiert ein System lediglich Stammdaten aus
einer Bewerbung oder überführt es unstrukturierte Rechnungsdaten in ein
strukturiertes Format, ohne Wertung, Profiling oder Personalentscheidung, kann
das Unternehmen die Einstufung durch eine dokumentierte Risikobewertung
abwenden. Die Ausnahme ist eng auszulegen und greift nie, wenn Profiling
natürlicher Personen stattfindet.

### 2.3 Automatische Protokollierung (Art. 12) und menschliche Aufsicht (Art. 14)

Um maschinelle Entscheidungen rechtlich handhabbar zu machen, verlangt der AI
Act zwei Architekturkonzepte: **Rückverfolgbarkeit** und **menschliche
Eingriffsmöglichkeit**.

**Art. 12** verpflichtet Hochrisiko-Systeme, Ereignisse über ihren gesamten
Lebenszyklus automatisch zu protokollieren. Die Protokolle müssen die
Funktionsweise im Hinblick auf Risiken rückwirkend rekonstruierbar machen:
Zeitraum der Nutzung, Eingabedaten (soweit datenschutzrechtlich zulässig) und
die an der Überprüfung beteiligten Personen. Nach **Art. 26 Abs. 6** bewahrt der
Betreiber diese Protokolle, soweit sie seiner Kontrolle unterliegen,
mindestens sechs Monate fälschungssicher auf. Für die Architektur folgt
daraus eine Anbindung der KI-Inferenz an einen unveränderbaren Speicher
(WORM-Prinzip), der Versionen, Konfidenzwerte und Modellentscheidungen
revisionssicher festhält.

**Art. 14** verlangt menschliche Aufsicht (Human Oversight). Ein KI-System, das
tief in Grundrechte eingreift, darf keine letzte Entscheidung vollautonom
treffen. Die beaufsichtigenden Personen müssen den Betrieb nachvollziehen,
Ausgaben kritisch bewerten, dem „Automation Bias“ (der Tendenz, maschinellen
Ergebnissen unreflektiert zu vertrauen) entgegenwirken und das System
übersteuern oder anhalten können (Art. 14 Abs. 4 lit. d und e). In der
Dokumentenprüfung bedeutet das Workflows wie **Human-in-the-Loop** (die KI
bereitet vor, der Mensch gibt stets frei) oder **Human-on-the-Loop** (die KI
arbeitet selbstständig, der Mensch greift stichprobenartig ein).

## 3. Steuerrecht und E-Rechnung: die Digitalisierung des Vorsteuerabzugs

Während der AI Act die Algorithmen reguliert, bestimmt das Umsatzsteuerrecht
die formalen und inhaltlichen Kriterien der geprüften Dokumente. Mit dem
Wachstumschancengesetz (März 2024) und dem BEG IV geht Deutschland zur
strukturierten elektronischen Rechnung über – mit erheblichen Folgen für
OCR- und KI-Extraktionssysteme.

### 3.1 Pflichtangaben (§ 14 Abs. 4 UStG) und Kleinbetragsrechnung (§ 33 UStDV)

Der Vorsteuerabzug nach § 15 UStG setzt eine formell und materiell
ordnungsgemäße Rechnung voraus. Die Merkmale, die ein System fehlerfrei
extrahieren und prüfen muss, nennt § 14 Abs. 4 UStG abschließend: vollständiger
Name und Anschrift des leistenden Unternehmers und des Leistungsempfängers,
Steuernummer oder USt-IdNr. des Leistenden, Ausstellungsdatum, fortlaufende
Rechnungsnummer, Menge und handelsübliche Bezeichnung der Lieferung bzw. Art
und Umfang der Leistung, Zeitpunkt der Lieferung oder Leistung, das nach
Steuersätzen aufgeschlüsselte Entgelt sowie der gesondert ausgewiesene
Steuerbetrag. Fehlt ein Merkmal oder ist es unrichtig, ist der Vorsteuerabzug
zu versagen. Die Rechtsprechung des EuGH, der der BFH folgt, erlaubt zwar die
rückwirkende Rechnungsberichtigung, doch jeder Fehler birgt Liquiditäts- und
Zinsrisiken in der Betriebsprüfung.

Eine verfahrensrechtliche Erleichterung bietet **§ 33 UStDV** für
Kleinbetragsrechnungen bis **250 Euro brutto**: Es genügen Name und Anschrift
des Leistenden, Ausstellungsdatum, Menge und Art der Leistung, das Bruttoentgelt
und der Steuersatz; Leistungsempfänger, Steuernummer und der getrennte Ausweis
von Netto und Steuer entfallen. Eine automatisierte Prüfung muss ihre
Regelmatrix daher am extrahierten Bruttobetrag ausrichten.

| Rechtsgrundlage | Anwendungsbereich | Pflichtangaben (Auswahl) | Folge für die Extraktion |
|---|---|---|---|
| § 14 Abs. 4 UStG | Rechnungen über 250 € | Namen und Anschriften beider Parteien, Steuernummer bzw. USt-IdNr., Rechnungsnummer, Netto, Steuerbetrag, Steuersatz | Strikte Prüfung aller Felder; bei Mängeln Übergabe an die menschliche Klärung |
| § 33 UStDV | Kleinbetragsrechnungen bis 250 € | Name und Anschrift des Leistenden, Datum, Art der Leistung, Bruttobetrag, Steuersatz; kein Empfänger nötig | Reduzierter Pflichtkatalog; fehlende Empfängerdaten sind kein Mangel |

### 3.2 Unrichtiger Steuerausweis (§ 14c UStG)

Ein erhebliches Risiko ist der unrichtige oder unberechtigte Steuerausweis.
Weist ein Unternehmer mehr Steuer aus, als er schuldet (z. B. 19 % statt 7 %),
schuldet er nach § 14c Abs. 1 UStG auch den Mehrbetrag. Diese auf Art. 203 der
Mehrwertsteuer-Systemrichtlinie (MwStSystRL) beruhende Gefährdungshaftung
schützt das Steueraufkommen vor einem unberechtigten Vorsteuerabzug des
Empfängers.

Der EuGH hat diese Haftung mit dem Urteil **P-GmbH (C-378/21) vom
8. Dezember 2022** eingeschränkt: Eine Steuerschuld aus unrichtigem Ausweis
entsteht nicht, wenn die Rechnung ausschließlich an Endverbraucher gerichtet
ist – sie sind nicht zum Vorsteuerabzug berechtigt, das Steueraufkommen ist
also nicht gefährdet. Das BMF hat dies mit Schreiben vom **27. Februar 2024**
(III C 2 – S 7282/19/10001 :002) umgesetzt und die frühere, strengere
BFH-Rechtsprechung (Urteil vom 13.12.2018, V R 4/18) insoweit für überholt
erklärt.

Die Folgerechtsprechung (EuGH, Urteil vom 1. August 2025; BFH, Beschluss vom
19. März 2025, XI R 4/22) knüpft die Befreiung an den Ausschluss der
„Infektionswirkung“: Es muss feststehen, dass die Rechnung nicht an einen
vorsteuerabzugsberechtigten Unternehmer gelangt ist. Bei Kleinbetragsrechnungen
an unbekannte Laufkundschaft sind Schätzungen des Endverbraucher-Anteils
zulässig, wenn sie transparent, verhältnismäßig und überprüfbar sind. Für
ERP- und Dokumentensysteme werden die Unterscheidung zwischen B2B und B2C und
die Dokumentation des Kundenstatus damit zu steuerlichen Anforderungen.

### 3.3 E-Rechnungspflicht nach EN 16931 seit dem 1. Januar 2025

Die tiefgreifendste Änderung ist die obligatorische E-Rechnung im inländischen
B2B-Verkehr, eingeführt durch das Wachstumschancengesetz und ausgelegt im
BMF-Schreiben vom **15. Oktober 2024**. Der Gesetzgeber löst sich von der
optischen Dokumentenprüfung und setzt auf den strukturierten,
maschinenlesbaren Datensatz.

Seit dem **1. Januar 2025** ist eine „elektronische Rechnung“ (§ 14 Abs. 1
Satz 3 UStG) ausschließlich eine Rechnung, die in einem strukturierten
elektronischen Format ausgestellt, übermittelt und empfangen wird, das eine
elektronische Verarbeitung ermöglicht und der Norm **EN 16931** entspricht.
Klassische PDF-Rechnungen per E-Mail gelten als „sonstige Rechnungen“ und
stehen Papierrechnungen gleich. In Deutschland qualifizieren sich vor allem
**XRechnung** und **ZUGFeRD** ab Version 2.0.1 (ohne die Profile MINIMUM und
BASIC WL).

Die Umstellung verläuft gestaffelt:

- **Empfangspflicht seit 01.01.2025:** Alle inländischen Unternehmer – auch
  Kleinunternehmer nach § 19 UStG – müssen E-Rechnungen nach EN 16931 empfangen
  und archivieren können. Übergangsfristen gibt es dafür nicht.
- **Ausstellungspflicht ab 2027/2028:** Vom 1. Januar 2025 bis zum
  31. Dezember 2026 dürfen Unternehmen weiterhin PDF-Rechnungen versenden, wenn
  der Empfänger zustimmt. Ab dem **1. Januar 2027** gilt die Pflicht für
  Unternehmen mit einem Vorjahresumsatz über 800.000 Euro, ab dem
  **1. Januar 2028** für den gesamten B2B-Bereich.

Für hybride Formate wie ZUGFeRD – ein PDF-Bildteil mit eingebettetem
XML-Datensatz – enthält das BMF-Schreiben vom 15. Oktober 2024 eine zentrale
Klarstellung: Weichen beide Teile voneinander ab, ist für Vorsteuerabzug und
Steuerfestsetzung **der XML-Datensatz maßgeblich** (Rz. 36). Eine KI-gestützte
Prüfung darf sich bei E-Rechnungen deshalb nicht auf die visuelle PDF-Schicht
verlassen, sondern muss den XML-Datensatz nach EN 16931 auswerten.

### 3.4 Aufbewahrungsfristen (BEG IV) und Verfahrensdokumentation

Die Aufbewahrung von E-Rechnungen und Prüfprotokollen folgt den GoBD
(Grundsätze zur ordnungsmäßigen Führung und Aufbewahrung von Büchern,
Aufzeichnungen und Unterlagen in elektronischer Form sowie zum Datenzugriff).
Das BEG IV hat mit Wirkung zum **1. Januar 2025** die Frist für Buchungsbelege
und Rechnungen (§ 147 Abs. 3 AO, § 14b Abs. 1 UStG) von zehn auf **acht Jahre**
verkürzt – auch für Belege, deren Zehnjahresfrist zu diesem Stichtag noch lief.

Daraus folgt ein häufig übersehenes Paradoxon: Rechnungsdatensätze dürfen nach
acht Jahren gelöscht werden, Jahresabschlüsse, Handelsbücher und – für
IT-Systeme entscheidend – die **Verfahrensdokumentation** bleiben **zehn Jahre**
aufbewahrungspflichtig.

Die GoBD verlangen für elektronische Dokumentenmanagementsysteme eine
Verfahrensdokumentation, die das organisatorisch und technisch gewollte
Verfahren beschreibt. Sie gliedert sich in vier Teile: allgemeine Beschreibung,
Anwenderdokumentation, technische Systemdokumentation und
Betriebsdokumentation (einschließlich IT-Sicherheits- und Kontrollmaßnahmen).
Um die Unveränderbarkeit historischer Buchungen über bis zu zehn Jahre
nachzuweisen, muss sie Systemzustände, Software-Updates und Änderungen der
Prüfalgorithmen historisieren. Der Prüfpfad (Audit Trail) von der empfangenen
XML-Datei über den maschinellen Prüfvermerk bis zur Buchung muss über die
gesamte Aufbewahrungsdauer maschinell auswertbar bleiben. Eine fehlende oder
unzureichende Dokumentation des E-Rechnungs-Workflows kann ein formeller
GoBD-Mangel sein (zur Gewichtung siehe die Anmerkungen am Ende).

## 4. Datenschutz, Cloud-Inferenz und Drittlandtransfer

Die semantische Extraktion aus unstrukturierten Dokumenten (Verträge,
Lebensläufe, Freitextrechnungen) übernehmen zunehmend LLMs statt regelbasierter
Systeme. Weil die Inferenz viel Rechenleistung braucht, greifen Unternehmen auf
Cloud-APIs (etwa von OpenAI, Anthropic oder Google) zurück, die überwiegend von
US-Unternehmen betrieben werden. Enthalten die Dokumente personenbezogene
Daten, eröffnet das die Anforderungen der DSGVO.

### 4.1 Pseudonymisierung und Anonymisierung (Art. 4 Nr. 5 DSGVO)

Entwickler versuchen häufig, Namen und Identifikatoren vor dem Versand an die
LLM-API zu „anonymisieren“. Die DSGVO verlangt jedoch eine klare Unterscheidung
mit weitreichenden Folgen.

Eine **Anonymisierung** im Sinne von Erwägungsgrund 26 liegt nur vor, wenn die
betroffene Person unter keinen Umständen mehr identifiziert werden kann;
anonyme Daten fallen nicht unter die DSGVO. Die **Pseudonymisierung** ist in
Art. 4 Nr. 5 DSGVO definiert als Verarbeitung, nach der die Daten ohne
zusätzliche Informationen (Schlüssel oder Zuordnungstabelle) keiner Person
mehr zugeordnet werden können. Pseudonymisierte Daten bleiben
personenbezogen und unterliegen der DSGVO.

Die Abgrenzung folgt dem Konzept der **relativen Identifizierbarkeit**. Der EuGH
hat in den Entscheidungen *Breyer* (C-582/14, dynamische IP-Adressen) und
*EDSB/SRB* (C-413/23 P, September 2025) festgehalten, dass der Personenbezug aus
der Sicht des jeweiligen Empfängers zu beurteilen ist. Übermittelt ein
Unternehmen pseudonymisierte Daten an einen Dritten und behält den Schlüssel
unter eigener Kontrolle, ohne dass der Empfänger rechtliche oder praktische
Mittel hat, ihn zu erlangen, können die Daten aus Sicht des Empfängers als
anonym gelten.

Bei generativen KI-Modellen ist das komplex. Der Europäische
Datenschutzausschuss (EDSA) hat in seiner **Stellungnahme 28/2024** zu
KI-Modellen betont, dass LLMs durch „Regurgitation“ (das unbeabsichtigte
Wiedergeben von Trainingsdaten) und durch Rückschlüsse aus dem semantischen
Kontext die Identifizierbarkeit deutlich erhöhen. Ein einfaches Ersetzen von
Namen (etwa per Regex) führt bei unstrukturierten Texten selten zu echter
Anonymität, weil der verbleibende Kontext (Berufsstationen, Vokabular,
stilistische Merkmale) eine Re-Identifizierung erlauben kann. Der EDSA
betrachtet solche Daten deshalb in der Regel weiterhin als pseudonymisiert.

### 4.2 Drittlandtransfer: EDSA-Empfehlungen 01/2020 und flüchtige Pseudonymisierung

Weil pseudonymisierte Prompts personenbezogen bleiben, löst ihre Übermittlung
an eine in den USA betriebene API die Regeln des **Kapitels V der DSGVO**
(Übermittlung in Drittländer) aus. Seit dem Schrems-II-Urteil des EuGH
(C-311/18, 16. Juli 2020) müssen Unternehmen ein angemessenes Schutzniveau
nachweisen.

Seit Juli 2023 besteht mit dem **EU-US Data Privacy Framework** ein
Angemessenheitsbeschluss für zertifizierte US-Unternehmen. Wegen möglicher
Anfechtungen („Schrems III“) und weil nicht alle Unterauftragnehmer
zertifiziert sind, stützen viele Organisationen Transfers zusätzlich auf
Standardvertragsklauseln (SCC) mit dokumentiertem Transfer Impact Assessment
(TIA).

Hier greifen die **EDSA-Empfehlungen 01/2020** zu ergänzenden Maßnahmen:
Vertragliche Zusicherungen genügen nicht, wenn das Recht des Drittlands (etwa
CLOUD Act oder FISA Section 702) Behörden einen unverhältnismäßigen Zugriff
erlaubt. Der Verantwortliche muss **wirksame ergänzende technische Maßnahmen**
treffen. Der verbreitete Lösungsansatz entspricht dem **Anwendungsfall 2**
(Übermittlung pseudonymisierter Daten): Die Übermittlung ist vertretbar, wenn
die Daten vor dem Verlassen des EWR so pseudonymisiert werden, dass der
Empfänger sie nicht re-identifizieren kann, und die Zuordnung ausschließlich
beim Datenexporteur in der EU verbleibt.

Für LLM-APIs bedeutet das einen **Pseudonymisierungs-Proxy auf der eigenen
Seite**: Bevor ein Dokument an die API geht, ersetzt eine lokale Komponente
sensible Entitäten (Namen, IBANs, Sozialversicherungsnummern) durch
strukturerhaltende Platzhalter – per Named Entity Recognition (NER),
deterministischer Tokenisierung oder formaterhaltender Verschlüsselung (FPE).
Die Inferenz läuft auf den Platzhaltern; erst nach der Rückkehr der Antwort
setzt der Proxy die Klartextwerte wieder ein. Selbst bei einer behördlichen
Anordnung könnte der Anbieter nur die Platzhalter herausgeben.

### 4.3 Rechtsgrundlage und Auftragsverarbeitungsvertrag (Art. 28 DSGVO)

Weder die Pseudonymisierung noch eine vertragliche Zusicherung flüchtiger
Verarbeitung („Zero Data Retention“, ZDR) heben die Anwendbarkeit der DSGVO
auf. Bei ZDR sichert der Anbieter zu, Prompts nicht dauerhaft zu speichern und
nicht für das Training zu verwenden. Das senkt das Risiko und unterstützt
Speicherbegrenzung und Datenminimierung (Art. 5 Abs. 1 lit. c und e DSGVO).
Die Übermittlung und die Verarbeitung im Arbeitsspeicher des Anbieters bleiben
aber eine Verarbeitung nach Art. 4 Nr. 2 DSGVO. Sie braucht eine Rechtsgrundlage
nach **Art. 6 DSGVO** und – bei besonderen Kategorien, etwa Gesundheitsdaten in
Personalunterlagen – eine Ausnahme nach **Art. 9 DSGVO**.

Der API-Anbieter handelt bei der Inferenz als **Auftragsverarbeiter**; ein
Vertrag nach **Art. 28 DSGVO** ist zwingend. Die ZDR-Zusicherung gehört als
dokumentierte Weisung (Art. 28 Abs. 3 lit. a DSGVO) in diesen Vertrag, nicht nur
in Marketingunterlagen. Der Vertrag regelt auch Unterauftragsverarbeiter und
macht ZDR als technisch-organisatorische Maßnahme nach **Art. 32 DSGVO** im
Verarbeitungsverzeichnis nachweisbar.

## 5. Architektonische Synthese

Die gleichzeitige Einhaltung von AI Act, Steuerrecht und Datenschutz verlangt
**Compliance by Design**: Die Anforderungen gehören in Code und Infrastruktur,
nicht in eine nachträgliche Prüfung.

| Norm | Rechtliche Anforderung | Architekturmuster |
|---|---|---|
| EU AI Act Art. 12 (Protokollierung) und GoBD (Verfahrensdokumentation) | Nachweisbarkeit von KI-Entscheidungen (mind. 6 Monate) und Unveränderbarkeit steuerlicher Prüfpfade (bis 10 Jahre) | **Einheitliches Compliance-Ledger (WORM):** append-only, manipulationssicher; je Prüfung Prompt-Version, Modellversion, Hash des Originals, Konfidenz und Zeitstempel |
| EU AI Act Art. 14 (menschliche Aufsicht) | Verhinderung des Automation Bias; Übersteuerung bei Grundrechtseingriffen | **Human-in-the-Loop-Gateway:** KI-Ergebnisse schreiben nie direkt ins ERP; unsichere Ergebnisse und Hochrisiko-Fälle nach Anhang III gehen in eine asynchrone Warteschlange zur Freigabe bzw. Übersteuerung durch Fachpersonal |
| § 14 Abs. 4 UStG und EN 16931 | Strukturierte E-Rechnung für den Vorsteuerabzug seit 01.01.2025; Vorrang der XML-Daten | **XML-first-Verarbeitung:** bei hybriden Formaten den XML-Datensatz auswerten statt die PDF-Schicht per OCR; Abweichungen zugunsten des XML auflösen; Regelmatrix am Betrag ausrichten (§ 33 UStDV) |
| DSGVO Art. 4 Nr. 5, Art. 28 und EDSA 01/2020 (Schrems II) | Absicherung des Drittlandtransfers pseudonymisierter Daten an Cloud-LLM-APIs | **Pseudonymisierungs-Proxy:** Identifikatoren vor dem Verlassen der eigenen Infrastruktur durch Platzhalter ersetzen; Inferenz nur auf Platzhaltern (mit AVV und ZDR); Re-Identifizierung erst nach der Rückkehr |

Der „Digital Omnibus“ (VO (EU) 2026/1744) verschafft Unternehmen für die
Zertifizierungspflichten eigenständiger Hochrisiko-Systeme (Anhang III) bis zum
**2. Dezember 2027** Zeit. Die operativen Grundlagen – Empfangsbereitschaft für
E-Rechnungen nach EN 16931 seit dem **1. Januar 2025**, GoBD-konforme
Historisierung in der Verfahrensdokumentation und die Abschirmung
personenbezogener Daten vor dem Transfer an Cloud-Anbieter – dulden dagegen
keinen Aufschub. Rechtliche Vorgaben lassen sich am besten als präzise
technische Spezifikation verstehen und umsetzen.

---

## Anmerkungen aus der Umsetzung (Stand v2.8, November 2026)

Abgleich der Analyse mit dem implementierten Stand des Enterprise Compliance
Agent. Der Analysetext oben bleibt inhaltlich unverändert; die folgenden Punkte
präzisieren ihn.

1. **Folgen einer fehlenden Verfahrensdokumentation.** Nach GoBD Rz. 155 ist
   eine fehlende oder ungenügende Verfahrensdokumentation nur dann ein
   formeller Mangel mit sachlichem Gewicht, der die Beweiskraft der Buchführung
   (§ 158 AO) entfallen lassen und eine Schätzung (§ 162 AO) eröffnen kann,
   wenn Nachvollziehbarkeit und Nachprüfbarkeit beeinträchtigt sind. Ein
   Automatismus „fehlt, also Schätzung“ besteht nicht. Umgesetzt:
   `app/procedural_doc.py` erzeugt einen Entwurf nach Rz. 153 aus dem
   Systemzustand.
2. **Rückausnahme Finanzsektor.** Für Kreditinstitute,
   Versicherungsunternehmen und Wertpapierinstitute gilt für Buchungsbelege
   wieder die Frist von zehn Jahren (Gesetz zur Modernisierung und
   Digitalisierung der Schwarzarbeitsbekämpfung, Bundesrat 19.12.2025).
   Umgesetzt in `app/retention.py`, Scorecard und Zertifikat.
3. **Fristbeginn.** Die Frist beginnt mit dem Schluss des Kalenderjahres, in dem
   der Beleg entstanden ist (§ 147 Abs. 4 AO), und läuft nicht ab, solange die
   Festsetzungsfrist noch offen ist (§ 147 Abs. 3 S. 5 AO).
4. **Pseudonymisierung.** Das Privacy Gateway arbeitet regelbasiert im Backend
   (kein NER-Modell, keine formaterhaltende Verschlüsselung); das Mapping bleibt
   flüchtig im Arbeitsspeicher. Der in Abschnitt 4.2 beschriebene Proxy mit NER
   und FPE ist das Zielbild, nicht der aktuelle Stand.
5. **Menschliche Aufsicht.** Art. 14 Abs. 4 lit. d AI Act ist als begründete
   Übersteuerung der Risikoeinstufung umgesetzt; Prüfer-Einträge sind im Ledger
   Ed25519-signiert. Die Signatur stammt vom System und belegt Integrität, nicht
   die Identität der Prüfperson.
6. **XML-Prüfung.** Der Agent wertet den XML-Datensatz hybrider und reiner
   E-Rechnungen deterministisch aus (Profil, Pflichtfelder, Summenregeln,
   Abgleich mit dem PDF-Bildteil). Eine vollständige Validierung gegen XSD und
   Schematron leistet er nicht; für die formale Annahme beim Empfänger zählt
   der KoSIT-Validator.
7. **Asynchrone Verarbeitung und Ausfallsicherheit.** Analysen laufen seit v2.5
   als Hintergrund-Jobs mit Warteschlange, Fortschritt und Abbruch. Fällt die
   gesamte KI-Kaskade aus, schließt ein deterministisches Regelwerk die Prüfung
   ab und kennzeichnet das Ergebnis in Oberfläche und Ledger; die Freigabe
   bleibt in jedem Fall bei der Prüfperson.
