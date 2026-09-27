// Session token lifecycle on the client. The server is the authority (it verifies the signature
// and can revoke a session); the client only reads the signed times to refresh before expiry.
// Token: v1.<session_id>.<issued_at>.<expires_at>.<signature>  (times in Unix seconds)

export type TokenState = "valid" | "refresh" | "expired";

/** valid: use it; refresh: past half its lifetime, swap it; expired/unreadable: start over. */
export function tokenState(token: string, nowMs: number): TokenState {
  const parts = token.split(".");
  const issued = Number(parts[2]) * 1000;
  const expires = Number(parts[3]) * 1000;
  if (parts.length !== 5 || parts[0] !== "v1" || !(expires > issued) || nowMs >= expires) {
    return "expired";
  }
  return nowMs >= issued + (expires - issued) / 2 ? "refresh" : "valid";
}
