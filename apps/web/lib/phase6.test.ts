import assert from "node:assert/strict";
import test from "node:test";
import { anomalySeverityBadge, formatConfidence, sectionDiffBadge } from "./phase6.ts";

test("anomaly severity badge maps symbols and labels deterministically", () => {
  const err = anomalySeverityBadge("error");
  assert.equal(err.symbol, "✕");
  assert.equal(err.label, "Error");
  assert.ok(err.className.includes("text-red-700"));

  const warn = anomalySeverityBadge("warning");
  assert.equal(warn.symbol, "⚠");
  assert.equal(warn.label, "Warning");
  assert.ok(warn.className.includes("text-amber-700"));

  const info = anomalySeverityBadge("info");
  assert.equal(info.symbol, "ℹ");
  assert.equal(info.label, "Info");
  assert.ok(info.className.includes("text-blue-700"));
});

test("section diff badge formats addition, removal, change, and unchanged status", () => {
  const added = sectionDiffBadge("added");
  assert.equal(added.symbol, "+");
  assert.equal(added.label, "Added");

  const removed = sectionDiffBadge("removed");
  assert.equal(removed.symbol, "−");
  assert.equal(removed.label, "Removed");

  const changed = sectionDiffBadge("changed");
  assert.equal(changed.symbol, "~");
  assert.equal(changed.label, "Changed");

  const unchanged = sectionDiffBadge("unchanged");
  assert.equal(unchanged.symbol, "=");
  assert.equal(unchanged.label, "Unchanged");
});

test("formatConfidence returns High, Medium, Low without inventing subjective certainty", () => {
  assert.equal(formatConfidence("0.95").label, "High");
  assert.equal(formatConfidence("0.85").label, "High");
  assert.equal(formatConfidence("0.72").label, "Medium");
  assert.equal(formatConfidence("0.60").label, "Medium");
  assert.equal(formatConfidence("0.45").label, "Low");
  assert.equal(formatConfidence("0.10").label, "Low");
  assert.equal(formatConfidence("invalid").label, "Medium");
});
