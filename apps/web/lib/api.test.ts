import assert from "node:assert/strict";
import { test } from "node:test";

// A fake API behind a fake fetch: records every request the client makes.
type Call = { url: string; method: string; headers: Record<string, string> };
const calls: Call[] = [];
const hour = 3600_000;
let csrf = "csrf-1";
let rejectNextWrite = false;
let hasCookie = false;
const stored = new Map<string, string>([["prospect.session", "v1.legacy.token"]]);

Object.assign(globalThis, {
  localStorage: {
    getItem: (k: string) => stored.get(k) ?? null,
    setItem: (k: string, v: string) => stored.set(k, v),
    removeItem: (k: string) => stored.delete(k),
  },
  fetch: async (url: string, init: RequestInit = {}) => {
    const method = (init.method ?? "GET").toUpperCase();
    calls.push({ url, method, headers: { ...(init.headers as Record<string, string>) } });
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    const session = () => ({
      issued_at: new Date(Date.now() - hour).toISOString(),
      expires_at: new Date(Date.now() + 23 * hour).toISOString(),
      csrf_token: csrf,
    });
    if (url === "/api/v1/sessions/current") {
      return hasCookie ? json(session()) : json({ error: { code: "unauthorized" } }, 401);
    }
    if (url === "/api/v1/sessions" || url === "/api/v1/sessions/refresh") {
      hasCookie = true; // Set-Cookie
      return json(session(), url.endsWith("refresh") ? 200 : 201);
    }
    if (method !== "GET" && rejectNextWrite) {
      rejectNextWrite = false;
      csrf = "csrf-2"; // e.g. another tab refreshed the session
      return json({ error: { code: "csrf_failed", message: "no" } }, 403);
    }
    return json({ ok: true });
  },
});

const { api } = await import("./api.ts");

test("a legacy localStorage token is traded once for a cookie session and removed", async () => {
  await api("/documents");
  assert.equal(stored.size, 0); // nothing left in localStorage
  const exchange = calls.find((c) => c.url === "/api/v1/sessions/refresh");
  assert.equal(exchange?.headers.Authorization, "Bearer v1.legacy.token"); // same user kept
  assert.ok(!calls.some((c) => c.url === "/api/v1/sessions")); // no new anonymous user
});

test("reads carry no CSRF token; writes carry the session's", async () => {
  calls.length = 0;
  await api("/documents");
  await api("/documents", { method: "POST", body: "{}" });
  const [read, write] = calls.filter((c) => c.url === "/api/v1/documents");
  assert.equal(read.headers["X-CSRF-Token"], undefined);
  assert.equal(write.headers["X-CSRF-Token"], "csrf-1");
  assert.ok(calls.every((c) => c.url.startsWith("/api/v1/"))); // same origin, no token in URLs
  assert.ok(calls.every((c) => !("Authorization" in c.headers)));
});

test("a stale CSRF token reloads the session once and retries", async () => {
  calls.length = 0;
  rejectNextWrite = true;
  await api("/documents/x", { method: "DELETE" });
  const writes = calls.filter((c) => c.method === "DELETE");
  assert.deepEqual(
    writes.map((c) => c.headers["X-CSRF-Token"]),
    ["csrf-1", "csrf-2"],
  );
});
