import assert from "node:assert/strict";
import { test } from "node:test";
import { parseTheme } from "./theme.ts";

test("theme defaults to light; only an exact 'dark' cookie turns dark mode on", () => {
  assert.equal(parseTheme("dark"), "dark");
  for (const value of [undefined, "", "light", "DARK", "dark;", " dark", "<script>"]) {
    assert.equal(parseTheme(value), "light");
  }
});
