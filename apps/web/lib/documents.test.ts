import assert from "node:assert/strict";
import { test } from "node:test";
import { formatBytes, isSettled, MAX_UPLOAD_BYTES, validatePdf } from "./documents.ts";

const pdf = { name: "Annual Report 2025.pdf", type: "application/pdf", size: 1024 };

test("accepts a PDF", () => {
  assert.equal(validatePdf(pdf), null);
});

test("accepts a .pdf with no browser-reported type", () => {
  assert.equal(validatePdf({ ...pdf, type: "" }), null);
});

test("rejects other types even when renamed", () => {
  assert.match(validatePdf({ ...pdf, name: "report.docx", type: "" }) ?? "", /Only PDF/);
  assert.match(validatePdf({ ...pdf, type: "application/msword" }) ?? "", /Only PDF/);
});

test("rejects empty and oversized files", () => {
  assert.match(validatePdf({ ...pdf, size: 0 }) ?? "", /empty/);
  assert.match(validatePdf({ ...pdf, size: MAX_UPLOAD_BYTES + 1 }) ?? "", /limit/);
  assert.equal(validatePdf({ ...pdf, size: MAX_UPLOAD_BYTES }), null);
});

test("only READY and FAILED stop polling", () => {
  assert.equal(isSettled("READY"), true);
  assert.equal(isSettled("FAILED"), true);
  assert.equal(isSettled("UPLOADED"), false);
  assert.equal(isSettled("UPLOADING"), false);
});

test("formats sizes", () => {
  assert.equal(formatBytes(512), "512 B");
  assert.equal(formatBytes(1536), "1.5 KB");
  assert.equal(formatBytes(12.5 * 1024 * 1024), "12.5 MB");
});
