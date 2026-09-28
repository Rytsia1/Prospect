import assert from "node:assert/strict";
import { test } from "node:test";
import { CLIENT_IP_HEADER, proxyHeaders, SECRET_HEADER } from "./proxy.ts";

const spoofed = () =>
  new Headers({
    [CLIENT_IP_HEADER]: "6.6.6.6",
    [SECRET_HEADER]: "guessed",
    "x-real-ip": "203.0.113.7",
    "x-forwarded-for": "203.0.113.7, 10.0.0.1",
    cookie: "session=kept",
  });

test("on Vercel the platform's client IP is forwarded with the shared secret", () => {
  const out = proxyHeaders(spoofed(), "s3cret", true);
  assert.equal(out.get(CLIENT_IP_HEADER), "203.0.113.7");
  assert.equal(out.get(SECRET_HEADER), "s3cret");
  assert.equal(out.get("cookie"), "session=kept"); // everything else passes through
});

test("a browser can never supply the trusted headers itself", () => {
  for (const [secret, onVercel] of [
    [undefined, true],
    ["s3cret", false],
  ] as const) {
    const out = proxyHeaders(spoofed(), secret, onVercel);
    assert.equal(out.get(CLIENT_IP_HEADER), null);
    assert.equal(out.get(SECRET_HEADER), null);
  }
});

test("x-forwarded-for is used only when x-real-ip is absent, first hop only", () => {
  const headers = new Headers({ "x-forwarded-for": " 198.51.100.4 , 10.0.0.1" });
  assert.equal(proxyHeaders(headers, "s", true).get(CLIENT_IP_HEADER), "198.51.100.4");
});
