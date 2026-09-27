import assert from "node:assert/strict";
import { test } from "node:test";
import { sha256Hex } from "./documents.ts";
import { type SessionInfo, sessionState } from "./session.ts";

const issued = Date.parse("2026-01-01T00:00:00Z");
const info: SessionInfo = {
  issued_at: "2026-01-01T00:00:00Z",
  expires_at: "2026-01-02T00:00:00Z",
  csrf_token: "c".repeat(64),
};
const at = (seconds: number) => issued + seconds * 1000;

test("a fresh session is used as is", () => {
  assert.equal(sessionState(info, at(60)), "valid");
});

test("past half its lifetime the session is refreshed", () => {
  assert.equal(sessionState(info, at(43_200)), "refresh");
  assert.equal(sessionState(info, at(86_399)), "refresh");
});

test("expired or malformed sessions start a new one", () => {
  assert.equal(sessionState(info, at(86_400)), "expired");
  assert.equal(sessionState({ ...info, expires_at: "not a date" }, at(0)), "expired");
  assert.equal(sessionState({ ...info, csrf_token: "" }, at(0)), "expired");
});

test("upload checksum matches SHA-256", async () => {
  const hex = await sha256Hex(new TextEncoder().encode("abc").buffer as ArrayBuffer);
  assert.equal(hex, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
});
