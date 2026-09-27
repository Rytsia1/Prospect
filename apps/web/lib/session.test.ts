import assert from "node:assert/strict";
import { test } from "node:test";
import { sha256Hex } from "./documents.ts";
import { tokenState } from "./session.ts";

const issued = 1_700_000_000;
const token = `v1.3f1c.${issued}.${issued + 86_400}.abcdef`;
const at = (seconds: number) => (issued + seconds) * 1000;

test("a fresh token is used as is", () => {
  assert.equal(tokenState(token, at(60)), "valid");
});

test("past half its lifetime the token is refreshed", () => {
  assert.equal(tokenState(token, at(43_200)), "refresh");
  assert.equal(tokenState(token, at(86_399)), "refresh");
});

test("expired, legacy and malformed tokens start a new session", () => {
  assert.equal(tokenState(token, at(86_400)), "expired");
  assert.equal(tokenState("0b7ad18e-uuid.signature", at(0)), "expired"); // pre-hardening format
  assert.equal(tokenState("v1.a.b.c.d", at(0)), "expired");
  assert.equal(tokenState("", at(0)), "expired");
});

test("upload checksum matches SHA-256", async () => {
  const hex = await sha256Hex(new TextEncoder().encode("abc").buffer as ArrayBuffer);
  assert.equal(hex, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
});
