import type { DocumentDetail, ScoreCheck } from "../types/api";
import { formatDate, formatMoney } from "./format";

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
 * dem Pruefergebnis, ohne Sprachmodell. Die Pruefperson bearbeitet und
 * versendet ihn selbst (menschliche Aufsicht, Art. 14 VO (EU) 2024/1689).
 */
export function buildCorrectionRequest(document: DocumentDetail): string {
  const ex = document.extraction;
  const number = ex?.document_number ? `Nr. ${ex.document_number}` : `„${document.filename}“`;
  const date = ex?.document_date ? ` vom ${formatDate(ex.document_date)}` : "";
  const amount = ex?.total_amount != null ? ` über ${formatMoney(ex.total_amount, ex.currency)}` : "";
  const defects = correctionDefects(document).map((check, index) => {
    const reason = check.risk_note ?? check.detail ?? "";
    const norm = check.legal_reference && !check.label.includes(check.legal_reference) ? ` (${check.legal_reference})` : "";
    return `${index + 1}. ${check.label}${norm}${reason ? `\n   ${reason}` : ""}`;
  });
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
