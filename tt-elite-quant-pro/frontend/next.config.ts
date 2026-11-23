import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone server bundle for the Docker image (set NEXT_OUTPUT=standalone); `npm start` uses the regular build.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  reactStrictMode: true,
  poweredByHeader: false,
  // The browser calls /api/* on this same origin; the Next server proxies it to the backend. One URL then works on
  // the Mac (localhost), on a phone over home Wi-Fi (http://<mac>.local:3000) and behind an HTTPS proxy.
  async rewrites() {
    const target = (process.env.API_INTERNAL_URL || "http://localhost:8000").replace(/\/$/, "");
    return [{ source: "/api/:path*", destination: `${target}/api/:path*` }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
