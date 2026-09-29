import { type NextRequest, NextResponse } from "next/server";
import { contentSecurityPolicy, originOnly } from "@/lib/csp";
import { proxyHeaders } from "@/lib/proxy";

// Where this app proxies /api/v1. Unset on Vercel with the `api` service: vercel.json routes
// /api/v1/* to it before this app sees the request (docs/ADR-006). next.config.ts requires it for
// other production builds; development defaults to a local API.
const API_ORIGIN =
  process.env.API_ORIGIN ??
  (process.env.NODE_ENV === "production" ? undefined : "http://localhost:8000");

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (API_ORIGIN && pathname.startsWith("/api/v1/")) {
    // Same-origin API proxy: the browser never talks to the API directly, and only this proxy
    // can tell the API who the visitor is (lib/proxy.ts). The PDF itself never comes through
    // here: it goes straight from the browser to storage with a signed URL.
    return NextResponse.rewrite(new URL(pathname + search, API_ORIGIN), {
      request: {
        headers: proxyHeaders(
          request.headers,
          process.env.TRUSTED_PROXY_SECRET,
          process.env.VERCEL === "1",
        ),
      },
    });
  }
  // Pages: a fresh CSP nonce per request; Next adds it to its own scripts while rendering.
  const nonce = btoa(crypto.randomUUID());
  const csp = contentSecurityPolicy(nonce, {
    dev: process.env.NODE_ENV === "development",
    storageOrigin: originOnly(process.env.STORAGE_ORIGIN),
  });
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", csp);
  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  // Pages and the API proxy; not static assets or prefetches.
  matcher: [
    {
      source: "/((?!_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
