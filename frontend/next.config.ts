import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone-Ausgabe fuer ein schlankes Docker-Image (node server.js).
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  // Kein schwebendes „N“-Badge im Entwicklungsmodus.
  devIndicators: false,
};

export default nextConfig;
