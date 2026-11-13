import type { NextConfig } from "next";

// Standalone-Ausgabe nur fuer das schlanke Docker-Image (NEXT_STANDALONE=1 -> node server.js),
// damit `npm run start` im lokalen Schnellstart ohne Next.js-Warnung laeuft.
const nextConfig: NextConfig = {
  ...(process.env.NEXT_STANDALONE === "1" ? { output: "standalone" } : {}),
  poweredByHeader: false,
  reactStrictMode: true,
  // Kein schwebendes „N“-Badge im Entwicklungsmodus.
  devIndicators: false,
  // Aufruf ueber http://127.0.0.1:3001 (empfohlen unter Windows) ohne Cross-Origin-Warnung im Dev-Server.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // Ein Build mit Lint- oder Typfehlern schlaegt fehl - nie still uebergehen.
  eslint: { ignoreDuringBuilds: false },
  typescript: { ignoreBuildErrors: false },
};

export default nextConfig;
