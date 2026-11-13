import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone-Ausgabe fuer ein schlankes Docker-Image (node server.js).
  output: "standalone",
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
