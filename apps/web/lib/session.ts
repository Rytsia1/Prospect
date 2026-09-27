// Session lifecycle on the client. The token lives only in an HttpOnly cookie that JavaScript
// cannot read; the API tells the page the session's times and its CSRF token (SessionInfo).
// The server stays the authority: it verifies the signature and can revoke a session.

export type SessionInfo = { issued_at: string; expires_at: string; csrf_token: string };
export type SessionState = "valid" | "refresh" | "expired";

/** valid: use it; refresh: past half its lifetime, swap it; expired/unreadable: start over. */
export function sessionState(info: SessionInfo, nowMs: number): SessionState {
  const issued = Date.parse(info.issued_at);
  const expires = Date.parse(info.expires_at);
  if (!(expires > issued) || nowMs >= expires || !info.csrf_token) return "expired";
  return nowMs >= issued + (expires - issued) / 2 ? "refresh" : "valid";
}
