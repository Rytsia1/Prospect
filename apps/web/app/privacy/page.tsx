import type { Metadata } from "next";
import Link from "next/link";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: "How Prospect handles, processes, and protects document and session data.",
};

export default function PrivacyPolicyPage() {
  return (
    <article className="mx-auto max-w-4xl space-y-10 py-2">
      {/* Header */}
      <header className="space-y-3 border-b border-slate-200 pb-6">
        <div className="inline-flex items-center gap-2 rounded bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800 border border-amber-200">
          <span>Notice: Baseline Draft Pending Final Human Review</span>
        </div>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Privacy Policy</h1>
        <p className="text-sm text-slate-600">
          Last updated: September 2026 · This policy explains what information Prospect processes,
          why it is processed, how long it is retained, and how you can exercise control over your
          data.
        </p>
      </header>

      {/* Operator Identification */}
      <section aria-labelledby="operator-heading" className="space-y-4">
        <h2 id="operator-heading" className="text-xl font-semibold text-slate-900">
          1. Service Operator
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          Prospect is an evidence-first financial document intelligence platform. The legal entity
          and operator responsible for processing data on this instance is:
        </p>
        <div className="rounded-md border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700 space-y-1">
          <p>
            <strong>Operator Legal Name:</strong>{" "}
            <span className="font-mono text-amber-700 bg-amber-100/60 px-1.5 py-0.5 rounded text-xs">
              [REQUIRES HUMAN INPUT — OPERATOR LEGAL NAME]
            </span>
          </p>
          <p>
            <strong>Physical Address:</strong>{" "}
            <span className="font-mono text-amber-700 bg-amber-100/60 px-1.5 py-0.5 rounded text-xs">
              [REQUIRES HUMAN INPUT — OPERATOR PHYSICAL ADDRESS]
            </span>
          </p>
          <p>
            <strong>Privacy Inquiries &amp; Requests:</strong>{" "}
            <span className="font-mono text-amber-700 bg-amber-100/60 px-1.5 py-0.5 rounded text-xs">
              [REQUIRES HUMAN INPUT — PRIVACY CONTACT EMAIL / FORM]
            </span>
          </p>
        </div>
      </section>

      {/* Core Processing Principles */}
      <section aria-labelledby="principles-heading" className="space-y-4">
        <h2 id="principles-heading" className="text-xl font-semibold text-slate-900">
          2. What Prospect Actually Does
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          Prospect transforms user-uploaded financial PDF documents (such as annual reports,
          financial statements, and prospectuses) into structured financial figures and
          deterministic calculations with verbatim page citations.
        </p>
        <ul className="list-disc space-y-2 pl-5 text-sm text-slate-700">
          <li>
            <strong>Anonymous by Design:</strong> Prospect does not require user registration or
            account creation. Workspaces are isolated per browser session using an anonymous cookie.
          </li>
          <li>
            <strong>No Generative AI or LLM Pipeline:</strong> The current implementation uses zero
            large language models (LLMs) or external AI model APIs. Financial fact extraction and
            ratio calculations are performed by deterministic application code.
          </li>
          <li>
            <strong>No Model Training:</strong> Your uploaded documents and extracted figures are
            never used to train machine learning models, AI systems, or public datasets.
          </li>
          <li>
            <strong>No Advertising or Tracking:</strong> Prospect does not sell your data, use
            advertising SDKs, or run cross-site behavioral tracking scripts.
          </li>
        </ul>
      </section>

      {/* Information Processed */}
      <section aria-labelledby="data-processed-heading" className="space-y-4">
        <h2 id="data-processed-heading" className="text-xl font-semibold text-slate-900">
          3. Categories of Information Processed
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          Prospect processes only the categories of data strictly necessary to provide the research
          service, maintain system security, and enforce resource limits:
        </p>
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wider text-slate-600">
              <tr>
                <th className="px-4 py-3">Data Category</th>
                <th className="px-4 py-3">Description &amp; Source</th>
                <th className="px-4 py-3">Purpose</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 bg-surface text-slate-700">
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Uploaded Documents</td>
                <td className="px-4 py-3">
                  PDF files submitted directly by you via browser upload (max 50 MB per file).
                </td>
                <td className="px-4 py-3">
                  Parsing text and tables to extract financial facts and display evidence.
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Document Metadata</td>
                <td className="px-4 py-3">
                  Filename, file size, SHA-256 hash, optional fiscal year, and optional company
                  label.
                </td>
                <td className="px-4 py-3">
                  File verification, deduplication, quota enforcement, and workspace grouping.
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">
                  Extracted Facts &amp; Evidence
                </td>
                <td className="px-4 py-3">
                  Parsed financial metrics (e.g. revenue, net income), currency, scale, period, page
                  numbers, and bounding-box coordinates.
                </td>
                <td className="px-4 py-3">
                  Displaying structured financial tables, evidence citations, and calculations.
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Session Identifiers</td>
                <td className="px-4 py-3">
                  Cryptographically signed session identifier stored in a first-party cookie (
                  <code>__Host-prospect_session</code>).
                </td>
                <td className="px-4 py-3">
                  Isolating your private workspace so only your browser can view your uploaded
                  documents.
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Audit &amp; Review Logs</td>
                <td className="px-4 py-3">
                  Timestamps of document uploads, manual fact reviews/corrections, and export
                  events.
                </td>
                <td className="px-4 py-3">
                  Internal auditability and tracking user-initiated fact modifications.
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Security Telemetry</td>
                <td className="px-4 py-3">
                  Client IP address, request paths, timestamps, and rate-limit counters.
                </td>
                <td className="px-4 py-3">
                  Abuse prevention, rate limiting (DDoS defense), and diagnosing processing
                  failures.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="text-xs text-slate-500">
          <strong>Categories NOT collected:</strong> Prospect does not collect personal names,
          national identity numbers, physical home addresses, personal email addresses (unless
          submitted in future registered mode), telephone numbers, payment card details, GPS
          location, or biometric data.
        </p>
      </section>

      {/* Retention Schedule */}
      <section aria-labelledby="retention-heading" className="space-y-4">
        <h2 id="retention-heading" className="text-xl font-semibold text-slate-900">
          4. Data Retention Schedule
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          Prospect enforces automated retention schedules in software to prevent sensitive financial
          documents from lingering indefinitely on servers:
        </p>
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wider text-slate-600">
              <tr>
                <th className="px-4 py-3">Data Asset</th>
                <th className="px-4 py-3">Technical Retention Limit</th>
                <th className="px-4 py-3">Automated Deletion Mechanism</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 bg-surface text-slate-700">
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Verified Uploaded PDF</td>
                <td className="px-4 py-3">
                  30 days from upload (<code>DOCUMENT_RETENTION_DAYS</code> default)
                </td>
                <td className="px-4 py-3">
                  Worker background sweep &amp; object store lifecycle rule.
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Derived Data &amp; Facts</td>
                <td className="px-4 py-3">Tied to the document record</td>
                <td className="px-4 py-3">
                  Cascade deleted immediately when the document is deleted (
                  <code>ON DELETE CASCADE</code>).
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Anonymous Workspace</td>
                <td className="px-4 py-3">
                  24 hours after last usable session expires (<code>WORKSPACE_GRACE_HOURS</code>{" "}
                  default)
                </td>
                <td className="px-4 py-3">
                  Worker background sweep purges the entire user record, files, and derived data.
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Failed Uploads</td>
                <td className="px-4 py-3">
                  File deleted within minutes; DB record purged after 24 hours (
                  <code>FAILED_DOCUMENT_RETENTION_HOURS</code>)
                </td>
                <td className="px-4 py-3">Immediate storage cleanup + scheduled database sweep.</td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Exports (CSV, JSON, XLSX)</td>
                <td className="px-4 py-3">Generated in memory per request</td>
                <td className="px-4 py-3">Never stored on server disk or object storage.</td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Worker Temp Files</td>
                <td className="px-4 py-3">Duration of parsing attempt only (≤ 120s)</td>
                <td className="px-4 py-3">
                  Isolated temporary directory purged on attempt conclusion.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="text-xs text-slate-600 bg-slate-50 p-3 rounded border border-slate-200">
          <strong>Policy Note:</strong> While technical mechanisms enforce the above defaults in the
          codebase, the formal legally binding retention window for commercial deployment requires
          operator confirmation:{" "}
          <span className="font-mono text-amber-700 bg-amber-100/60 px-1 py-0.5 rounded">
            [REQUIRES HUMAN INPUT — RETENTION PERIOD POLICY CONFIRMATION]
          </span>
          .
        </p>
      </section>

      {/* Deletion Behavior */}
      <section aria-labelledby="deletion-heading" className="space-y-4">
        <h2 id="deletion-heading" className="text-xl font-semibold text-slate-900">
          5. Data Deletion &amp; Erasure Mechanics
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          You can delete any document at any time directly through the Prospect interface or via the{" "}
          <code>DELETE /api/v1/documents/&#123;id&#125;</code> endpoint.
        </p>
        <div className="space-y-2 text-sm text-slate-700">
          <p>When a document is deleted, Prospect performs the following deterministic actions:</p>
          <ol className="list-decimal space-y-1.5 pl-5">
            <li>Deletes the underlying PDF object from private object storage.</li>
            <li>
              Purges all audit log entries that copied document contents (such as filenames,
              before/after fact values, and scenario reasons), preserving only metadata markers (
              <code>document_created</code>, <code>document_deleted</code>).
            </li>
            <li>
              Deletes the database document record, which cascades across all extracted pages,
              sections, chunks, verbatim evidence rows, financial facts, ratio calculations, quality
              issues, and derived scenarios.
            </li>
          </ol>
          <p className="text-xs text-slate-500 pt-1">
            <strong>Honest Disclosure Regarding Backups:</strong> Prospect does not claim immediate
            cryptographic erasure of automated infrastructure backups. If database point-in-time
            recovery (PITR) backups are enabled by the cloud host, deleted records may persist
            inside encrypted database backups until provider backup retention expires (recommended:
            ≤ 37 days).
          </p>
        </div>
      </section>

      {/* Cookies & Tracking */}
      <section aria-labelledby="cookies-heading" className="space-y-4">
        <h2 id="cookies-heading" className="text-xl font-semibold text-slate-900">
          6. Cookies &amp; Storage Technologies
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          Prospect uses only strictly necessary technologies essential to operate the application:
        </p>
        <ul className="list-disc space-y-1.5 pl-5 text-sm text-slate-700">
          <li>
            <strong>
              Session Cookie (<code>__Host-prospect_session</code>):
            </strong>{" "}
            A first-party, HttpOnly, SameSite=Strict cookie containing an HMAC-signed session token.
            It is inaccessible to client-side JavaScript and is used exclusively to maintain your
            anonymous workspace and prevent Cross-Site Request Forgery (CSRF).
          </li>
          <li>
            <strong>
              Theme Cookie (<code>theme</code>):
            </strong>{" "}
            Set only if you switch between light and dark mode. It holds just the word
            &quot;light&quot; or &quot;dark&quot;, no identifier, and expires after one year.
          </li>
          <li>
            <strong>Local Storage:</strong> Prospect does not store document data or personal state
            in browser <code>localStorage</code> or <code>sessionStorage</code>. (The application
            only checks for and removes obsolete legacy tokens if found from earlier versions).
          </li>
          <li>
            <strong>No Third-Party Cookies or Web Beacons:</strong> No tracking pixels, Google
            Analytics, social media trackers, or third-party cookies are embedded in the
            application.
          </li>
        </ul>
      </section>

      {/* Infrastructure & Third Parties */}
      <section aria-labelledby="subprocessors-heading" className="space-y-4">
        <h2 id="subprocessors-heading" className="text-xl font-semibold text-slate-900">
          7. Infrastructure Providers &amp; Third-Party Services
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          Prospect relies on managed cloud providers to run application services and store encrypted
          data:
        </p>
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wider text-slate-600">
              <tr>
                <th className="px-4 py-3">Provider</th>
                <th className="px-4 py-3">Role in Architecture</th>
                <th className="px-4 py-3">Data Handled</th>
                <th className="px-4 py-3">Location / Residency</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 bg-surface text-slate-700">
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Vercel</td>
                <td className="px-4 py-3">Frontend Next.js web hosting and API edge proxy</td>
                <td className="px-4 py-3">HTTP requests, client IP, web pages</td>
                <td className="px-4 py-3">Globally distributed edge network</td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Railway / Render</td>
                <td className="px-4 py-3">Managed FastAPI backend and asynchronous PDF worker</td>
                <td className="px-4 py-3">API requests, PDF parsing jobs</td>
                <td className="px-4 py-3">
                  <span className="font-mono text-amber-700 bg-amber-100/60 px-1 py-0.5 rounded text-xs">
                    [REQUIRES VERIFICATION — HOSTING REGION]
                  </span>
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">
                  Managed PostgreSQL (Railway / Supabase)
                </td>
                <td className="px-4 py-3">Relational database storage</td>
                <td className="px-4 py-3">
                  Extracted facts, evidence, audit logs, session records
                </td>
                <td className="px-4 py-3">
                  <span className="font-mono text-amber-700 bg-amber-100/60 px-1 py-0.5 rounded text-xs">
                    [REQUIRES VERIFICATION — DATABASE REGION]
                  </span>
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">
                  Cloudflare R2 / Supabase Storage
                </td>
                <td className="px-4 py-3">Private object storage for PDF files</td>
                <td className="px-4 py-3">Uploaded PDF documents (private bucket, signed URLs)</td>
                <td className="px-4 py-3">
                  <span className="font-mono text-amber-700 bg-amber-100/60 px-1 py-0.5 rounded text-xs">
                    [REQUIRES VERIFICATION — STORAGE REGION]
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* Cross-Border Transfers */}
      <section aria-labelledby="transfers-heading" className="space-y-4">
        <h2 id="transfers-heading" className="text-xl font-semibold text-slate-900">
          8. Cross-Border Processing &amp; Data Residency
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          Prospect uses globally distributed cloud infrastructure. Depending on the physical
          location from which you access the service and where managed cloud resources are
          provisioned, your data may be transferred across international borders. Prospect makes no
          unsupported claim that data remains exclusively within any single national territory (such
          as Indonesia or the European Union) unless explicit regional tenant pinning has been
          verified and configured.
        </p>
      </section>

      {/* User Rights */}
      <section aria-labelledby="rights-heading" className="space-y-4">
        <h2 id="rights-heading" className="text-xl font-semibold text-slate-900">
          9. User Rights &amp; How to Exercise Them
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          Because Prospect operates with anonymous sessions, you have direct, immediate control over
          your data during your session:
        </p>
        <ul className="list-disc space-y-1.5 pl-5 text-sm text-slate-700">
          <li>
            <strong>Access &amp; Portability:</strong> You can view all extracted facts and export
            them as CSV, JSON, or XLSX directly through the interface at any time.
          </li>
          <li>
            <strong>Correction:</strong> You can review, correct, or reject extracted financial
            facts via the Review workspace.
          </li>
          <li>
            <strong>Deletion:</strong> You can delete any uploaded document at any time, or clear
            your browser cookies to permanently dissociate from your anonymous workspace.
          </li>
          <li>
            <strong>Formal Inquiries:</strong> For inquiries regarding applicable data protection
            laws (such as UU PDP or GDPR) or to submit formal requests, contact:{" "}
            <span className="font-mono text-amber-700 bg-amber-100/60 px-1.5 py-0.5 rounded text-xs">
              [REQUIRES HUMAN INPUT — PRIVACY CONTACT EMAIL / FORM]
            </span>
            .
          </li>
        </ul>
      </section>

      {/* Footer Navigation */}
      <footer className="border-t border-slate-200 pt-6 text-xs text-slate-500 flex flex-wrap gap-4">
        <Link href="/terms" className="underline hover:text-slate-800">
          Terms of Use
        </Link>
        <Link href="/acceptable-use" className="underline hover:text-slate-800">
          Acceptable Use Policy
        </Link>
        <Link href="/security" className="underline hover:text-slate-800">
          Security Disclosure
        </Link>
        <Link href="/copyright" className="underline hover:text-slate-800">
          Copyright &amp; IP
        </Link>
      </footer>
    </article>
  );
}
