import type { NextConfig } from "next";

// The browser calls the API on its own origin at /v1/*. In production the load balancer
// routes /v1/* straight to FastAPI (so the API sees real client IPs for rate limiting, and
// uploads never pass through Node). This rewrite is the same routing for local development
// and simple single-host setups. Rewrites are resolved at build time: set API_ORIGIN when
// running `next build`. Same-origin keeps CORS out, lets downloads work, and allows a strict
// `connect-src 'self'` CSP.
const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [
      // Only the versioned API surface is exposed; /healthz, /readyz, /docs stay internal.
      { source: "/v1/:path*", destination: `${API_ORIGIN}/v1/:path*` },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Permissions-Policy",
            // The app never needs the camera: users choose an existing photo.
            value: "camera=(), microphone=(), geolocation=(), interest-cohort=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
