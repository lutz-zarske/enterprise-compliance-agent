import type { DocumentDetail, ScoreCheck } from "../types/api";
import { formatDate, formatMoney } from "./format";
import { getActiveLocale, translateDynamic } from "./i18n";

/** Maengel, die der Lieferant beheben kann: formelle Pflichtangaben und Rechenfehler. */
export function correctionDefects(document: DocumentDetail | null): ScoreCheck[] {
  if (!document?.scorecard || document.extraction?.doc_type !== "invoice") return [];
  return document.scorecard.tiles
    .filter((tile) => tile.key === "formal" || tile.key === "math")
    .flatMap((tile) => tile.checks)
    .filter((check) => check.status === "fail");
}

/**
 * Entwurf einer Korrekturanforderung an den Lieferanten - deterministisch aus
 * dem Pruefergebnis, ohne Sprachmodell.
 */
export function buildCorrectionRequest(document: DocumentDetail): string {
  const loc = getActiveLocale();
  const ex = document.extraction;
  const num = ex?.document_number;
  const rawDate = ex?.document_date ? formatDate(ex.document_date) : "";
  const rawAmount = ex?.total_amount != null ? formatMoney(ex.total_amount, ex.currency) : "";

  const defects = correctionDefects(document).map((check, index) => {
    const label = translateDynamic(check.label, loc);
    const reason = translateDynamic(check.risk_note ?? check.detail ?? "", loc);
    const norm = check.legal_reference && !label.includes(check.legal_reference) ? ` (${check.legal_reference})` : "";
    return `${index + 1}. ${label}${norm}${reason ? `\n   ${reason}` : ""}`;
  });

  if (loc === "en") {
    const number = num ? `No. ${num}` : `"${document.filename}"`;
    const date = rawDate ? ` dated ${rawDate}` : "";
    const amount = rawAmount ? ` in the amount of ${rawAmount}` : "";
    return [
      `Subject: Request for corrected invoice – Invoice ${number}${date}`,
      "",
      `To: ${ex?.sender ?? "[Supplier]"}`,
      "",
      "Dear Sir or Madam,",
      "",
      `During compliance verification of your invoice ${number}${date}${amount}, we identified the following issues that require correction or clarification prior to payment:`,
      "",
      ...defects,
      "",
      "Please send us a corrected invoice (§ 31 (5) UStDV / § 14 (4) German VAT Act). Payment is temporarily on hold until receipt, as input VAT deduction (§ 15 UStG) requires all mandatory disclosures. Bank details are verified via an established contact channel before payout.",
      "",
      "Please let us know if you have any questions.",
      "",
      "Kind regards,",
      "[Name, Department]",
    ].join("\n");
  }

  if (loc === "es") {
    const number = num ? `N.º ${num}` : `"${document.filename}"`;
    const date = rawDate ? ` de fecha ${rawDate}` : "";
    const amount = rawAmount ? ` por importe de ${rawAmount}` : "";
    return [
      `Asunto: Solicitud de factura rectificativa – Factura ${number}${date}`,
      "",
      `Para: ${ex?.sender ?? "[Proveedor]"}`,
      "",
      "Estimados señores:",
      "",
      `Durante la verificación formal de su factura ${number}${date}${amount}, hemos detectado los siguientes puntos que deben subsanarse antes del pago:`,
      "",
      ...defects,
      "",
      "Les rogamos que nos remitan una factura rectificativa (§ 31 (5) UStDV / § 14 (4) UStG). Hasta su recepción suspenderemos el pago, ya que la deducción del IVA soportado (§ 15 UStG) exige todos los requisitos legales. Los datos bancarios se verifican por un canal contrastado antes de autorizar pagos.",
      "",
      "Quedamos a su disposición para cualquier aclaración.",
      "",
      "Atentamente,",
      "[Nombre, Departamento]",
    ].join("\n");
  }

  const number = num ? `Nr. ${num}` : `„${document.filename}“`;
  const date = rawDate ? ` vom ${rawDate}` : "";
  const amount = rawAmount ? ` über ${rawAmount}` : "";
  return [
    `Betreff: Bitte um berichtigte Rechnung – Rechnung ${number}${date}`,
    "",
    `An: ${ex?.sender ?? "[Lieferant]"}`,
    "",
    "Sehr geehrte Damen und Herren,",
    "",
    `bei der Prüfung Ihrer Rechnung ${number}${date}${amount} haben wir folgende Punkte festgestellt, die wir vor der Zahlung korrigiert bzw. geklärt benötigen:`,
    "",
    ...defects,
    "",
    "Wir bitten Sie, uns eine berichtigte Rechnung zu übermitteln (§ 31 Abs. 5 UStDV). Bis zum Eingang stellen wir die Zahlung zurück, da der Vorsteuerabzug nach § 15 UStG eine Rechnung mit allen Angaben nach § 14 Abs. 4 UStG voraussetzt. Bankverbindungen gleichen wir vor jeder Zahlung über einen bekannten Kontaktweg ab.",
    "",
    "Für Rückfragen stehen wir gern zur Verfügung.",
    "",
    "Mit freundlichen Grüßen",
    "[Name, Abteilung]",
  ].join("\n");
}
