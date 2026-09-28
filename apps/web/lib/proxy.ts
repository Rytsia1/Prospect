// Headers the web app's /api proxy (middleware.ts) sends to the API. The API believes the
// client IP only together with the shared TRUSTED_PROXY_SECRET (apps/api/app/ratelimit.py).
export const CLIENT_IP_HEADER = "x-prospect-client-ip";
export const SECRET_HEADER = "x-prospect-proxy-secret";

/**
 * The request headers to forward. A browser can never set the two trusted headers: they are
 * always removed first. The visitor's IP is taken from x-real-ip / x-forwarded-for only on
 * Vercel, whose edge overwrites those headers with the real client address; elsewhere (next
 * start, next dev) they are whatever the client sent, so no IP is forwarded and the API falls
 * back to the connection's own address.
 */
export function proxyHeaders(incoming: Headers, secret: string | undefined, onVercel: boolean) {
  const headers = new Headers(incoming);
  headers.delete(CLIENT_IP_HEADER);
  headers.delete(SECRET_HEADER);
  const ip = incoming.get("x-real-ip") ?? incoming.get("x-forwarded-for")?.split(",")[0];
  if (secret && onVercel && ip?.trim()) {
    headers.set(SECRET_HEADER, secret);
    headers.set(CLIENT_IP_HEADER, ip.trim());
  }
  return headers;
}
