import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";

const WEB_ROOT = path.resolve(import.meta.dirname, "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "..", "..");

function readText(relPath: string, root = WEB_ROOT): string {
  const fullPath = path.join(root, relPath);
  return fs.readFileSync(fullPath, "utf-8");
}

test("all required legal pages exist in the web application", () => {
  const requiredPages = [
    "app/privacy/page.tsx",
    "app/terms/page.tsx",
    "app/acceptable-use/page.tsx",
    "app/security/page.tsx",
    "app/copyright/page.tsx",
  ];
  for (const page of requiredPages) {
    const fullPath = path.join(WEB_ROOT, page);
    assert.ok(fs.existsSync(fullPath), `Expected ${page} to exist`);
  }
});

test("LEGAL_HUMAN_REVIEW.md exists in repository root with required review sections", () => {
  const reviewDoc = readText("LEGAL_HUMAN_REVIEW.md", REPO_ROOT);
  assert.match(reviewDoc, /Operator Legal Name/);
  assert.match(reviewDoc, /Operator Physical Address/);
  assert.match(reviewDoc, /Privacy Inquiries & Data Rights Contact/);
  assert.match(reviewDoc, /Security & Responsible Disclosure Contact/);
  assert.match(reviewDoc, /Copyright & Takedown Agent Contact/);
  assert.match(reviewDoc, /Document Retention Duration Confirmation/);
  assert.match(reviewDoc, /Governing Law & Jurisdiction/);
  assert.match(reviewDoc, /Age & Eligibility Policy/);
  assert.match(reviewDoc, /Legal Basis Assessment/);
});

test("legal pages do not fabricate operator legal names or contact emails", () => {
  const legalFiles = [
    "app/privacy/page.tsx",
    "app/terms/page.tsx",
    "app/acceptable-use/page.tsx",
    "app/security/page.tsx",
    "app/copyright/page.tsx",
  ];

  const forbiddenFabrications = [
    /Prospect Inc/i,
    /Prospect LLC/i,
    /Prospect Corp/i,
    /Prospect Ltd/i,
    /privacy@prospect\.com/i,
    /legal@prospect\.com/i,
    /support@prospect\.com/i,
    /security@prospect\.com/i,
    /contact@prospect\.com/i,
    /admin@prospect\.com/i,
  ];

  for (const file of legalFiles) {
    const content = readText(file);
    for (const forbidden of forbiddenFabrications) {
      assert.doesNotMatch(
        content,
        forbidden,
        `File ${file} should not contain fabricated fact matching ${forbidden}`,
      );
    }
    // Must contain explicit human review placeholders
    assert.match(
      content,
      /\[REQUIRES HUMAN INPUT|\[REQUIRES HUMAN DECISION|\[REQUIRES VERIFICATION/,
      `File ${file} must include explicit human review placeholders`,
    );
  }
});

test("legal pages do not overstate compliance or security", () => {
  const legalFiles = [
    "app/privacy/page.tsx",
    "app/terms/page.tsx",
    "app/acceptable-use/page.tsx",
    "app/security/page.tsx",
    "app/copyright/page.tsx",
  ];

  const overstatements = [
    /fully GDPR compliant/i,
    /fully UU PDP compliant/i,
    /legally compliant/i,
    /100% secure/i,
    /guaranteed accurate/i,
    /zero data loss/i,
    /100% uptime/i,
  ];

  for (const file of legalFiles) {
    const content = readText(file);
    for (const pattern of overstatements) {
      assert.doesNotMatch(
        content,
        pattern,
        `File ${file} must not contain compliance overstatement matching ${pattern}`,
      );
    }
  }
});

test("Privacy Policy documents actual implementation and retention truth", () => {
  const privacy = readText("app/privacy/page.tsx");
  assert.match(privacy, /__Host-prospect_session/);
  assert.match(privacy, /30 days/);
  assert.match(privacy, /DOCUMENT_RETENTION_DAYS/);
  assert.match(privacy, /WORKSPACE_GRACE_HOURS/);
  assert.match(privacy, /FAILED_DOCUMENT_RETENTION_HOURS/);
  assert.match(privacy, /ON DELETE CASCADE/);
  assert.match(privacy, /50 MB/);
  assert.match(privacy, /No Generative AI or LLM Pipeline/);
  assert.match(privacy, /No Model Training/);
});

test("Terms of Use includes mandatory financial analysis and accuracy disclaimers", () => {
  const terms = readText("app/terms/page.tsx");
  assert.match(terms, /Mandatory Disclaimer/);
  assert.match(terms, /Investment Disclaimer/);
  assert.match(terms, /Original Documents Remain Authoritative/);
  assert.match(terms, /You Retain Ownership of Your Documents/);
  assert.match(terms, /Limited Operational License/);
  assert.match(terms, /AS IS/);
  assert.match(terms, /AS AVAILABLE/);
});

test("root layout renders persistent footer linking to all legal pages", () => {
  const layout = readText("app/layout.tsx");
  assert.match(layout, /<footer/);
  assert.match(layout, /href="\/privacy"/);
  assert.match(layout, /href="\/terms"/);
  assert.match(layout, /href="\/acceptable-use"/);
  assert.match(layout, /href="\/security"/);
  assert.match(layout, /href="\/copyright"/);
});

test("upload component contains pre-upload acknowledgement linking to legal policies", () => {
  const upload = readText("components/upload.tsx");
  assert.match(upload, /right and authority to submit this document/);
  assert.match(upload, /href="\/privacy"/);
  assert.match(upload, /href="\/terms"/);
});

test("legal pages do not expose hardcoded secrets or environment tokens", () => {
  const legalFiles = [
    "app/privacy/page.tsx",
    "app/terms/page.tsx",
    "app/acceptable-use/page.tsx",
    "app/security/page.tsx",
    "app/copyright/page.tsx",
  ];

  const secretPatterns = [
    /postgresql:\/\//i,
    /postgres:\/\//i,
    /sk-[a-zA-Z0-9]{20,}/,
    /r2\.cloudflarestorage\.com/,
  ];

  for (const file of legalFiles) {
    const content = readText(file);
    for (const pattern of secretPatterns) {
      assert.doesNotMatch(content, pattern, `Secret leak pattern ${pattern} found in ${file}`);
    }
  }
});
