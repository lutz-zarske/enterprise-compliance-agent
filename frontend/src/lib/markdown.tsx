import React from "react";

/**
 * Schlankes, sicheres Markdown fuer Copilot-Antworten - ohne Abhaengigkeit und ohne
 * ``dangerouslySetInnerHTML``: Absaetze, Aufzaehlungen (- / 1.), Zwischenueberschriften
 * (### ), **fett**, *kursiv*, `Code`.  Zeilenverweise "[Z. 4]" bzw. "[Z. 4-6]" werden zu
 * Knoepfen, die die Zeile im Belegtext anspringen.
 */
export type CiteHandler = (line: number) => void;

const INLINE = /(\[Z\.\s?\d+(?:\s?[-–]\s?\d+)?\]|\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;

function inline(text: string, onCite: CiteHandler | undefined, keyBase: string): React.ReactNode[] {
  return text.split(INLINE).filter(Boolean).map((part, index) => {
    const key = `${keyBase}-${index}`;
    const cite = /^\[Z\.\s?(\d+)(?:\s?[-–]\s?(\d+))?\]$/.exec(part);
    if (cite) {
      const line = Number(cite[1]);
      const label = part.slice(1, -1);
      return onCite ? (
        <button
          key={key}
          type="button"
          onClick={() => onCite(line)}
          title={`Zeile ${line} im Beleg anzeigen`}
          className="mx-0.5 inline-flex items-center rounded border border-accent-line bg-accent-soft px-1 text-xs font-medium tabular-nums text-accent transition-colors duration-150 hover:border-accent"
        >
          {label}
        </button>
      ) : (
        <span key={key} className="mx-0.5 rounded border border-accent-line bg-accent-soft px-1 text-xs tabular-nums text-accent">{label}</span>
      );
    }
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={key} className="font-semibold text-fg">{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={key}>{part.slice(1, -1)}</code>;
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) return <em key={key}>{part.slice(1, -1)}</em>;
    return <React.Fragment key={key}>{part}</React.Fragment>;
  });
}

export function Markdown({ text, onCite }: { text: string; onCite?: CiteHandler }) {
  const blocks: React.ReactNode[] = [];
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  let list: { ordered: boolean; items: string[] } | null = null;
  let paragraph: string[] = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const key = `p${blocks.length}`;
    blocks.push(<p key={key}>{inline(paragraph.join(" "), onCite, key)}</p>);
    paragraph = [];
  };
  const flushList = () => {
    if (!list) return;
    const key = `l${blocks.length}`;
    const items = list.items.map((item, index) => <li key={`${key}-${index}`}>{inline(item, onCite, `${key}-${index}`)}</li>);
    blocks.push(list.ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>);
    list = null;
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const heading = /^#{1,4}\s+(.*)$/.exec(line);
    if (!line.trim()) {
      flushParagraph();
      flushList();
    } else if (heading) {
      flushParagraph();
      flushList();
      const key = `h${blocks.length}`;
      blocks.push(<h4 key={key}>{inline(heading[1], onCite, key)}</h4>);
    } else if (bullet || numbered) {
      flushParagraph();
      const ordered = Boolean(numbered);
      if (list && list.ordered !== ordered) flushList();
      list ??= { ordered, items: [] };
      list.items.push((bullet ?? numbered)![1]);
    } else if (list && /^\s{2,}\S/.test(raw)) {
      list.items[list.items.length - 1] += ` ${line.trim()}`;
    } else {
      flushList();
      paragraph.push(line.trim());
    }
  }
  flushParagraph();
  flushList();
  return <div className="md-answer">{blocks}</div>;
}
