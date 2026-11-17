import type { Metadata, Viewport } from "next";
// Schriften strikt lokal aus dem npm-Bundle - kein CDN, kein Netz beim Build (Docker, Offline-Betrieb).
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource/ibm-plex-serif/latin-500.css";
import "@fontsource/ibm-plex-serif/latin-600.css";
import "./globals.css";
import { SplashAbbau } from "../components/SplashAbbau";
import { ThemeProvider } from "../components/ThemeProvider";
import { I18nProvider } from "../lib/i18n";

export const metadata: Metadata = {
  title: "Enterprise Compliance Agent",
  description:
    "Revisionssichere Vorprüfung von Rechnungen und Verträgen: § 14 UStG, E-Rechnung nach EN 16931, EU AI Act und DSGVO – lokal oder über ein Privacy Gateway.",
  icons: {
    icon: [
      { url: "/compliance-logo-transparent.png", type: "image/png", sizes: "256x256" },
      { url: "/compliance-logo.png", type: "image/png", sizes: "256x256" },
    ],
    apple: "/compliance-logo.png",
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#07080c" },
    { media: "(prefers-color-scheme: light)", color: "#f8fafc" },
  ],
};

/**
 * Setzt das Farbschema vor dem ersten Paint (kein Aufblitzen des falschen Themes).
 * Wahl dark | light | system; Standard ist der dunkle Arbeitsmodus.
 */
const themeScript = `(function(){try{var t=localStorage.getItem("eca-theme");var d=t==="light"?false:t==="system"?!window.matchMedia("(prefers-color-scheme: light)").matches:true;document.documentElement.classList.toggle("dark",d);document.documentElement.style.colorScheme=d?"dark":"light";var l=localStorage.getItem("eca-lang");if(l==="en"||l==="es"||l==="de")document.documentElement.lang=l;}catch(e){document.documentElement.classList.add("dark");}})();`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="de" className="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="bg-bg text-fg antialiased">
        {/* Kaltstart-Splash: deckt den ersten Paint ab, bis die Startdaten geladen sind (SplashAbbau). */}
        <div id="eca-splash" className="eca-splash no-print" aria-hidden="true">
          <div className="eca-splash-inhalt">
            {/* eslint-disable-next-line @next/next/no-img-element -- vor der Hydration, ohne next/image-Laufzeit */}
            <img src="/compliance-logo-transparent.png" alt="" width={48} height={48} className="eca-splash-logo" />
            <span className="eca-splash-name">Enterprise Compliance Agent</span>
            <span className="eca-splash-linie" />
          </div>
        </div>
        <SplashAbbau />
        <I18nProvider>
          <ThemeProvider>{children}</ThemeProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
