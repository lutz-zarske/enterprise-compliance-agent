/**
 * Kurze Erklärtexte für Tooltips (höchstens zwei Sätze, Alltagssprache) - eine Quelle,
 * damit derselbe Begriff überall gleich erklärt wird (Belegliste, Kopfzeile, Inspektor).
 */
import type { CheckStatus } from "../types/api";
import { tr } from "./i18n";

/** Ampel-Etikett der Scorecard (``band_label`` bzw. ``presentedBand``). */
export function bandHint(label: string): string | null {
  switch (label) {
    case "Vollständig verkehrsfähig & konform":
      return tr(
        "Score ab 85 ohne Mangel: Alle Pflichtangaben sind da und die Beträge stimmen. Der Beleg kann gebucht und bezahlt werden.",
        "Score of 85 or more with no defect: all mandatory details are present and the amounts add up. The document can be booked and paid.",
        "Puntuación de 85 o más sin defectos: están todos los datos obligatorios y los importes cuadran. El documento puede contabilizarse y pagarse.",
      );
    case "Nachbesserung erforderlich":
      return tr(
        "Score 60 bis 84: Der Beleg ist im Kern brauchbar, einzelne Angaben fehlen oder weichen ab. Vor der Zahlung beim Aussteller ergänzen lassen.",
        "Score 60 to 84: the document is basically usable, but some details are missing or inconsistent. Have the issuer complete them before payment.",
        "Puntuación de 60 a 84: el documento es aprovechable, pero faltan o no cuadran algunos datos. Pida al emisor que los complete antes de pagar.",
      );
    case "Revisionssperre / schwerer Rechtsverstoß":
      return tr(
        "Score unter 60: Der Beleg hat schwere Mängel und darf so weder gebucht noch bezahlt werden. Erst nach Korrektur durch den Aussteller erneut prüfen.",
        "Score below 60: the document has serious defects and must not be booked or paid as is. Re-audit once the issuer has corrected it.",
        "Puntuación inferior a 60: el documento tiene defectos graves y no debe contabilizarse ni pagarse así. Vuelva a auditarlo cuando el emisor lo corrija.",
      );
    case "Nachforderung nötig":
      return tr(
        "Eine Pflichtangabe fehlt, deshalb ist die Freigabe gesperrt. Fordern Sie beim Aussteller eine korrigierte Rechnung an.",
        "A mandatory detail is missing, so approval is blocked. Ask the issuer for a corrected invoice.",
        "Falta un dato obligatorio, por eso la aprobación está bloqueada. Solicite al emisor una factura corregida.",
      );
    case "Freigabe gesperrt":
      return tr(
        "Ein schwerer Befund sperrt die Freigabe trotz gutem Score. Die Gründe stehen bei den Prüfpunkten mit Abzug.",
        "A serious finding blocks approval despite a good score. The reasons are listed at the checks with deductions.",
        "Un hallazgo grave bloquea la aprobación pese a la buena puntuación. Los motivos figuran en los controles con deducción.",
      );
    case "Freigabe unter Vorbehalt":
      return tr(
        "Inhaltlich in Ordnung, aber eine Formvorgabe wie der XRechnung-Standard ist nicht eingehalten. Freigabe möglich, die Abweichung beim Aussteller ansprechen.",
        "Fine in substance, but a formal requirement such as the XRechnung standard is not met. Approval is possible; raise the deviation with the issuer.",
        "Correcto en el fondo, pero no se cumple un requisito formal como el estándar XRechnung. Se puede aprobar; comente la desviación con el emisor.",
      );
    default:
      return null;
  }
}

/** Bearbeitungsstand eines Belegs (Kopf des Arbeitsbereichs). */
export function documentStatusHint(status: "uploaded" | "processing" | "extracted" | "failed" | "sealed"): string {
  switch (status) {
    case "uploaded":
      return tr("Noch nicht geprüft – mit „Prüfen“ starten.", "Not audited yet – start with “Audit”.", "Aún sin auditar: empiece con «Auditar».");
    case "processing":
      return tr(
        "Die Prüfung läuft im Hintergrund; das Ergebnis erscheint von selbst.",
        "The audit runs in the background; the result appears automatically.",
        "La auditoría se ejecuta en segundo plano; el resultado aparece solo.",
      );
    case "extracted":
      return tr(
        "Die automatische Prüfung ist abgeschlossen. Freigeben und versiegeln kann nur eine Prüfperson.",
        "The automated audit is complete. Only an auditor can approve and seal it.",
        "La auditoría automática ha terminado. Solo un auditor puede aprobarla y sellarla.",
      );
    case "failed":
      return tr(
        "Die Prüfung ist abgebrochen. Mit „Neu prüfen“ wiederholen.",
        "The audit was aborted. Repeat it with “Re-audit”.",
        "La auditoría se interrumpió. Repítala con «Reanalizar».",
      );
    case "sealed":
      return tr(
        "Eine Prüfperson hat das Ergebnis abgezeichnet und digital signiert. Danach lässt es sich nicht mehr unbemerkt ändern.",
        "An auditor has signed off the result with a digital signature. After that it cannot be changed unnoticed.",
        "Un auditor ha firmado digitalmente el resultado. A partir de ahí no puede cambiarse sin que se note.",
      );
  }
}

/** Status eines einzelnen Prüfpunkts (Chip rechts in der Prüfliste). */
export function checkStatusHint(status: CheckStatus): string {
  switch (status) {
    case "pass":
      return tr("Diese Anforderung ist erfüllt.", "This requirement is met.", "Este requisito se cumple.");
    case "warn":
      return tr(
        "Auffälligkeit zum Ansehen – ein Punktabzug steht gegebenenfalls daneben.",
        "Something to look at – any point deduction is shown next to it.",
        "Algo que revisar; si resta puntos, se indica al lado.",
      );
    case "fail":
      return tr(
        "Anforderung nicht erfüllt: Das kostet Punkte und muss meist beim Aussteller korrigiert werden.",
        "Requirement not met: this costs points and usually has to be corrected by the issuer.",
        "Requisito no cumplido: resta puntos y normalmente debe corregirlo el emisor.",
      );
    case "not_applicable":
      return tr("Für diesen Beleg nicht relevant.", "Not relevant for this document.", "No aplica a este documento.");
  }
}

/** Maskierungsstufe der Belegansicht (Einstellungen › Compliance). */
export function maskingHint(level: "strict" | "standard" | "audit_only", marks: number): string {
  const lead = {
    strict: tr(
      "Strikt: Alle personenbezogenen Angaben samt Namen, Adressen und Beträgen sind geschwärzt.",
      "Strict: all personal details including names, addresses and amounts are redacted.",
      "Estricto: se ocultan todos los datos personales, incluidos nombres, direcciones e importes.",
    ),
    standard: tr(
      "Standard: IBAN, Steuer- und Kennnummern, E-Mail, Telefon und Gesundheitsdaten sind geschwärzt, Namen und Adressen nur markiert.",
      "Standard: IBAN, tax and ID numbers, email, phone and health data are redacted; names and addresses are only highlighted.",
      "Estándar: se ocultan IBAN, números fiscales e identificativos, correo, teléfono y datos de salud; nombres y direcciones solo se marcan.",
    ),
    audit_only: tr(
      "Audit-Only: Alles bleibt lesbar und ist nur markiert – nur für berechtigte interne Prüfer.",
      "Audit-Only: everything stays readable and is only highlighted – for authorized internal auditors only.",
      "Audit-Only: todo sigue legible y solo se marca; solo para auditores internos autorizados.",
    ),
  }[level];
  const count = tr(
    `${marks} ${marks === 1 ? "Stelle ist" : "Stellen sind"} im Belegtext farbig hervorgehoben.`,
    `${marks} ${marks === 1 ? "passage is" : "passages are"} highlighted in the document text.`,
    `${marks} ${marks === 1 ? "pasaje está resaltado" : "pasajes están resaltados"} en el texto.`,
  );
  return `${lead} ${count}`;
}

export function einvoiceHint(): string {
  return tr(
    "Der Beleg enthält einen maschinenlesbaren Rechnungsdatensatz (XML) nach der EU-Norm EN 16931. Dieser Datensatz gilt rechtlich vor dem PDF-Bild.",
    "The document contains a machine-readable invoice dataset (XML) under the EU standard EN 16931. This dataset legally prevails over the PDF image.",
    "El documento contiene un conjunto de datos de factura legible por máquina (XML) según la norma europea EN 16931. Prevalece legalmente sobre la imagen PDF.",
  );
}

export function highRiskHint(): string {
  return tr(
    "Der Beleg betrifft ein KI-System mit hohem Risiko, etwa zur Bewerberauswahl. Ab 02.12.2027 braucht es dafür eine Konformitätsbewertung (EU AI Act).",
    "The document concerns a high-risk AI system, e.g. for screening job applicants. From 2 Dec 2027 it requires a conformity assessment (EU AI Act).",
    "El documento se refiere a un sistema de IA de alto riesgo, p. ej. para seleccionar candidatos. Desde el 02.12.2027 requiere una evaluación de conformidad (Reglamento de IA).",
  );
}

export function referenceAuditHint(): string {
  return tr(
    "Musterbeleg mit vorberechneter KI-Antwort. Score, Schwärzung und Protokoll stammen trotzdem aus dem echten Regelwerk.",
    "Sample document with a precomputed AI answer. Score, redaction and audit trail still come from the real rule set.",
    "Documento de ejemplo con respuesta de IA precalculada. Puntuación, ocultación y registro proceden igualmente del reglamento real.",
  );
}

export function rulesOnlyHint(): string {
  return tr(
    "Kein KI-Modell war erreichbar, deshalb hat das Regelwerk allein und vorsichtig geprüft. Sobald ein Modell läuft, mit „Neu prüfen“ wiederholen.",
    "No AI model was reachable, so the rule set audited the document on its own, conservatively. Repeat with “Re-audit” once a model is available.",
    "No había ningún modelo de IA disponible, así que el reglamento auditó solo y con prudencia. Repita con «Reanalizar» cuando haya un modelo.",
  );
}

export function smallInvoiceHint(): string {
  return tr(
    "Rechnung bis 250 € brutto: Empfänger, Rechnungsnummer und gesonderter Steuerbetrag dürfen fehlen (§ 33 UStDV).",
    "Invoice up to €250 gross: recipient, invoice number and a separate tax amount may be omitted (§ 33 UStDV).",
    "Factura de hasta 250 € brutos: pueden faltar destinatario, número de factura e importe del impuesto por separado (§ 33 UStDV).",
  );
}
