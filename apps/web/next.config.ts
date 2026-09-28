import type { NextConfig } from "next";

// The browser only ever talks to this origin: middleware.ts proxies /api/v1/* to the API, so the
// session cookie is first-party (SameSite=Strict, HttpOnly) and the API needs no credentialed
// CORS. API_ORIGIN and TRUSTED_PROXY_SECRET are server-side configuration (never NEXT_PUBLIC_).
const production = process.env.NODE_ENV === "production";
const apiOrigin = process.env.API_ORIGIN ?? (production ? undefined : "http://localhost:8000");
if (!apiOrigin) {
  throw new Error("Set API_ORIGIN (e.g. https://api.prospect.example) for production builds.");
}
if (process.env.VERCEL === "1" && !process.env.TRUSTED_PROXY_SECRET) {
  // Without it the API cannot tell visitors apart and rate limits them all as one.
  throw new Error("Set TRUSTED_PROXY_SECRET (the same value as the API's) on Vercel.");
}

// Content-Security-Policy is per request (it carries a nonce): see middleware.ts.
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  // Vercel serves production over HTTPS only; browsers ignore HSTS on plain http.
  ...(production
    ? [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }]
    : []),
];

const config: NextConfig = {
  poweredByHeader: false,
  async headers() {
    // Pages only: proxied API responses keep the API's own, stricter headers.
    return [{ source: "/:path((?!api/).*)", headers: securityHeaders }];
  },
};

export default config;
