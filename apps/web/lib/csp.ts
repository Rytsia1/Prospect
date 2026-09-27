// Content-Security-Policy for the web app, sent by middleware.ts with a fresh nonce per request.
//
// Scripts: only Next's own, which carry the nonce ('strict-dynamic' lets them load their chunks).
// No inline or third-party scripts exist, and no 'unsafe-inline'/'unsafe-eval' in production
// ('unsafe-eval' only for `next dev`, which needs it for React's debugging).
// Styles: 'unsafe-inline' is required for React `style` attributes (charts, progress bars), which
// cannot carry a nonce; style injection cannot run script.
// connect-src: this origin (the /api proxy) plus the storage origin that receives signed uploads.
// Nothing may frame the app, and it frames nothing (PDFs open in a new tab from storage).

export type CspOptions = { dev: boolean; storageOrigin?: string };

export function contentSecurityPolicy(nonce: string, { dev, storageOrigin }: CspOptions): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self'", // the app has no data:/blob: images (export blobs are downloads)
    "font-src 'self'",
    `connect-src 'self'${storageOrigin ? ` ${storageOrigin}` : ""}`,
    "object-src 'none'",
    "frame-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    ...(dev ? [] : ["upgrade-insecure-requests"]),
  ].join("; ");
}

/** Accept only an http(s) origin for the CSP (a stray path, quote or ';' would break it). */
export function originOnly(value: string | undefined): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.origin : undefined;
  } catch {
    return undefined;
  }
}
