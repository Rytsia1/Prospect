import assert from "node:assert/strict";
import { test } from "node:test";
import { contentSecurityPolicy, originOnly } from "./csp.ts";

const directives = (csp: string) =>
  new Map(csp.split("; ").map((d) => [d.split(" ")[0], d.split(" ").slice(1)]));

test("production scripts need the nonce: no inline, eval or wildcard", () => {
  const csp = directives(
    contentSecurityPolicy("abc", { dev: false, storageOrigin: "https://s.example" }),
  );
  assert.deepEqual(csp.get("script-src"), ["'self'", "'nonce-abc'", "'strict-dynamic'"]);
  for (const [, sources] of csp) assert.ok(!sources.includes("*"));
  assert.deepEqual(csp.get("img-src"), ["'self'"]);
  assert.deepEqual(csp.get("object-src"), ["'none'"]);
  assert.deepEqual(csp.get("frame-ancestors"), ["'none'"]);
  assert.deepEqual(csp.get("base-uri"), ["'self'"]);
  assert.deepEqual(csp.get("form-action"), ["'self'"]);
  assert.deepEqual(csp.get("connect-src"), ["'self'", "https://s.example"]);
  assert.ok(csp.has("upgrade-insecure-requests"));
});

test("only next dev gets 'unsafe-eval'", () => {
  assert.match(contentSecurityPolicy("n", { dev: true }), /script-src [^;]*'unsafe-eval'/);
  assert.doesNotMatch(contentSecurityPolicy("n", { dev: false }), /unsafe-eval/);
});

test("the storage origin is reduced to a bare http(s) origin", () => {
  assert.equal(originOnly("https://acct.r2.example.com/bucket?x=1"), "https://acct.r2.example.com");
  assert.equal(originOnly("https://a.example; script-src *"), undefined);
  assert.equal(originOnly("javascript:alert(1)"), undefined);
  assert.equal(originOnly(undefined), undefined);
});
