/**
 * Bildmarke: Schild mit Prüfhaken auf ruhiger Kachel.  Vektor statt Rastergrafik -
 * scharf in jeder Größe; Farben kommen aus globals.css (.brand-*), passend zu Hell und Dunkel.
 */
export function BrandMark({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} className={className} aria-hidden="true" focusable="false">
      <rect x="0.5" y="0.5" width="31" height="31" rx="8" className="brand-tile" />
      <path
        d="M16 6.2 23.6 9v6.4c0 4.8-3.2 8.3-7.6 10.2-4.4-1.9-7.6-5.4-7.6-10.2V9Z"
        fill="none"
        className="brand-shield"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
      <path d="m12.4 15.9 2.6 2.6 4.8-5.1" fill="none" className="brand-check" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
