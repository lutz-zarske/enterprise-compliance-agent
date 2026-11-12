import type { Metadata, Viewport } from "next";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";
import { SplashAbbau } from "../components/SplashAbbau";
import { ThemeProvider } from "../components/ThemeProvider";

export const metadata: Metadata = {
  title: "Enterprise Compliance Agent",
  description:
    "Revisionssichere Prüfung von Rechnungen und Verträgen: EU AI Act, § 14 UStG, DSGVO – lokal oder über ein Privacy Gateway.",
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
    { media: "(prefers-color-scheme: dark)", color: "#090d16" },
    { media: "(prefers-color-scheme: light)", color: "#f8fafc" },
  ],
};

/**
 * Setzt das Theme vor dem ersten Paint (kein Aufblitzen des falschen Themes).
 * Standard ist der institutionelle Dark Mode.
 */
const themeScript = `(function(){try{var t=localStorage.getItem("eca-theme");var d=t?t==="dark":true;document.documentElement.classList.toggle("dark",d);}catch(e){document.documentElement.classList.add("dark");}})();`;

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
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
