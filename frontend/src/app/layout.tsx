import type { Metadata, Viewport } from "next";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";
import { ThemeProvider } from "../components/ThemeProvider";

export const metadata: Metadata = {
  title: "Compliance Agent | VO (EU) 2024/1689 · § 14 UStG",
  description:
    "Revisionssichere Prüfung von Rechnungen und Verträgen: EU AI Act, § 14 UStG, DSGVO – lokal oder über ein Privacy Gateway.",
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
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
