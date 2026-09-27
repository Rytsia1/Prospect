import { type NextRequest, NextResponse } from "next/server";
import { contentSecurityPolicy, originOnly } from "@/lib/csp";

/** A fresh CSP nonce per page request; Next adds it to its own scripts while rendering. */
export function middleware(request: NextRequest) {
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
  // Pages only: not the proxied API, static assets or prefetches.
  matcher: [
    {
      source: "/((?!api/|_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
