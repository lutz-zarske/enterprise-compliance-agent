/**
 * Fundstellen im Belegtext je Pruefkriterium (Rossum-Muster: Hover auf ein
 * Kriterium hebt die belegende Zeile hervor, Klick scrollt dorthin).
 *
 * Die Zuordnung ist deterministisch und folgt denselben Mustern wie die
 * Textbelege des Regelwerks (app/scoring.py: analyze_text). Sie arbeitet auf der
 * Inspektor-Ansicht, also auch auf geschwaerztem Text: Feldbezeichner wie
 * „Rechnungsdatum:“ bleiben stehen, nur die Werte werden zu Platzhaltern.
 */
import type { CheckStatus, DetectionSource, DocumentDetail, ScoreCheck, ScoreTile } from "../types/api";

export interface Line {
  start: number;
  /** exklusiv, ohne Zeilenumbruch */
  end: number;
}

export interface Evidence {
  /** Zeilenindizes, aufsteigend */
  lines: number[];
  /** Indizes in text_view.spans, die zusaetzlich hervorgehoben werden */
  spans: number[];
}

export type EvidenceTone = "ok" | "warn" | "bad";

export interface EvidenceIndex {
  lines: Line[];
  byCheck: Map<string, Evidence>;
  /** Rueckrichtung: welche Kriterien eine Zeile belegt */
  byLine: Map<number, string[]>;
}

export function splitLines(text: string): Line[] {
  const lines: Line[] = [];
  let start = 0;
  for (let i = 0; i <= text.length; i += 1) {
    if (i === text.length || text[i] === "\n") {
      lines.push({ start, end: i });
      start = i + 1;
    }
  }
  return lines;
}

const TAX_WORD = /\b(ust|mwst|umsatzsteuer|mehrwertsteuer)\b/i;
const ID_WORD = /id|nr\.|nummer|identifikation/i;
const TAX_ID_LABEL = /ust-?id|umsatzsteuer-?id|steuer-?nr|steuernummer|\buid\b|vat\s*(id|no)/i;
const DATE_LABEL = /rechnungsdatum|ausstellungsdatum|belegdatum|\bdatum\b/i;
const NUMBER_LABEL = /rechnung(s)?[\s-]*(nr|nummer|no)|invoice\s*(no|number)|beleg-?nr|\bnr\.\s*\S/i;
const RECIPIENT_LABEL = /empf(ä|ae)nger|rechnungsempf|leistungsempf|\bkunde\b|\ban:/i;
const ITEMS = /\bpos(ition)?\.?\s*\d|\bmenge\b|\bstk\.?|\bst(ü|ue)ck\b|\banzahl\b|leistungsbeschreibung|\bartikel\b/i;
const SERVICE_DATE = /(leistungs|liefer)(datum|zeitraum|zeitpunkt|tag)|leistung\s+erbracht|zeitraum\s*:/i;
const NET = /netto/i;
const PERCENT = /\d\s?%/;
const EXEMPTION = /steuerfrei|reverse[\s-]?charge|steuerschuldnerschaft des leistungsempf|§\s?13b|§\s?4 nr\.?|kleinunternehmer|§\s?19 ustg|innergemeinschaftliche lieferung/i;
const GROSS = /brutto|gesamtbetrag|rechnungsbetrag|endbetrag|zu zahlen/i;
const IBAN_LABEL = /\biban\b|bankverbindung/i;
const LEITWEG = /leitweg/i;

/** Ton der Hervorhebung: Gruen konform, Gelb Pruefhinweis oder reiner KI-Nachweis, Rot Verstoss. */
export function evidenceTone(status: CheckStatus, source: DetectionSource | null): EvidenceTone | null {
  if (status === "fail") return "bad";
  if (status === "warn") return "warn";
  if (status === "pass") return source === "llm" ? "warn" : "ok";
  return null;
}

export const EVIDENCE_LABELS: Record<EvidenceTone, string> = {
  ok: "Konform",
  warn: "Prüfhinweis",
  bad: "Verstoß",
};

export function toneLabel(check: ScoreCheck): string {
  const tone = evidenceTone(check.status, check.evidence_source);
  if (!tone) return "Nicht einschlägig";
  if (tone === "warn" && check.status === "pass") return "KI-Vorschlag – manuell sichten";
  return EVIDENCE_LABELS[tone];
}

const RANK: Record<EvidenceTone, number> = { ok: 0, warn: 1, bad: 2 };

export function worstTone(tones: (EvidenceTone | null)[]): EvidenceTone | null {
  return tones.reduce<EvidenceTone | null>((worst, tone) => (tone && (!worst || RANK[tone] > RANK[worst]) ? tone : worst), null);
}

/** Pruefkacheln, deren Kriterien im Inspektor als Zeilen erscheinen. */
export const TILE_TABS: Partial<Record<ScoreTile["key"], "ustg" | "facts" | "aiact">> = {
  formal: "ustg",
  math: "facts",
  regulatory: "aiact",
};

export function buildEvidence(document: DocumentDetail): EvidenceIndex {
  const view = document.text_view;
  const empty: EvidenceIndex = { lines: [], byCheck: new Map(), byLine: new Map() };
  if (!view) return empty;
  const text = view.text;
  const lines = splitLines(text);
  const lower = text.toLowerCase();
  const lineText = lines.map((line) => text.slice(line.start, line.end));

  const lineOf = (offset: number): number => {
    let lo = 0;
    let hi = lines.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (lines[mid].start <= offset) lo = mid;
      else hi = mid - 1;
    }
    return lo;
  };
  const matching = (pattern: RegExp, options: { first?: boolean; unless?: RegExp; also?: RegExp } = {}): number[] => {
    const hits: number[] = [];
    for (let i = 0; i < lineText.length; i += 1) {
      const value = lineText[i];
      if (!pattern.test(value)) continue;
      if (options.unless?.test(value)) continue;
      if (options.also && !options.also.test(value)) continue;
      hits.push(i);
      if (options.first) break;
    }
    return hits;
  };
  /** Zeilen, in denen ein extrahierter Wert woertlich steht (nur ungeschwaerzt auffindbar). */
  const containing = (value: string | null | undefined, first = true): number[] => {
    const needle = value?.trim().toLowerCase();
    if (!needle || needle.length < 3) return [];
    const hits: number[] = [];
    let index = lower.indexOf(needle);
    while (index !== -1) {
      hits.push(lineOf(index));
      if (first) break;
      index = lower.indexOf(needle, index + needle.length);
    }
    return hits;
  };
  const spansOf = (...categories: string[]): number[] =>
    view.spans.flatMap((span, index) => (categories.includes(span.category) ? [index] : []));
  const linesOfSpans = (indices: number[]): number[] => indices.map((index) => lineOf(view.spans[index].start));
  const firstOr = (...candidates: number[][]): number[] => candidates.find((hits) => hits.length) ?? [];

  const ex = document.extraction;
  const taxIdSpans = spansOf("vat_id", "tax_number");
  const ibanSpans = spansOf("iban");
  const firstAddress = spansOf("address").slice(0, 1);
  const rateLines = [...matching(TAX_WORD, { unless: ID_WORD, also: PERCENT }), ...matching(EXEMPTION)];
  const taxLines = matching(TAX_WORD, { unless: ID_WORD, also: /\d|\[betrag\]/i });

  const rules: Record<string, () => Evidence> = {
    ustg_1_sender: () => ({
      lines: [
        ...firstOr(containing(ex?.sender), linesOfSpans(spansOf("org").slice(0, 1))),
        ...linesOfSpans(firstAddress),
      ],
      spans: firstAddress,
    }),
    ustg_1_recipient: () => ({ lines: firstOr(containing(ex?.recipient), matching(RECIPIENT_LABEL, { first: true })), spans: [] }),
    ustg_2_tax_id: () => ({ lines: [...linesOfSpans(taxIdSpans), ...matching(TAX_ID_LABEL)], spans: taxIdSpans }),
    ustg_3_date: () => ({ lines: matching(DATE_LABEL, { first: true }), spans: [] }),
    ustg_4_number: () => ({ lines: firstOr(containing(ex?.document_number), matching(NUMBER_LABEL, { first: true })), spans: [] }),
    ustg_5_items: () => ({ lines: matching(ITEMS), spans: [] }),
    ustg_6_service_date: () => ({ lines: matching(SERVICE_DATE), spans: [] }),
    ustg_7_net: () => ({ lines: matching(NET), spans: [] }),
    ustg_8_rate: () => ({ lines: rateLines, spans: [] }),
    ustg_8_amount: () => ({ lines: [...taxLines, ...matching(EXEMPTION)], spans: [] }),
    leitweg_id: () => ({ lines: matching(LEITWEG), spans: [] }),
    vat_rate: () => ({ lines: rateLines, spans: [] }),
    tax_calc: () => ({ lines: taxLines, spans: [] }),
    sum_check: () => ({ lines: [...matching(NET), ...taxLines, ...matching(GROSS)], spans: [] }),
    iban_mod97: () => ({ lines: [...linesOfSpans(ibanSpans), ...matching(IBAN_LABEL)], spans: ibanSpans }),
    ai_act: () => ({
      lines: (document.compliance?.ai_act.systems ?? []).flatMap((system) => containing(system.evidence)),
      spans: [],
    }),
  };

  const byCheck = new Map<string, Evidence>();
  const byLine = new Map<number, string[]>();
  for (const tile of document.scorecard?.tiles ?? []) {
    if (!TILE_TABS[tile.key]) continue;
    for (const check of tile.checks) {
      const rule = rules[check.id];
      if (!rule || check.status === "not_applicable") continue;
      const found = rule();
      const unique = Array.from(new Set(found.lines)).sort((a, b) => a - b);
      if (!unique.length) continue;
      byCheck.set(check.id, { lines: unique, spans: found.spans });
      for (const line of unique) byLine.set(line, [...(byLine.get(line) ?? []), check.id]);
    }
  }
  return { lines, byCheck, byLine };
}
