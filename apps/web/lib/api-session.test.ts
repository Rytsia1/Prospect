import assert from "node:assert/strict";
import { test } from "node:test";

// A first visit: no cookie session, nothing in localStorage. Its own file, so the module's
// session state starts empty.
const requests: string[] = [];
Object.assign(globalThis, {
  localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  fetch: async (url: string, init: RequestInit = {}) => {
    requests.push(`${(init.method ?? "GET").toUpperCase()} ${url}`);
    return new Response(JSON.stringify({ error: { code: "unauthorized" } }), { status: 401 });
  },
});

const { hasSession } = await import("./api.ts");

test("checking for a workspace never starts one", async () => {
  assert.equal(await hasSession(), false);
  assert.deepEqual(requests, ["GET /api/v1/sessions/current"]); // no POST /api/v1/sessions
});
