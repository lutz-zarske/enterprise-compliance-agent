"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";

export type Locale = "de" | "en" | "es";
export const LOCALE_STORAGE_KEY = "eca-lang";

export const LOCALE_TAG: Record<Locale, string> = {
  de: "de-DE",
  en: "en-GB",
  es: "es-ES",
};

let currentLocale: Locale = "de";

export function getActiveLocale(): Locale {
  if (typeof window !== "undefined") {
    try {
      const raw = window.localStorage.getItem(LOCALE_STORAGE_KEY);
      if (raw === "de" || raw === "en" || raw === "es") {
        currentLocale = raw;
      }
    } catch {
      /* ignore */
    }
  }
  return currentLocale;
}

export function setActiveLocale(next: Locale): void {
  currentLocale = next;
  if (typeof document !== "undefined") {
    document.documentElement.lang = next;
  }
}

/** Typsichere Dreifach-Auswahl (DE / EN / ES) fuer Inline-Texte und Attribute. */
export function tr(de: string, en: string, es: string, locale: Locale = getActiveLocale()): string {
  if (locale === "en") return en;
  if (locale === "es") return es;
  return de;
}

// ---------------------------------------------------------------------------
// Uebersetzung dynamischer Backend-Texte (Scorecard, Checks, Ledger, E-Invoice)
// ---------------------------------------------------------------------------

const EXACT_EN: Record<string, string> = {
  "Zur Auszahlung freigegeben": "Approved for payment",
  "Freigabe empfohlen — Prüfung ohne Befund": "Approval recommended — audit without findings",
  "Freigabe gesperrt — Nachforderung nötig": "Approval blocked — supplier correction required",
  "Freigabe gesperrt — Konformitätsbewertung nach Art. 43 EU AI Act nachweisen":
    "Approval blocked — conformity assessment under Art. 43 EU AI Act required",
  "Freigabe unter Vorbehalt — Abweichung zwischen XML und PDF klären (XML maßgeblich)":
    "Conditional approval — clarify discrepancy between XML and PDF (XML prevails)",
  "Freigabe unter Vorbehalt — Nachbesserung empfohlen": "Conditional approval — remediation recommended",
  "Vollständig verkehrsfähig & konform": "Fully compliant & valid",
  "Nachbesserung erforderlich": "Remediation required",
  "Revisionssperre / schwerer Rechtsverstoß": "Audit lock / severe compliance violation",
  "Gedeckelt auf 59: Hochrisiko-KI (Anhang III) ohne Konformitätsnachweis":
    "Capped at 59: High-risk AI (Annex III) without conformity evidence",
  "Gedeckelt auf 20: Verbotene Praktik nach Art. 5 EU AI Act":
    "Capped at 20: Prohibited practice under Art. 5 EU AI Act",

  // Check labels
  "Anwendungsbereich § 14 UStG": "Scope of Sec. 14 German VAT Act (§ 14 UStG)",
  "Name und Anschrift des leistenden Unternehmers": "Full name and address of the supplier",
  "Name und Anschrift des Leistungsempfängers": "Full name and address of the recipient",
  "Steuernummer oder USt-IdNr. des Ausstellers": "Supplier tax number or VAT ID",
  "Ausstellungsdatum": "Invoice issue date",
  "Fortlaufende, einmalige Rechnungsnummer": "Sequential, unique invoice number",
  "Menge und Art der Lieferung / Umfang und Art der Leistung": "Quantity and nature of goods / scope and type of services",
  "Zeitpunkt der Lieferung oder Leistung": "Date or period of supply / performance",
  "Nach Steuersätzen aufgeschlüsseltes Entgelt (netto)": "Net consideration broken down by tax rate",
  "Anzuwendender Steuersatz oder Hinweis auf Steuerbefreiung": "Applicable VAT rate or tax exemption notice",
  "Auf das Entgelt entfallender Steuerbetrag": "Tax amount payable on the consideration",
  "Strukturierte E-Rechnung (EN 16931: XRechnung / ZUGFeRD)": "Structured E-Invoice (EN 16931: XRechnung / ZUGFeRD)",
  "Abgleich XML-Datensatz ↔ PDF-Bildteil": "Cross-check XML dataset ↔ visual PDF",
  "Leitweg-ID des öffentlichen Auftraggebers (BT-10)": "Public sector routing ID (Leitweg-ID, BT-10)",
  "IBAN-Prüfziffer (ISO 13616, MOD-97-10)": "IBAN check digit (ISO 13616, MOD-97-10)",
  "Zulässiger Umsatzsteuersatz (19 % / 7 % / 0 %)": "Valid statutory VAT rate (19% / 7% / 0%)",
  "Netto + Umsatzsteuer = Brutto": "Net + VAT = Gross total",
  "Netto + Umsatzsteuer = Brutto (BT-109 + BT-110 = BT-112)": "Net + VAT = Gross total (BT-109 + BT-110 = BT-112)",
  "Umsatzsteuer = Netto x Steuersatz": "VAT amount = Net × VAT rate",
  "Umsatzsteuer = Bemessungsgrundlage x Steuersatz (je Satz)": "VAT amount = Tax base × VAT rate (per rate)",
  "Verbotene KI-Praktik": "Prohibited AI practice",
  "Hochrisiko-KI-System": "High-risk AI system",
  "KI mit Transparenzpflichten": "AI system with transparency obligations",
  "KI-System mit minimalem Risiko": "Minimal-risk AI system",
  "Kein KI-System beschrieben": "No AI system described",
  "Besondere Kategorien personenbezogener Daten": "Special categories of personal data",
  "Amtliche Kennnummern natürlicher Personen": "Official identification numbers of natural persons",
  "Personenbezogene Daten maskiert": "Personal data masked",

  // Headlines & common details
  "Nicht einschlägig": "Not applicable",
  "0 PII-Funde": "0 PII findings",
  "Keine PII erkannt.": "No PII detected.",
  "Pflichtangabe fehlt.": "Mandatory disclosure missing.",
  "Keine IBAN im Dokument.": "No IBAN in document.",
  "IBAN valide · MwSt. korrekt berechnet": "IBAN valid · VAT calculated correctly",
  "IBAN ungültig · MwSt.-Fehler": "IBAN invalid · VAT calculation error",
  "IBAN valide · MwSt.-Fehler": "IBAN valid · VAT calculation error",
  "IBAN ungültig · MwSt. korrekt berechnet": "IBAN invalid · VAT calculated correctly",
  "IBAN valide": "IBAN valid",
  "IBAN ungültig": "IBAN invalid",
  "Hochrisiko (Anhang III)": "High-Risk (Annex III)",
  "Begrenztes Risiko (Art. 50)": "Limited Risk (Art. 50)",
  "Minimales Risiko": "Minimal Risk",
  "Verbotene Praktik (Art. 5)": "Prohibited Practice (Art. 5)",
  "Weder Steuernummer noch USt-IdNr. angegeben – kein Vorsteuerabzug (§ 15 UStG).":
    "Neither tax number nor VAT ID stated — no input VAT deduction (§ 15 UStG).",
  "Prüfziffer ungültig – Zahlungsziel nicht verifizierbar (Betrugsrisiko).":
    "Invalid check digit — payment destination unverifiable (fraud risk).",
  "Keine Rechnung – Pflichtangaben nach § 14 Abs. 4 UStG nicht einschlägig.":
    "Not an invoice — mandatory disclosures under § 14 (4) UStG not applicable.",

  // Risk notes
  "Ohne vollständige Anschrift des Ausstellers ist die Rechnung nicht ordnungsgemäß und der Vorsteuerabzug nach § 15 UStG gefährdet.":
    "Without the supplier's complete address, the invoice is non-compliant and input VAT deduction (§ 15 UStG) is at risk.",
  "Fehlt die Anschrift des Leistungsempfängers, kann das Finanzamt den Vorsteuerabzug nach § 15 UStG versagen.":
    "If the recipient's address is missing, the tax office may deny input VAT deduction under § 15 UStG.",
  "Ohne Steuernummer oder USt-IdNr. entfällt der Vorsteuerabzug nach § 15 UStG.":
    "Without a tax number or VAT ID, input VAT deduction under § 15 UStG is denied.",
  "Ohne Ausstellungsdatum lässt sich der Zeitpunkt des Vorsteuerabzugs nicht bestimmen.":
    "Without an issue date, the period for input VAT deduction cannot be determined.",
  "Ohne eindeutige Rechnungsnummer ist die Rechnung nicht ordnungsgemäß, und Doppelzahlungen bleiben unerkannt.":
    "Without a unique invoice number, the invoice is non-compliant and duplicate payments may go undetected.",
  "Ohne hinreichend konkrete Leistungsbeschreibung kann der Vorsteuerabzug versagt werden.":
    "Without a sufficiently specific service description, input VAT deduction may be denied.",
  "Ohne Leistungszeitpunkt lässt sich die Steuerentstehung nicht zuordnen; der Hinweis „Leistungsdatum entspricht Rechnungsdatum“ genügt.":
    "Without a performance date, tax accrual cannot be assigned; a note that performance date equals invoice date suffices.",
  "Ohne ausgewiesenes Nettoentgelt ist der Steuerbetrag nicht nachprüfbar.":
    "Without a stated net amount, the tax amount cannot be verified.",
  "Ohne Steuersatz oder Befreiungshinweis bleibt offen, ob die Steuer zutreffend berechnet ist.":
    "Without a tax rate or exemption notice, it remains unclear whether tax was calculated properly.",
  "Als Vorsteuer abziehbar ist höchstens die gesondert ausgewiesene Steuer; ohne Steuerbetrag entfällt der Abzug.":
    "Only separately stated tax is deductible as input VAT; without a tax amount, no deduction is possible.",
  "Ab 2027 bzw. 2028 erfüllt eine reine PDF-Rechnung im inländischen B2B-Verkehr die Rechnungspflicht nicht mehr.":
    "From 2027/2028 onwards, a plain PDF invoice no longer fulfills domestic B2B e-invoicing obligations.",
  "Eine IBAN mit falscher Prüfziffer ist ein typisches Merkmal von Zahlungsumleitungsbetrug – vor Zahlung auf bekanntem Weg verifizieren.":
    "An IBAN with an invalid check digit is a typical indicator of payment diversion fraud — verify via a known channel before payment.",
  "Bei zu niedrigem Steuerausweis schuldet der Lieferant die gesetzliche Steuer, der Empfänger kann aber nur den ausgewiesenen Betrag als Vorsteuer abziehen.":
    "If VAT is understated, the supplier owes the statutory tax, while the buyer may only deduct the stated amount.",
  "Rechenfehler zwischen Netto, Steuer und Brutto führen zu falsch gebuchter Vorsteuer und Zahlungsdifferenzen.":
    "Calculation errors between net, VAT, and gross lead to misbooked input tax and payment discrepancies.",
  "Zu hoch ausgewiesene Steuer schuldet der Aussteller nach § 14c Abs. 1 UStG, zu niedrig ausgewiesene ist nur in ausgewiesener Höhe abziehbar.":
    "Overstated VAT is owed by the issuer under § 14c (1) UStG; understated VAT is only deductible up to the stated amount.",
  "Hochrisiko-KI nach Anhang III darf ab dem 02.12.2027 nur mit Konformitätsbewertung betrieben werden; Verstöße kosten bis zu 15 Mio. € oder 3 % des Jahresumsatzes (Art. 99 Abs. 4).":
    "High-risk AI under Annex III may only operate with a conformity assessment from 02.12.2027; violations carry fines up to €15M or 3% of annual turnover (Art. 99 (4)).",
  "Bei Rechnungen ausschließlich an Endverbraucher entsteht keine Steuerschuld aus § 14c UStG (EuGH, Urteil vom 08.12.2022, C-378/21; BMF-Schreiben vom 27.02.2024).":
    "For invoices issued exclusively to final consumers, no tax liability arises under § 14c UStG (ECJ C-378/21; BMF letter of 27.02.2024).",

  // GDPR & Business Terms
  "Name einer natürlichen Person": "Name of a natural person",
  "Kontaktdaten (E-Mail / Telefon)": "Contact details (email / phone)",
  "Anschrift / Standortdaten": "Address / location data",
  "Bankverbindung (IBAN / BIC)": "Bank account (IBAN / BIC)",
  "Steuer-ID / USt-IdNr.": "Tax ID / VAT ID",
  "Personalausweis- / Passnummer": "ID card / passport number",
  "Sozialversicherungsnummer": "Social security number",
  "Geburtsdatum": "Date of birth",
  "Gesundheitsdaten (Art. 9 DSGVO)": "Health data (Art. 9 GDPR)",
  "Biometrische Daten (Art. 9 DSGVO)": "Biometric data (Art. 9 GDPR)",
  "Politische / religiöse Überzeugung / Gewerkschaft (Art. 9 DSGVO)": "Political / religious belief / union (Art. 9 GDPR)",
  "Rechnungsnummer": "Invoice number",
  "Rechnungsdatum": "Invoice date",
  "Rechnungstyp": "Invoice type",
  "Währung": "Currency",
  "Käufer-Referenz / Leitweg-ID": "Buyer reference / Routing ID",
  "Spezifikationskennung": "Specification ID",
  "Name des Verkäufers": "Seller name",
  "USt-IdNr. des Verkäufers": "Seller VAT ID",
  "Steuernummer des Verkäufers": "Seller tax number",
  "Name des Käufers": "Buyer name",
  "IBAN des Zahlungsempfängers": "Payee IBAN",
  "Summe der Rechnungspositionen (netto)": "Sum of invoice line net amounts",
  "Rechnungsgesamtbetrag ohne Umsatzsteuer": "Invoice total amount without VAT",
  "Rechnungsgesamtbetrag der Umsatzsteuer": "Invoice total VAT amount",
  "Rechnungsgesamtbetrag mit Umsatzsteuer": "Invoice total amount with VAT",
  "Fälliger Zahlungsbetrag": "Amount due for payment",

  // E-Invoice Business Terms & Visual Checks (app/schemas.py & app/extractors/einvoice.py)
  "Käuferreferenz / Leitweg-ID": "Buyer reference / Leitweg-ID",
  "Elektronische Adresse des Verkäufers": "Seller electronic address",
  "Elektronische Adresse des Käufers": "Buyer electronic address",
  "Summe netto": "Net total",
  "Umsatzsteuer gesamt": "Total VAT",
  "Rechnungsgesamtbetrag (brutto)": "Invoice total amount (gross)",
  "Rechnungsgesamtbetrag": "Invoice total amount",
  "Zahlbetrag": "Amount due",
  "Steuersatz": "VAT rate",
  "Unbekannt (BT-24 fehlt)": "Unknown (BT-24 missing)",
  "Unbekannt": "Unknown",
  "Elektronische Adresse des Käufers ist eine Leitweg-ID (Schema 0204).": "Buyer electronic address is a Leitweg-ID (scheme 0204).",
  "Käuferreferenz (BT-10) ist eine gültige Leitweg-ID.": "Buyer reference (BT-10) is a valid Leitweg-ID.",

  // EU AI Act Annex III labels (app/schemas.py)
  "Anhang III Nr. 1 - Biometrie": "Annex III No. 1 – Biometrics",
  "Anhang III Nr. 2 - Kritische Infrastruktur": "Annex III No. 2 – Critical infrastructure",
  "Anhang III Nr. 3 - Allgemeine und berufliche Bildung": "Annex III No. 3 – Education & vocational training",
  "Anhang III Nr. 4 - Beschäftigung und Personalmanagement": "Annex III No. 4 – Employment & worker management",
  "Anhang III Nr. 5 - Wesentliche Dienste, u. a. Kreditwürdigkeitsprüfung": "Annex III No. 5 – Essential services (incl. creditworthiness)",
  "Anhang III Nr. 6 - Strafverfolgung": "Annex III No. 6 – Law enforcement",
  "Anhang III Nr. 7 - Migration, Asyl und Grenzkontrolle": "Annex III No. 7 – Migration, asylum & border control",
  "Anhang III Nr. 8 - Rechtspflege und demokratische Prozesse": "Annex III No. 8 – Justice & democratic processes",

  // Exact backend PII_CATEGORY_LABELS & raw enum keys (app/schemas.py)
  "Gesundheitsdaten (Art. 9 Abs. 1 DSGVO)": "Health data (Art. 9(1) GDPR)",
  "Religions- oder Weltanschauungszugehörigkeit (Art. 9 Abs. 1 DSGVO)": "Religious or philosophical beliefs (Art. 9(1) GDPR)",
  "Rassische oder ethnische Herkunft (Art. 9 Abs. 1 DSGVO)": "Racial or ethnic origin (Art. 9(1) GDPR)",
  "Politische Meinung (Art. 9 Abs. 1 DSGVO)": "Political opinions (Art. 9(1) GDPR)",
  "Gewerkschaftszugehörigkeit (Art. 9 Abs. 1 DSGVO)": "Trade union membership (Art. 9(1) GDPR)",
  "Biometrische Daten (Art. 9 Abs. 1 DSGVO)": "Biometric data (Art. 9(1) GDPR)",
  "Genetische Daten (Art. 9 Abs. 1 DSGVO)": "Genetic data (Art. 9(1) GDPR)",
  "Sexualleben oder sexuelle Orientierung (Art. 9 Abs. 1 DSGVO)": "Sex life or sexual orientation (Art. 9(1) GDPR)",
  "Strafrechtliche Verurteilungen und Straftaten (Art. 10 DSGVO)": "Criminal convictions and offences (Art. 10 GDPR)",
  "Ausweis- oder Passnummer": "ID document or passport number",
  "Steueridentifikationsnummer": "Tax identification number",
  "Bankverbindung (IBAN/BIC)": "Bank account (IBAN/BIC)",
  "Anschrift": "Address",
  "Kontaktdaten (E-Mail, Telefon)": "Contact details (email, phone)",
  "Sonstige personenbezogene Daten": "Other personal data",
  health_data: "Health data",
  religious_belief: "Religious belief",
  racial_or_ethnic_origin: "Ethnic origin",
  political_opinion: "Political opinion",
  trade_union_membership: "Trade union",
  biometric_data: "Biometric data",
  genetic_data: "Genetic data",
  sex_life_or_orientation: "Sex life / orientation",
  criminal_offence_data: "Criminal offences (Art. 10)",
  id_document_number: "ID / Passport",
  social_security_number: "Social security no.",
  tax_identification_number: "Tax ID",
  bank_account: "Bank account (IBAN/BIC)",
  date_of_birth: "Date of birth",
  name: "Name",
  address: "Address",
  contact_data: "Contact data",
  other_personal_data: "Other PII",

  // Scoring details, risk notes & compliance notes (app/scoring.py)
  "Entbehrlich bei Kleinbetragsrechnungen bis 250 EUR (§ 33 UStDV).": "Not required for small-amount invoices up to 250 EUR (§ 33 UStDV).",
  "Bei Kleinbetragsrechnungen genügt das Entgelt inkl. Steuer (§ 33 UStDV).": "For small-amount invoices, gross amount including VAT suffices (§ 33 UStDV).",
  "Keine Beträge prüfbar": "No amounts verifiable",
  "Empfangspflicht für E-Rechnungen seit 01.01.2025. Bei hybriden Formaten ist der XML-Teil führend; abweichende Angaben im Bildteil können als eigene Rechnung gelten (BMF-Schreiben vom 15.10.2024, Rz. 36, präzisiert durch BMF-Schreiben vom 15.10.2025).":
    "Mandatory e-invoice receipt from 01 Jan 2025. For hybrid invoices, the XML dataset governs; conflicting visual values may constitute a separate invoice (BMF 15 Oct 2024, para. 36 & 15 Oct 2025).",
  "Reines PDF ohne eingebettetes XML: im inländischen B2B-Verkehr seit 01.01.2025 eine „sonstige Rechnung“. Zulässig in der Übergangsfrist bis 31.12.2026 (bei Vorjahresumsatz bis 800.000 EUR bis 31.12.2027), danach Ausstellungspflicht für E-Rechnungen. Kein Punktabzug.":
    "Plain PDF without embedded XML: an 'other invoice' in domestic B2B since 01 Jan 2025. Permissible during transitional period until 31 Dec 2026 (until 31 Dec 2027 if prior-year turnover ≤ 800,000 EUR); mandatory e-invoicing thereafter. No score deduction.",
  "Reines PDF ohne eingebettetes XML: im inländischen B2B-Verkehr seit 01.01.2025 eine „sonstige Rechnung“. Zulässig in der Übergangsfrist bis 31.12.2026 (bei Vorjahresumsatz bis 800.000 EUR bis 31.12.2027), danach Ausstellungspflicht für E-Rechnungen. Kein Punktabzug. Öffentliche Auftraggeber verlangen eine E-Rechnung (für den Bund § 3 ERechV, für Länder und Kommunen Landesrecht).":
    "Plain PDF without embedded XML: an 'other invoice' in domestic B2B since 01 Jan 2025 (transitional period until 31 Dec 2026/2027). Public authority buyers require an e-invoice (§ 3 ERechV / state law). No score deduction.",
  "Hinweis auf eingebettetes XML (ZUGFeRD/Factur-X/XRechnung), der Datensatz ist aber nicht lesbar. Rechtlich maßgeblich ist bei hybriden Rechnungen der strukturierte XML-Teil; bewertet wird hier der Bildteil. Kein Punktabzug.":
    "Embedded XML indicator found (ZUGFeRD/Factur-X/XRechnung), but the dataset is unreadable. Visually audited instead; the structured XML prevails legally. No score deduction.",
  "Verstöße gegen EN-16931-Geschäftsregeln führen beim Empfänger regelmäßig zur Zurückweisung durch den Validator.":
    "EN 16931 business-rule violations routinely result in rejection by the recipient's validator.",
  "MINIMUM- und BASIC-WL-Datensätze erfüllen die Rechnungspflicht nach Ablauf der Übergangsfrist nicht; bis dahin ist der Bildteil die Rechnung.":
    "MINIMUM and BASIC WL datasets do not fulfill mandatory e-invoicing after the transitional period; until then the visual PDF is the invoice.",
  "Einsatz ist unionsrechtlich untersagt (seit 02.02.2025).": "Deployment is prohibited under EU law (since 02 Feb 2025).",
  "Kennzeichnungs- und Informationspflichten nach Art. 50 sicherstellen.": "Ensure transparency labelling and disclosure obligations under Art. 50.",
  "Keine spezifischen Pflichten; Maßnahmen zur KI-Kompetenz nach Art. 4 ergreifen.": "No specific obligations; implement AI literacy measures under Art. 4.",
  "Art. 6 Abs. 3: Ausnahme möglich bei eng begrenzten oder rein vorbereitenden Aufgaben ohne Profiling – Profiling natürlicher Personen ist immer Hochrisiko. Das System eskaliert konservativ auf Hochrisiko. Die Pflichten für Anhang-III-Systeme gelten nach der Änderung durch VO (EU) 2026/1744 ab dem 02.12.2027.":
    "Art. 6(3): derogation possible only for narrowly defined or preparatory tasks without profiling — profiling natural persons is always High-Risk. Conservative High-Risk escalation applied. Annex III duties apply from 02 Dec 2027 (Reg. (EU) 2026/1744).",
  "Rechtsgrundlage nach Art. 9 Abs. 2 DSGVO ist im Dokument nicht belegt; Zugriff beschränken und Erforderlichkeit prüfen.":
    "Legal basis under Art. 9(2) GDPR is not documented; restrict access and verify necessity.",
  "Verarbeitung nur bei gesetzlicher Grundlage; Speicherbegrenzung (Art. 5 Abs. 1 lit. e).":
    "Process only with statutory legal basis; enforce storage limitation (Art. 5(1)(e)).",
  "Maßgeblich ist der XML-Datensatz; ein abweichender Bildteil kann als weitere Rechnung gewertet werden und bei höherem Steuerausweis eine Steuerschuld nach § 14c UStG auslösen.":
    "The XML dataset prevails; a diverging visual PDF may be treated as an extra invoice and trigger tax liability under § 14c UStG.",
  "Ohne gültige Leitweg-ID kann die Eingangsplattform des Auftraggebers die Rechnung nicht zuordnen und weist sie zurück; die Zahlung verzögert sich.":
    "Without a valid Leitweg-ID, the contracting authority's portal rejects the invoice and delays payment.",
  "Verbotene Praktiken sind seit 02.02.2025 untersagt; das Bußgeld reicht bis 35 Mio. € oder 7 % des weltweiten Jahresumsatzes (Art. 99 Abs. 3).":
    "Prohibited practices are banned since 02 Feb 2025; fines reach €35M or 7% of global annual turnover (Art. 99(3)).",
  "Verstöße gegen die Transparenzpflichten nach Art. 50 können mit bis zu 15 Mio. € oder 3 % des Jahresumsatzes geahndet werden.":
    "Breaches of Art. 50 transparency obligations carry fines up to €15M or 3% of annual turnover.",
  "Verarbeitung besonderer Kategorien ohne Rechtsgrundlage nach Art. 9 Abs. 2 kann mit bis zu 20 Mio. € oder 4 % des Jahresumsatzes geahndet werden (Art. 83 Abs. 5 DSGVO).":
    "Processing special categories without Art. 9(2) legal basis carries fines up to €20M or 4% of annual turnover (Art. 83(5) GDPR).",
  "Amtliche Kennnummern sind besonders missbrauchsanfällig (Identitätsdiebstahl) und dürfen nur mit Rechtsgrundlage gespeichert werden.":
    "Official identifiers carry high identity-theft risk and may only be stored with a legal basis.",

  // Jobs, Copilot steps, Heuristics, Local AI & Release messages
  "Text-Layer & XML-Vorrang": "Text Layer & XML Primacy",
  "PII-Scanner & Privacy Vault": "PII Scanner & Privacy Vault",
  "§ 14 UStG Extraktion & Prüfung": "§ 14 VAT Extraction & Audit",
  "EU AI Act, Scorecard & Ledger": "EU AI Act, Scorecard & Ledger",
  "Regelbasiertes Referenz-Audit – KI nicht verfügbar": "Rule-Based Reference Audit – AI Unavailable",
  "Regelbasiertes Referenz-Audit – KI temporär überlastet": "Rule-Based Reference Audit – AI Unavailable",
  "Beleg archiviert": "Document archived",
  "Beleg aus dem Archiv geholt": "Document restored from archive",
  "Belegstellen und Prüfergebnis aufbereiten": "Preparing document excerpts and audit findings",
  "Personenbezogene Daten pseudonymisieren (Privacy Vault)": "Pseudonymizing personal data (Privacy Vault)",
  "Regelwerk antwortet (KI nicht verfügbar)": "Rule engine answering (AI unavailable)",
  "Antwort re-identifizieren": "Re-identifying response",
  "Antwort formulieren": "Formulating response",
  "Ollama läuft.": "Ollama is running.",
  "Ollama ist installiert, läuft aber nicht.": "Ollama is installed but stopped.",
  "Ollama lief bereits.": "Ollama was already running.",
  "Ollama lief nicht.": "Ollama was not running.",
  "Ollama läuft jetzt (Flash Attention, 8-Bit-KV-Cache).": "Ollama is now running (Flash Attention, 8-bit KV cache).",
  "Ollama ist gestoppt – der Grafikspeicher ist wieder frei.": "Ollama stopped — GPU memory freed.",
  "Im Container läuft Ollama als eigener Dienst (docker compose) – Start und Stopp dort.": "In container deployments, Ollama runs as a separate docker compose service.",
  "Im Container wird Ollama über docker compose gestartet.": "In containers, Ollama is started via docker compose.",
  "Im Container wird Ollama über docker compose gestoppt.": "In containers, Ollama is stopped via docker compose.",
  "Ollama ist auf diesem Rechner nicht installiert (ollama.com).": "Ollama is not installed on this machine (ollama.com).",
  "Keine lokale KI gefunden. Ollama (ollama.com) installieren, dann erscheint hier der Startknopf.": "No local AI found. Install Ollama (ollama.com) to enable local start controls.",
  "Keine Git-Arbeitskopie (z. B. Docker-Image) - Update über ein neues Image.": "Not a Git checkout (e.g. Docker image) — update via container image.",
  "Keine Git-Arbeitskopie - Update über ein neues Image.": "Not a Git checkout — update via container image.",
  "Ein Update läuft bereits.": "An update is already running.",
  "Lokale Änderungen vorhanden - Update abgebrochen.": "Local changes present — update aborted.",
};

const EXACT_ES: Record<string, string> = {
  "Zur Auszahlung freigegeben": "Aprobado para el pago",
  "Freigabe empfohlen — Prüfung ohne Befund": "Aprobación recomendada — auditoría sin hallazgos",
  "Freigabe gesperrt — Nachforderung nötig": "Aprobación bloqueada — rectificación requerida",
  "Freigabe gesperrt — Konformitätsbewertung nach Art. 43 EU AI Act nachweisen":
    "Aprobación bloqueada — acreditar evaluación de conformidad según el art. 43 del Reglamento de IA",
  "Freigabe unter Vorbehalt — Abweichung zwischen XML und PDF klären (XML maßgeblich)":
    "Aprobación condicional — aclarar discrepancia entre XML y PDF (prevalece el XML)",
  "Freigabe unter Vorbehalt — Nachbesserung empfohlen": "Aprobación condicional — se recomienda subsanación",
  "Vollständig verkehrsfähig & konform": "Totalmente conforme y válido",
  "Nachbesserung erforderlich": "Subsanación necesaria",
  "Revisionssperre / schwerer Rechtsverstoß": "Bloqueo de auditoría / infracción grave",
  "Gedeckelt auf 59: Hochrisiko-KI (Anhang III) ohne Konformitätsnachweis":
    "Limitado a 59: IA de alto riesgo (Anexo III) sin certificado de conformidad",
  "Gedeckelt auf 20: Verbotene Praktik nach Art. 5 EU AI Act":
    "Limitado a 20: Práctica prohibida según el art. 5 del Reglamento de IA",

  // Check labels
  "Anwendungsbereich § 14 UStG": "Ámbito de aplicación del § 14 UStG (Ley de IVA)",
  "Name und Anschrift des leistenden Unternehmers": "Nombre completo y dirección del emisor",
  "Name und Anschrift des Leistungsempfängers": "Nombre completo y dirección del destinatario",
  "Steuernummer oder USt-IdNr. des Ausstellers": "Número fiscal o NIF-IVA del emisor",
  "Ausstellungsdatum": "Fecha de expedición",
  "Fortlaufende, einmalige Rechnungsnummer": "Número de factura único y correlativo",
  "Menge und Art der Lieferung / Umfang und Art der Leistung": "Cantidad y naturaleza de los bienes / alcance del servicio",
  "Zeitpunkt der Lieferung oder Leistung": "Fecha o período de entrega / prestación",
  "Nach Steuersätzen aufgeschlüsseltes Entgelt (netto)": "Base imponible neta desglosada por tipo impositivo",
  "Anzuwendender Steuersatz oder Hinweis auf Steuerbefreiung": "Tipo impositivo aplicable o mención de exención",
  "Auf das Entgelt entfallender Steuerbetrag": "Cuota tributaria correspondiente",
  "Strukturierte E-Rechnung (EN 16931: XRechnung / ZUGFeRD)": "Factura electrónica estructurada (EN 16931: XRechnung / ZUGFeRD)",
  "Abgleich XML-Datensatz ↔ PDF-Bildteil": "Verificación cruzada XML ↔ representación PDF",
  "Leitweg-ID des öffentlichen Auftraggebers (BT-10)": "ID de enrutamiento del sector público (Leitweg-ID, BT-10)",
  "IBAN-Prüfziffer (ISO 13616, MOD-97-10)": "Dígito de control IBAN (ISO 13616, MOD-97-10)",
  "Zulässiger Umsatzsteuersatz (19 % / 7 % / 0 %)": "Tipo de IVA legalmente válido (19 % / 7 % / 0 %)",
  "Netto + Umsatzsteuer = Brutto": "Neto + IVA = Total bruto",
  "Netto + Umsatzsteuer = Brutto (BT-109 + BT-110 = BT-112)": "Neto + IVA = Total bruto (BT-109 + BT-110 = BT-112)",
  "Umsatzsteuer = Netto x Steuersatz": "Cuota de IVA = Neto × Tipo impositivo",
  "Umsatzsteuer = Bemessungsgrundlage x Steuersatz (je Satz)": "Cuota de IVA = Base imponible × Tipo (por tramo)",
  "Verbotene KI-Praktik": "Práctica de IA prohibida",
  "Hochrisiko-KI-System": "Sistema de IA de alto riesgo",
  "KI mit Transparenzpflichten": "Sistema de IA con obligaciones de transparencia",
  "KI-System mit minimalem Risiko": "Sistema de IA de riesgo mínimo",
  "Kein KI-System beschrieben": "No se describe ningún sistema de IA",
  "Besondere Kategorien personenbezogener Daten": "Categorías especiales de datos personales",
  "Amtliche Kennnummern natürlicher Personen": "Números de identificación oficial de personas físicas",
  "Personenbezogene Daten maskiert": "Datos personales enmascarados",

  // Headlines & common details
  "Nicht einschlägig": "No aplicable",
  "0 PII-Funde": "0 hallazgos PII",
  "Keine PII erkannt.": "No se detectaron datos personales.",
  "Pflichtangabe fehlt.": "Falta dato obligatorio.",
  "Keine IBAN im Dokument.": "Sin IBAN en el documento.",
  "IBAN valide · MwSt. korrekt berechnet": "IBAN válido · IVA calculado correctamente",
  "IBAN ungültig · MwSt.-Fehler": "IBAN inválido · Error de cálculo de IVA",
  "IBAN valide · MwSt.-Fehler": "IBAN válido · Error de cálculo de IVA",
  "IBAN ungültig · MwSt. korrekt berechnet": "IBAN inválido · IVA calculado correctamente",
  "IBAN valide": "IBAN válido",
  "IBAN ungültig": "IBAN inválido",
  "Hochrisiko (Anhang III)": "Alto riesgo (Anexo III)",
  "Begrenztes Risiko (Art. 50)": "Riesgo limitado (Art. 50)",
  "Minimales Risiko": "Riesgo mínimo",
  "Verbotene Praktik (Art. 5)": "Práctica prohibida (Art. 5)",
  "Weder Steuernummer noch USt-IdNr. angegeben – kein Vorsteuerabzug (§ 15 UStG).":
    "No se indica número fiscal ni NIF-IVA — sin derecho a deducción del IVA soportado (§ 15 UStG).",
  "Prüfziffer ungültig – Zahlungsziel nicht verifizierbar (Betrugsrisiko).":
    "Dígito de control inválido — destino de pago no verificable (riesgo de fraude).",
  "Keine Rechnung – Pflichtangaben nach § 14 Abs. 4 UStG nicht einschlägig.":
    "No es una factura — los requisitos del § 14 (4) UStG no son aplicables.",

  // Risk notes
  "Ohne vollständige Anschrift des Ausstellers ist die Rechnung nicht ordnungsgemäß und der Vorsteuerabzug nach § 15 UStG gefährdet.":
    "Sin la dirección completa del emisor, la factura no es válida y peligra la deducción del IVA soportado (§ 15 UStG).",
  "Fehlt die Anschrift des Leistungsempfängers, kann das Finanzamt den Vorsteuerabzug nach § 15 UStG versagen.":
    "Si falta la dirección del destinatario, la administración tributaria puede denegar la deducción del IVA (§ 15 UStG).",
  "Ohne Steuernummer oder USt-IdNr. entfällt der Vorsteuerabzug nach § 15 UStG.":
    "Sin número fiscal o NIF-IVA no procede la deducción del IVA soportado según el § 15 UStG.",
  "Ohne Ausstellungsdatum lässt sich der Zeitpunkt des Vorsteuerabzugs nicht bestimmen.":
    "Sin fecha de expedición no puede determinarse el período de deducción del IVA.",
  "Ohne eindeutige Rechnungsnummer ist die Rechnung nicht ordnungsgemäß, und Doppelzahlungen bleiben unerkannt.":
    "Sin un número de factura único, la factura es irregular y pueden producirse pagos duplicados.",
  "Ohne hinreichend konkrete Leistungsbeschreibung kann der Vorsteuerabzug versagt werden.":
    "Sin una descripción suficientemente concreta del servicio, puede denegarse la deducción del IVA.",
  "Ohne Leistungszeitpunkt lässt sich die Steuerentstehung nicht zuordnen; der Hinweis „Leistungsdatum entspricht Rechnungsdatum“ genügt.":
    "Sin fecha de prestación no puede asignarse el devengo; basta indicar que coincide con la fecha de factura.",
  "Ohne ausgewiesenes Nettoentgelt ist der Steuerbetrag nicht nachprüfbar.":
    "Sin base imponible neta desglosada, la cuota tributaria no es verificable.",
  "Ohne Steuersatz oder Befreiungshinweis bleibt offen, ob die Steuer zutreffend berechnet ist.":
    "Sin tipo impositivo o nota de exención, no puede verificarse el cálculo del impuesto.",
  "Als Vorsteuer abziehbar ist höchstens die gesondert ausgewiesene Steuer; ohne Steuerbetrag entfällt der Abzug.":
    "Solo es deducible el impuesto desglosado expresamente; sin cuota tributaria no hay deducción.",
  "Ab 2027 bzw. 2028 erfüllt eine reine PDF-Rechnung im inländischen B2B-Verkehr die Rechnungspflicht nicht mehr.":
    "A partir de 2027/2028, una factura solo en PDF ya no cumplirá la obligación de facturación electrónica B2B.",
  "Eine IBAN mit falscher Prüfziffer ist ein typisches Merkmal von Zahlungsumleitungsbetrug – vor Zahlung auf bekanntem Weg verifizieren.":
    "Un IBAN con dígito de control erróneo es señal típica de fraude de desvío de pagos — verificar por canal seguro antes de pagar.",
  "Bei zu niedrigem Steuerausweis schuldet der Lieferant die gesetzliche Steuer, der Empfänger kann aber nur den ausgewiesenen Betrag als Vorsteuer abziehen.":
    "Si se repercute menos IVA del legal, el proveedor debe el impuesto legal pero el receptor solo deduce el importe consignado.",
  "Rechenfehler zwischen Netto, Steuer und Brutto führen zu falsch gebuchter Vorsteuer und Zahlungsdifferenzen.":
    "Los errores de cálculo entre neto, IVA y bruto generan asientos erróneos y diferencias de pago.",
  "Zu hoch ausgewiesene Steuer schuldet der Aussteller nach § 14c Abs. 1 UStG, zu niedrig ausgewiesene ist nur in ausgewiesener Höhe abziehbar.":
    "El IVA repercutido en exceso se adeuda según el § 14c (1) UStG; el repercutido por defecto solo es deducible por el importe indicado.",
  "Hochrisiko-KI nach Anhang III darf ab dem 02.12.2027 nur mit Konformitätsbewertung betrieben werden; Verstöße kosten bis zu 15 Mio. € oder 3 % des Jahresumsatzes (Art. 99 Abs. 4).":
    "La IA de alto riesgo del Anexo III solo podrá operar con evaluación de conformidad desde el 02.12.2027; multas de hasta 15 M€ o el 3 % de la facturación anual (Art. 99 (4)).",
  "Bei Rechnungen ausschließlich an Endverbraucher entsteht keine Steuerschuld aus § 14c UStG (EuGH, Urteil vom 08.12.2022, C-378/21; BMF-Schreiben vom 27.02.2024).":
    "En facturas emitidas exclusivamente a consumidores finales no nace deuda tributaria por el § 14c UStG (TJUE C-378/21).",

  // GDPR & Business Terms
  "Name einer natürlichen Person": "Nombre de persona física",
  "Kontaktdaten (E-Mail / Telefon)": "Datos de contacto (correo / teléfono)",
  "Anschrift / Standortdaten": "Dirección / datos de localización",
  "Bankverbindung (IBAN / BIC)": "Cuenta bancaria (IBAN / BIC)",
  "Steuer-ID / USt-IdNr.": "ID fiscal / NIF-IVA",
  "Personalausweis- / Passnummer": "Número de DNI / pasaporte",
  "Sozialversicherungsnummer": "Número de seguridad social",
  "Geburtsdatum": "Fecha de nacimiento",
  "Gesundheitsdaten (Art. 9 DSGVO)": "Datos de salud (Art. 9 RGPD)",
  "Biometrische Daten (Art. 9 DSGVO)": "Datos biométricos (Art. 9 RGPD)",
  "Politische / religiöse Überzeugung / Gewerkschaft (Art. 9 DSGVO)": "Opiniones políticas / religiosas / sindicato (Art. 9 RGPD)",
  "Rechnungsnummer": "Número de factura",
  "Rechnungsdatum": "Fecha de factura",
  "Rechnungstyp": "Tipo de factura",
  "Währung": "Moneda",
  "Käufer-Referenz / Leitweg-ID": "Referencia del comprador / Leitweg-ID",
  "Spezifikationskennung": "Identificador de especificación",
  "Name des Verkäufers": "Nombre del vendedor",
  "USt-IdNr. des Verkäufers": "NIF-IVA del vendedor",
  "Steuernummer des Verkäufers": "Número fiscal del vendedor",
  "Name des Käufers": "Nombre del comprador",
  "IBAN des Zahlungsempfängers": "IBAN del beneficiario",
  "Summe der Rechnungspositionen (netto)": "Suma neta de las líneas de factura",
  "Rechnungsgesamtbetrag ohne Umsatzsteuer": "Importe total de la factura sin IVA",
  "Rechnungsgesamtbetrag der Umsatzsteuer": "Importe total del IVA",
  "Rechnungsgesamtbetrag mit Umsatzsteuer": "Importe total de la factura con IVA",
  "Fälliger Zahlungsbetrag": "Importe pendiente de pago",

  // E-Invoice Business Terms & Visual Checks (app/schemas.py & app/extractors/einvoice.py)
  "Käuferreferenz / Leitweg-ID": "Referencia del comprador / Leitweg-ID",
  "Elektronische Adresse des Verkäufers": "Dirección electrónica del vendedor",
  "Elektronische Adresse des Käufers": "Dirección electrónica del comprador",
  "Summe netto": "Base imponible neta",
  "Umsatzsteuer gesamt": "IVA total",
  "Rechnungsgesamtbetrag (brutto)": "Importe total de la factura (bruto)",
  "Rechnungsgesamtbetrag": "Importe total de la factura",
  "Zahlbetrag": "Importe a pagar",
  "Steuersatz": "Tipo de IVA",
  "Unbekannt (BT-24 fehlt)": "Desconocido (falta BT-24)",
  "Unbekannt": "Desconocido",
  "Elektronische Adresse des Käufers ist eine Leitweg-ID (Schema 0204).": "La dirección electrónica del comprador es una Leitweg-ID (esquema 0204).",
  "Käuferreferenz (BT-10) ist eine gültige Leitweg-ID.": "La referencia del comprador (BT-10) es una Leitweg-ID válida.",

  // EU AI Act Annex III labels (app/schemas.py)
  "Anhang III Nr. 1 - Biometrie": "Anexo III n.º 1 – Biometría",
  "Anhang III Nr. 2 - Kritische Infrastruktur": "Anexo III n.º 2 – Infraestructura crítica",
  "Anhang III Nr. 3 - Allgemeine und berufliche Bildung": "Anexo III n.º 3 – Educación y formación profesional",
  "Anhang III Nr. 4 - Beschäftigung und Personalmanagement": "Anexo III n.º 4 – Empleo y gestión de personal",
  "Anhang III Nr. 5 - Wesentliche Dienste, u. a. Kreditwürdigkeitsprüfung": "Anexo III n.º 5 – Servicios esenciales (incl. solvencia)",
  "Anhang III Nr. 6 - Strafverfolgung": "Anexo III n.º 6 – Fuerzas y cuerpos de seguridad",
  "Anhang III Nr. 7 - Migration, Asyl und Grenzkontrolle": "Anexo III n.º 7 – Migración, asilo y control fronterizo",
  "Anhang III Nr. 8 - Rechtspflege und demokratische Prozesse": "Anexo III n.º 8 – Administración de justicia y procesos democráticos",

  // Exact backend PII_CATEGORY_LABELS & raw enum keys (app/schemas.py)
  "Gesundheitsdaten (Art. 9 Abs. 1 DSGVO)": "Datos de salud (Art. 9(1) RGPD)",
  "Religions- oder Weltanschauungszugehörigkeit (Art. 9 Abs. 1 DSGVO)": "Convicciones religiosas o filosóficas (Art. 9(1) RGPD)",
  "Rassische oder ethnische Herkunft (Art. 9 Abs. 1 DSGVO)": "Origen étnico o racial (Art. 9(1) RGPD)",
  "Politische Meinung (Art. 9 Abs. 1 DSGVO)": "Opiniones políticas (Art. 9(1) RGPD)",
  "Gewerkschaftszugehörigkeit (Art. 9 Abs. 1 DSGVO)": "Afiliación sindical (Art. 9(1) RGPD)",
  "Biometrische Daten (Art. 9 Abs. 1 DSGVO)": "Datos biométricos (Art. 9(1) RGPD)",
  "Genetische Daten (Art. 9 Abs. 1 DSGVO)": "Datos genéticos (Art. 9(1) RGPD)",
  "Sexualleben oder sexuelle Orientierung (Art. 9 Abs. 1 DSGVO)": "Vida u orientación sexual (Art. 9(1) RGPD)",
  "Strafrechtliche Verurteilungen und Straftaten (Art. 10 DSGVO)": "Condenas e infracciones penales (Art. 10 RGPD)",
  "Ausweis- oder Passnummer": "Número de documento o pasaporte",
  "Steueridentifikationsnummer": "Número de identificación fiscal",
  "Bankverbindung (IBAN/BIC)": "Cuenta bancaria (IBAN/BIC)",
  "Anschrift": "Dirección",
  "Kontaktdaten (E-Mail, Telefon)": "Datos de contacto (correo, teléfono)",
  "Sonstige personenbezogene Daten": "Otros datos personales",
  health_data: "Datos de salud",
  religious_belief: "Creencias religiosas",
  racial_or_ethnic_origin: "Origen étnico",
  political_opinion: "Opinión política",
  trade_union_membership: "Afiliación sindical",
  biometric_data: "Datos biométricos",
  genetic_data: "Datos genéticos",
  sex_life_or_orientation: "Vida / orientación sexual",
  criminal_offence_data: "Infracciones penales (Art. 10)",
  id_document_number: "DNI / Pasaporte",
  social_security_number: "Seguridad social",
  tax_identification_number: "NIF",
  bank_account: "Cuenta bancaria (IBAN/BIC)",
  date_of_birth: "Fecha de nacimiento",
  name: "Nombre",
  address: "Dirección",
  contact_data: "Datos de contacto",
  other_personal_data: "Otros PII",

  // Scoring details, risk notes & compliance notes (app/scoring.py)
  "Entbehrlich bei Kleinbetragsrechnungen bis 250 EUR (§ 33 UStDV).": "Prescindible en facturas simplificadas de hasta 250 EUR (§ 33 UStDV).",
  "Bei Kleinbetragsrechnungen genügt das Entgelt inkl. Steuer (§ 33 UStDV).": "En facturas simplificadas basta el importe bruto con IVA incluido (§ 33 UStDV).",
  "Keine Beträge prüfbar": "Sin importes verificables",
  "Empfangspflicht für E-Rechnungen seit 01.01.2025. Bei hybriden Formaten ist der XML-Teil führend; abweichende Angaben im Bildteil können als eigene Rechnung gelten (BMF-Schreiben vom 15.10.2024, Rz. 36, präzisiert durch BMF-Schreiben vom 15.10.2025).":
    "Recepción obligatoria de factura electrónica desde el 01/01/2025. En formatos híbridos prevalece el XML; divergencias en el PDF pueden generar responsabilidad fiscal (§ 14c UStG).",
  "Reines PDF ohne eingebettetes XML: im inländischen B2B-Verkehr seit 01.01.2025 eine „sonstige Rechnung“. Zulässig in der Übergangsfrist bis 31.12.2026 (bei Vorjahresumsatz bis 800.000 EUR bis 31.12.2027), danach Ausstellungspflicht für E-Rechnungen. Kein Punktabzug.":
    "PDF simple sin XML incrustado: «otra factura» en B2B nacional desde 01/01/2025. Admisible en período transitorio hasta 31/12/2026 (o 31/12/2027 con facturación ≤ 800.000 EUR). Sin penalización.",
  "Reines PDF ohne eingebettetes XML: im inländischen B2B-Verkehr seit 01.01.2025 eine „sonstige Rechnung“. Zulässig in der Übergangsfrist bis 31.12.2026 (bei Vorjahresumsatz bis 800.000 EUR bis 31.12.2027), danach Ausstellungspflicht für E-Rechnungen. Kein Punktabzug. Öffentliche Auftraggeber verlangen eine E-Rechnung (für den Bund § 3 ERechV, für Länder und Kommunen Landesrecht).":
    "PDF simple sin XML incrustado (admisible en período transitorio B2B). El sector público exige factura electrónica (§ 3 ERechV / normativa regional). Sin penalización.",
  "Hinweis auf eingebettetes XML (ZUGFeRD/Factur-X/XRechnung), der Datensatz ist aber nicht lesbar. Rechtlich maßgeblich ist bei hybriden Rechnungen der strukturierte XML-Teil; bewertet wird hier der Bildteil. Kein Punktabzug.":
    "Indicio de XML incrustado (ZUGFeRD/Factur-X/XRechnung), pero conjunto ilegible; se audita el PDF visual aunque el XML prevalece legalmente. Sin penalización.",
  "Verstöße gegen EN-16931-Geschäftsregeln führen beim Empfänger regelmäßig zur Zurückweisung durch den Validator.":
    "Las infracciones de las reglas de negocio EN 16931 provocan normalmente el rechazo en el validador del receptor.",
  "MINIMUM- und BASIC-WL-Datensätze erfüllen die Rechnungspflicht nach Ablauf der Übergangsfrist nicht; bis dahin ist der Bildteil die Rechnung.":
    "Los perfiles MINIMUM y BASIC WL no cumplen la obligación de factura electrónica tras el período transitorio; hasta entonces rige el PDF visual.",
  "Einsatz ist unionsrechtlich untersagt (seit 02.02.2025).": "Uso prohibido por el Derecho de la UE (desde el 02/02/2025).",
  "Kennzeichnungs- und Informationspflichten nach Art. 50 sicherstellen.": "Garantizar las obligaciones de transparencia e información del art. 50.",
  "Keine spezifischen Pflichten; Maßnahmen zur KI-Kompetenz nach Art. 4 ergreifen.": "Sin obligaciones específicas; adoptar medidas de alfabetización en IA según el art. 4.",
  "Art. 6 Abs. 3: Ausnahme möglich bei eng begrenzten oder rein vorbereitenden Aufgaben ohne Profiling – Profiling natürlicher Personen ist immer Hochrisiko. Das System eskaliert konservativ auf Hochrisiko. Die Pflichten für Anhang-III-Systeme gelten nach der Änderung durch VO (EU) 2026/1744 ab dem 02.12.2027.":
    "Art. 6(3): excepción solo para tareas estrictamente limitadas sin elaboración de perfiles (el perfilado siempre es alto riesgo). Escalamiento conservador. Obligaciones Anexo III desde el 02/12/2027.",
  "Rechtsgrundlage nach Art. 9 Abs. 2 DSGVO ist im Dokument nicht belegt; Zugriff beschränken und Erforderlichkeit prüfen.":
    "La base jurídica del art. 9(2) RGPD no consta en el documento; restringir acceso y verificar necesidad.",
  "Verarbeitung nur bei gesetzlicher Grundlage; Speicherbegrenzung (Art. 5 Abs. 1 lit. e).":
    "Tratar solo con base legal; limitación del plazo de conservación (Art. 5(1)(e)).",
  "Maßgeblich ist der XML-Datensatz; ein abweichender Bildteil kann als weitere Rechnung gewertet werden und bei höherem Steuerausweis eine Steuerschuld nach § 14c UStG auslösen.":
    "Prevalece el XML; un PDF divergente puede considerarse segunda factura y generar deuda fiscal según § 14c UStG.",
  "Ohne gültige Leitweg-ID kann die Eingangsplattform des Auftraggebers die Rechnung nicht zuordnen und weist sie zurück; die Zahlung verzögert sich.":
    "Sin una Leitweg-ID válida, la plataforma pública rechaza la factura y retrasa el pago.",
  "Verbotene Praktiken sind seit 02.02.2025 untersagt; das Bußgeld reicht bis 35 Mio. € oder 7 % des weltweiten Jahresumsatzes (Art. 99 Abs. 3).":
    "Las prácticas prohibidas están vetadas desde el 02/02/2025; multas de hasta 35 M€ o el 7 % de la facturación anual (Art. 99(3)).",
  "Verstöße gegen die Transparenzpflichten nach Art. 50 können mit bis zu 15 Mio. € oder 3 % des Jahresumsatzes geahndet werden.":
    "Incumplimientos del art. 50 pueden sancionarse con hasta 15 M€ o el 3 % de la facturación anual.",
  "Verarbeitung besonderer Kategorien ohne Rechtsgrundlage nach Art. 9 Abs. 2 kann mit bis zu 20 Mio. € oder 4 % des Jahresumsatzes geahndet werden (Art. 83 Abs. 5 DSGVO).":
    "El tratamiento de categorías especiales sin base del art. 9(2) conlleva multas de hasta 20 M€ o el 4 % de la facturación anual (Art. 83(5) RGPD).",
  "Amtliche Kennnummern sind besonders missbrauchsanfällig (Identitätsdiebstahl) und dürfen nur mit Rechtsgrundlage gespeichert werden.":
    "Los identificadores oficiales conllevan alto riesgo de suplantación y solo deben conservarse con base legal.",

  // Jobs, Copilot steps, Heuristics, Local AI & Release messages
  "Text-Layer & XML-Vorrang": "Capa de texto y primacía XML",
  "PII-Scanner & Privacy Vault": "Escáner PII y Privacy Vault",
  "§ 14 UStG Extraktion & Prüfung": "Extracción § 14 UStG y verificación",
  "EU AI Act, Scorecard & Ledger": "Reglamento de IA, Scorecard y Registro",
  "Regelbasiertes Referenz-Audit – KI nicht verfügbar": "Auditoría de referencia basada en reglas – IA no disponible",
  "Regelbasiertes Referenz-Audit – KI temporär überlastet": "Auditoría de referencia basada en reglas – IA no disponible",
  "Beleg archiviert": "Documento archivado",
  "Beleg aus dem Archiv geholt": "Documento recuperado del archivo",
  "Belegstellen und Prüfergebnis aufbereiten": "Preparando citas y resultado de auditoría",
  "Personenbezogene Daten pseudonymisieren (Privacy Vault)": "Seudonimizando datos personales (Privacy Vault)",
  "Regelwerk antwortet (KI nicht verfügbar)": "Responde el motor de reglas (IA no disponible)",
  "Antwort re-identifizieren": "Reidentificando respuesta",
  "Antwort formulieren": "Formulando respuesta",
  "Ollama läuft.": "Ollama está en ejecución.",
  "Ollama ist installiert, läuft aber nicht.": "Ollama está instalado pero detenido.",
  "Ollama lief bereits.": "Ollama ya estaba en ejecución.",
  "Ollama lief nicht.": "Ollama no estaba en ejecución.",
  "Ollama läuft jetzt (Flash Attention, 8-Bit-KV-Cache).": "Ollama en ejecución (Flash Attention, caché KV de 8 bits).",
  "Ollama ist gestoppt – der Grafikspeicher ist wieder frei.": "Ollama detenido — memoria GPU liberada.",
  "Im Container läuft Ollama als eigener Dienst (docker compose) – Start und Stopp dort.": "En contenedor, Ollama se ejecuta como servicio independiente (docker compose).",
  "Im Container wird Ollama über docker compose gestartet.": "En contenedor, Ollama se inicia mediante docker compose.",
  "Im Container wird Ollama über docker compose gestoppt.": "En contenedor, Ollama se detiene mediante docker compose.",
  "Ollama ist auf diesem Rechner nicht installiert (ollama.com).": "Ollama no está instalado en este equipo (ollama.com).",
  "Keine lokale KI gefunden. Ollama (ollama.com) installieren, dann erscheint hier der Startknopf.": "No se encontró IA local. Instale Ollama (ollama.com) para habilitarla.",
  "Keine Git-Arbeitskopie (z. B. Docker-Image) - Update über ein neues Image.": "No es un repositorio Git (p. ej. imagen Docker) — actualice mediante nueva imagen.",
  "Keine Git-Arbeitskopie - Update über ein neues Image.": "No es un repositorio Git — actualice mediante nueva imagen.",
  "Ein Update läuft bereits.": "Ya hay una actualización en curso.",
  "Lokale Änderungen vorhanden - Update abgebrochen.": "Hay cambios locales — actualización cancelada.",
};

/**
 * Protokoll-Zusammenfassungen und Anbieter-Meldungen.  Gespeichert bleiben sie deutsch
 * (Teil der Hash-Kette); uebersetzt wird nur die Anzeige.  Muster gelten auch mitten
 * in aneinandergereihten Saetzen (fallback_reason = Ursache + Hinweis).
 */
const MESSAGE_RULES: [RegExp, string, string][] = [
  [/^(.+) erreichbar, Modell (\S+) verfügbar\.$/, "$1 reachable, model $2 available.", "$1 disponible, modelo $2 disponible."],
  [/^Ollama erreichbar, Modell (\S+) installiert\.$/, "Ollama reachable, model $1 installed.", "Ollama disponible, modelo $1 instalado."],
  [/^Ollama erreichbar, Modell '([^']+)' aber nicht installiert\./, "Ollama reachable, but model '$1' is not installed.", "Ollama disponible, pero el modelo '$1' no está instalado."],
  [/ Installiert ist (\S+) – per Klick übernehmen\./, " $1 is installed – apply with one click.", " Está instalado $1: aplíquelo con un clic."],
  [/Tagesbudget für Cloud-KI erreicht \(([\d.]+) von ([\d.]+) Tokens\)\./g, "Daily cloud AI budget reached ($1 of $2 tokens).", "Presupuesto diario de IA en la nube alcanzado ($1 de $2 tokens)."],
  [/Bis morgen lokal prüfen – lokale Modelle sind nicht begrenzt – oder das Tageslimit in der Serverkonfiguration anheben\./g,
    "Run audits locally until tomorrow – local models are not limited – or raise the daily limit in the server configuration.",
    "Analice en local hasta mañana (los modelos locales no tienen límite) o aumente el límite diario en la configuración del servidor."],
  [/Ein kleineres lokales Modell wählen oder das Zeitlimit in der Serverkonfiguration anheben\./g,
    "Choose a smaller local model or raise the timeout in the server configuration.",
    "Elija un modelo local más pequeño o aumente el tiempo límite en la configuración del servidor."],
  [/Ein schnelleres Modell wählen oder in einigen Minuten erneut prüfen\./g,
    "Choose a faster model or try again in a few minutes.", "Elija un modelo más rápido o reintente en unos minutos."],
  [/^Wechsel (\S+) -> (\S+) \(([^)]+)\)$/, "Provider switch $1 -> $2 ($3)", "Cambio de proveedor $1 -> $2 ($3)"],
  [/^Modellwechsel (.+) -> (.+)$/, "Model change $1 -> $2", "Cambio de modelo $1 -> $2"],
  [/^Release-Wechsel (\S+) -> (\S+) durch (.+)$/, "Release change $1 -> $2 by $3", "Cambio de versión $1 -> $2 por $3"],
  [/^Einstufung (\S+) -> (\S+) durch (.+); Score (\S+) -> (\S+)$/, "Classification $1 -> $2 by $3; score $4 -> $5", "Clasificación $1 -> $2 por $3; puntuación $4 -> $5"],
  [/^(SEALED_[A-Z]+) durch (.+)$/, "$1 by $2", "$1 por $2"],
  [/^Score (\d+): /, "Score $1: ", "Puntuación $1: "],
  [/§ 14 UStG −/g, "Sec. 14 UStG −", "§ 14 UStG −"],
  [/Finanzmathematik −/g, "Financial math −", "Matemática financiera −"],
  [/DSGVO −/g, "GDPR −", "RGPD −"],
  [/^EU AI Act: Hochrisiko$/, "EU AI Act: high risk", "EU AI Act: alto riesgo"],
  [/^DSGVO: personenbezogene Daten \((\w+)\)$/, "GDPR: personal data ($1)", "RGPD: datos personales ($1)"],
  [/^DSGVO: besondere Kategorien \(Art\. 9\/10\)$/, "GDPR: special categories (Art. 9/10)", "RGPD: categorías especiales (Art. 9/10)"],
  [/ nimmt vorerst keine Anfragen an \(HTTP 429: Anfragelimit oder Kontingent des API-Keys erreicht\)\./g,
    " is not accepting requests for now (HTTP 429: rate limit or API key quota reached).",
    " no acepta solicitudes por ahora (HTTP 429: límite de solicitudes o cuota de la clave API alcanzados)."],
  [/ hat die Anfrage wegen Zeitüberschreitung abgebrochen \(HTTP 408\)\./g,
    " cancelled the request after a timeout (HTTP 408).", " canceló la solicitud por tiempo agotado (HTTP 408)."],
  [/ ist vorübergehend überlastet \(HTTP (\d+)\)\./g, " is temporarily overloaded (HTTP $1).", " está saturado temporalmente (HTTP $1)."],
  [/ meldet eine Störung \(HTTP (\d+)\)\./g, " reports an outage (HTTP $1).", " informa de una incidencia (HTTP $1)."],
  [/ antwortet nicht rechtzeitig \(Zeitüberschreitung\)\./g, " did not respond in time (timeout).", " no respondió a tiempo (tiempo agotado)."],
  [/ ist nicht erreichbar \(Verbindungsfehler\)\./g, " is unreachable (connection error).", " no está disponible (error de conexión)."],
  [/ lehnt den API-Key ab \(HTTP (\d+)\)\./g, " rejects the API key (HTTP $1).", " rechaza la clave API (HTTP $1)."],
  [/Ausweichmodell oder zweiten API-Key unter Einstellungen › KI(?:-Einrichtung)? › Ausweich-Kaskade hinterlegen; sonst in einigen Minuten erneut prüfen\./g,
    "Add a fallback model or a second API key under Settings › AI setup › Fallback cascade; otherwise try again in a few minutes.",
    "Añada un modelo alternativo o una segunda clave API en Ajustes › Configuración IA › Cascada de respaldo; si no, reintente en unos minutos."],
  [/Auch die zweite Stufe der Ausweich-Kaskade antwortete nicht\./g,
    "The second stage of the fallback cascade did not respond either.", "Tampoco respondió el segundo nivel de la cascada de respaldo."],
  [/Auch die übrigen (\d+) Stufen der Ausweich-Kaskade antworteten nicht\./g,
    "The remaining $1 stages of the fallback cascade did not respond either.", "Tampoco respondieron los $1 niveles restantes de la cascada de respaldo."],
  [/API-Key prüfen; ggf\. Berechtigung für das gewählte Modell freischalten\./g,
    "Check the API key; if needed, enable access to the selected model.", "Compruebe la clave API; si es necesario, habilite el acceso al modelo elegido."],
  [/API-Key unter Einstellungen › KI(?:-Einrichtung)? hinterlegen oder auf 'Lokal' umschalten\./g,
    "Add an API key under Settings › AI setup or switch to 'Local'.", "Añada una clave API en Ajustes › Configuración IA o cambie a 'Local'."],
  [/Ollama unter (\S+) ist nicht erreichbar\./g, "Ollama at $1 is unreachable.", "Ollama en $1 no está disponible."],
  [/Lokale KI starten \(Einstellungen › KI(?:-Einrichtung)?\) oder im Terminal 'ollama serve' ausführen; Erreichbarkeit mit scripts\/smoke_test_ollama\.py prüfen\./g,
    "Start local AI (Settings › AI setup) or run 'ollama serve' in a terminal; check reachability with scripts/smoke_test_ollama.py.",
    "Inicie la IA local (Ajustes › Configuración IA) o ejecute 'ollama serve' en una terminal; compruebe la conexión con scripts/smoke_test_ollama.py."],
];

export function translateDynamic(text: string | null | undefined, locale: Locale = getActiveLocale()): string {
  if (!text || locale === "de") return text ?? "";
  const map = locale === "en" ? EXACT_EN : EXACT_ES;
  if (map[text]) return map[text];
  // Zusammengesetzte Protokoll-Zeilen ("A | B | C") Teil fuer Teil uebersetzen.
  if (text.includes(" | ")) return text.split(" | ").map((part) => translateDynamic(part, locale)).join(" | ");

  let out = text;
  for (const [pattern, en, es] of MESSAGE_RULES) out = out.replace(pattern, locale === "en" ? en : es);
  if (locale === "en") {
    out = out
      .replace(/^Vollständig \((\d+\/\d+)\)(.*)$/, "Complete ($1)$2")
      .replace(/^Mängel \((\d+) fehlend\)(.*)$/, "Defects ($1 missing)$2")
      .replace(/ · Kleinbetrag$/, " · Small-amount")
      .replace(/^(\d+) Datensatz maskiert$/, "$1 record masked")
      .replace(/^(\d+) Datensätze maskiert$/, "$1 records masked")
      .replace(/^(\d+) Datensatz erkannt und maskiert\.$/, "$1 record detected and masked.")
      .replace(/^(\d+) Datensätze erkannt und maskiert\.$/, "$1 records detected and masked.")
      .replace(/^Art\. 9\/10: (\d+) Kategorie\(n\)$/, "Art. 9/10: $1 category(ies)")
      .replace(/^Alle (\d+) Kernwerte stimmen im XML und im Bildteil überein\.$/, "All $1 core values match between XML and visual PDF.")
      .replace(/^Im Bildteil nicht wiedergefunden: (.+?)\. Maßgeblich ist der XML-Datensatz\. Kein Punktabzug\.$/, "Not found in visual PDF: $1. The XML dataset governs. No score deduction.")
      .replace(/^Diskrepanz zwischen visuellem PDF und maßgeblichem XML-Datensatz \(BMF 15\.10\.2024: XML hat Vorrang\)\. (.+)$/, "Mismatch between visual PDF and authoritative XML (BMF 15 Oct 2024: XML prevails). $1")
      .replace(/^Steuersatz (.+) ist zum Rechnungsdatum nicht zulässig\.$/, "VAT rate $1 is not valid on the invoice date.")
      .replace(/^(.+) \+ (.+) ergibt (.+), ausgewiesen sind (.+)\.$/, "$1 + $2 equals $3, but $4 is stated.")
      .replace(/^Erwartet (.+), ausgewiesen (.+)\.$/, "Expected $1, stated $2.")
      .replace(/^Profil ([^,]+), Syntax ([^(]+) \((eingebettet als ([^)]+)|reines XML)\)\. Geprüft: Profilkennung BT-24, Pflichtfelder und Summenregeln \(BR-CO-10\/13\/14\/15, BR-DE-15\)\. Keine Validierung gegen XSD und Schematron \(z\. B\. KoSIT-Validator\)\.(.*)$/,
        (_m, prof, syn, cont, att, rest) => `Profile ${prof}, syntax ${syn} (${att ? `embedded as ${att}` : "standalone XML"}). Checked: BT-24 profile ID, mandatory fields and totals rules (BR-CO-10/13/14/15, BR-DE-15). No XSD/Schematron (KoSIT) validation.${rest}`)
      .replace(/ Verstöße: (.+?) Kein Punktabzug\.$/, " Violations: $1 No score deduction.")
      .replace(/^Profil ([^(]+) \((eingebettet als ([^)]+)|reines XML)\) erfüllt nicht die Anforderungen an eine E-Rechnung \(BMF-Schreiben vom 15\.10\.2024\)\. Rechnung ist der Bildteil – eine „sonstige Rechnung“, zulässig in der Übergangsfrist\. Kein Punktabzug\.$/,
        (_m, prof, _cont, att) => `Profile ${prof} (${att ? `embedded as ${att}` : "standalone XML"}) does not meet E-Invoice requirements (BMF 15 Oct 2024). The visual PDF governs during the transitional period. No score deduction.`)
      .replace(/^Profil nicht erkennbar \(BT-24: ([^)]+)\)\. Die Daten wurden gelesen, die Zuordnung zu EN 16931 ist aber nicht belegt\. Kein Punktabzug\.$/,
        "Profile unrecognized (BT-24: $1). Data read, but EN 16931 compliance is unverified. No score deduction.")
      .replace(/^Eingebetteter Datensatz (.*?) ist nicht auswertbar: (.+?) Bewertet wird der Bildteil\. Kein Punktabzug\.$/,
        "Embedded dataset $1 cannot be parsed: $2 Falling back to visual PDF. No score deduction.")
      .replace(/Käufer „(.+?)“ ist als öffentliche Stelle erkennbar \(„(.+?)“\)\./g, "Buyer “$1” identified as public authority (“$2”).")
      .replace(/^([^:]+): Aufbau und Prüfziffer \(ISO\/IEC 7064, MOD 97-10\) gültig\. (.+)$/, "$1: Format and check digits (ISO/IEC 7064, MOD 97-10) valid. $2")
      .replace(/^Öffentlicher Auftraggeber erkannt, aber keine Leitweg-ID angegeben\. (.+)$/, "Public buyer detected, but no Leitweg-ID provided. $1")
      .replace(/^Prüfziffer ungültig \(erwartet ([^,]+), angegeben ([^)]+)\)\.$/, "Invalid check digit (expected $1, provided $2).")
      .replace(/^(.+?)\. Kein Nachweis einer Konformitätsbewertung \(Art\. 43\) und CE-Kennzeichnung \(Art\. 48\); Betreiberpflichten nach Art\. 26 beachten\.$/, "$1. No proof of conformity assessment (Art. 43) or CE marking (Art. 48); observe deployer duties under Art. 26.")
      .replace(/^(.+?)\. Hinweis auf Konformitätsbewertung vorhanden – Nachweis prüfen \(Art\. 43\)\.$/, "$1. Conformity indicator present — verify evidence (Art. 43).")
      .replace(/^Ollama ist als entfernter Dienst konfiguriert \(([^)]+)\)\.$/, "Ollama is configured as a remote service ($1).")
      .replace(/^Update-Server nicht erreichbar: (.+)$/, "Update server unreachable: $1")
      .replace(/^Wechsle auf (.+?): (.+)$/, "Switching to $1: $2")
      .replace(/^(.+?) prüft Belegstellen und Rechtsnormen$/, "$1 reviewing excerpts and statutory rules");
  } else if (locale === "es") {
    out = out
      .replace(/^Vollständig \((\d+\/\d+)\)(.*)$/, "Completo ($1)$2")
      .replace(/^Mängel \((\d+) fehlend\)(.*)$/, "Defectos ($1 faltantes)$2")
      .replace(/ · Kleinbetrag$/, " · Importe reducido")
      .replace(/^(\d+) Datensatz maskiert$/, "$1 registro enmascarado")
      .replace(/^(\d+) Datensätze maskiert$/, "$1 registros enmascarados")
      .replace(/^(\d+) Datensatz erkannt und maskiert\.$/, "$1 registro detectado y enmascarado.")
      .replace(/^(\d+) Datensätze erkannt und maskiert\.$/, "$1 registros detectados y enmascarados.")
      .replace(/^Art\. 9\/10: (\d+) Kategorie\(n\)$/, "Art. 9/10: $1 categoría(s)")
      .replace(/^Alle (\d+) Kernwerte stimmen im XML und im Bildteil überein\.$/, "Los $1 valores clave coinciden entre el XML y el PDF visual.")
      .replace(/^Im Bildteil nicht wiedergefunden: (.+?)\. Maßgeblich ist der XML-Datensatz\. Kein Punktabzug\.$/, "No hallado en el PDF visual: $1. Prevalece el XML. Sin penalización.")
      .replace(/^Diskrepanz zwischen visuellem PDF und maßgeblichem XML-Datensatz \(BMF 15\.10\.2024: XML hat Vorrang\)\. (.+)$/, "Discrepancia entre el PDF visual y el XML vinculante (BMF 15/10/2024). $1")
      .replace(/^Steuersatz (.+) ist zum Rechnungsdatum nicht zulässig\.$/, "El tipo de IVA $1 no es válido en la fecha de la factura.")
      .replace(/^(.+) \+ (.+) ergibt (.+), ausgewiesen sind (.+)\.$/, "$1 + $2 suma $3, pero figura $4.")
      .replace(/^Erwartet (.+), ausgewiesen (.+)\.$/, "Esperado $1, consignado $2.")
      .replace(/^Profil ([^,]+), Syntax ([^(]+) \((eingebettet als ([^)]+)|reines XML)\)\. Geprüft: Profilkennung BT-24, Pflichtfelder und Summenregeln \(BR-CO-10\/13\/14\/15, BR-DE-15\)\. Keine Validierung gegen XSD und Schematron \(z\. B\. KoSIT-Validator\)\.(.*)$/,
        (_m, prof, syn, cont, att, rest) => `Perfil ${prof}, sintaxis ${syn} (${att ? `incrustado como ${att}` : "XML puro"}). Verificados BT-24, campos obligatorios y sumas (BR-CO-10/13/14/15, BR-DE-15). Sin validación XSD/Schematron.${rest}`)
      .replace(/ Verstöße: (.+?) Kein Punktabzug\.$/, " Infracciones: $1 Sin penalización.")
      .replace(/^Profil ([^(]+) \((eingebettet als ([^)]+)|reines XML)\) erfüllt nicht die Anforderungen an eine E-Rechnung \(BMF-Schreiben vom 15\.10\.2024\)\. Rechnung ist der Bildteil – eine „sonstige Rechnung“, zulässig in der Übergangsfrist\. Kein Punktabzug\.$/,
        (_m, prof, _cont, att) => `El perfil ${prof} (${att ? `incrustado como ${att}` : "XML puro"}) no cumple los requisitos de factura electrónica (BMF 15/10/2024); prevalece el PDF visual. Sin penalización.`)
      .replace(/^Profil nicht erkennbar \(BT-24: ([^)]+)\)\. Die Daten wurden gelesen, die Zuordnung zu EN 16931 ist aber nicht belegt\. Kein Punktabzug\.$/,
        "Perfil no reconocido (BT-24: $1). Datos leídos, pero conformidad EN 16931 sin verificar. Sin penalización.")
      .replace(/^Eingebetteter Datensatz (.*?) ist nicht auswertbar: (.+?) Bewertet wird der Bildteil\. Kein Punktabzug\.$/,
        "El XML incrustado $1 no se pudo analizar: $2 Se evalúa el PDF visual. Sin penalización.")
      .replace(/Käufer „(.+?)“ ist als öffentliche Stelle erkennbar \(„(.+?)“\)\./g, "Comprador «$1» identificado como organismo público («$2»).")
      .replace(/^([^:]+): Aufbau und Prüfziffer \(ISO\/IEC 7064, MOD 97-10\) gültig\. (.+)$/, "$1: Formato y dígitos de control (ISO/IEC 7064, MOD 97-10) válidos. $2")
      .replace(/^Öffentlicher Auftraggeber erkannt, aber keine Leitweg-ID angegeben\. (.+)$/, "Comprador público detectado, pero sin Leitweg-ID. $1")
      .replace(/^Prüfziffer ungültig \(erwartet ([^,]+), angegeben ([^)]+)\)\.$/, "Dígito de control inválido (esperado $1, indicado $2).")
      .replace(/^(.+?)\. Kein Nachweis einer Konformitätsbewertung \(Art\. 43\) und CE-Kennzeichnung \(Art\. 48\); Betreiberpflichten nach Art\. 26 beachten\.$/, "$1. Sin acreditación de conformidad (Art. 43) ni marcado CE (Art. 48); cumplir obligaciones del art. 26.")
      .replace(/^(.+?)\. Hinweis auf Konformitätsbewertung vorhanden – Nachweis prüfen \(Art\. 43\)\.$/, "$1. Indicio de evaluación de conformidad — verificar acreditación (Art. 43).")
      .replace(/^Ollama ist als entfernter Dienst konfiguriert \(([^)]+)\)\.$/, "Ollama está configurado como servicio remoto ($1).")
      .replace(/^Update-Server nicht erreichbar: (.+)$/, "Servidor de actualizaciones inaccesible: $1")
      .replace(/^Wechsle auf (.+?): (.+)$/, "Cambiando a $1: $2")
      .replace(/^(.+?) prüft Belegstellen und Rechtsnormen$/, "$1 comprobando citas y normativa");
  }
  return out;
}

interface I18nContextValue {
  locale: Locale;
  setLocale: (next: Locale) => void;
  tr: (de: string, en: string, es: string) => string;
  td: (text: string | null | undefined) => string;
}

const I18nContext = createContext<I18nContextValue>({
  locale: "de",
  setLocale: () => undefined,
  tr: (de) => de,
  td: (text) => text ?? "",
});

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("de");

  useEffect(() => {
    const initial = getActiveLocale();
    setActiveLocale(initial);
    setLocaleState(initial);
  }, []);

  const setLocale = useCallback((next: Locale) => {
    setActiveLocale(next);
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
    } catch {
      /* private mode */
    }
    setLocaleState(next);
  }, []);

  const boundTr = useCallback((de: string, en: string, es: string) => tr(de, en, es, locale), [locale]);
  const boundTd = useCallback((text: string | null | undefined) => translateDynamic(text, locale), [locale]);

  return (
    <I18nContext.Provider value={{ locale, setLocale, tr: boundTr, td: boundTd }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n(): I18nContextValue {
  return useContext(I18nContext);
}
