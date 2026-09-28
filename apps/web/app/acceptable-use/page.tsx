import type { Metadata } from "next";
import Link from "next/link";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Acceptable Use Policy",
  description: "Rules and restrictions governing acceptable use of the Prospect platform.",
};

export default function AcceptableUsePage() {
  return (
    <article className="mx-auto max-w-4xl space-y-10 py-2">
      {/* Header */}
      <header className="space-y-3 border-b border-slate-200 pb-6">
        <div className="inline-flex items-center gap-2 rounded bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800 border border-amber-200">
          <span>Notice: Baseline Draft Pending Final Human Review</span>
        </div>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900">
          Acceptable Use Policy
        </h1>
        <p className="text-sm text-slate-600">
          Last updated: September 2026 · This policy establishes prohibited activities, technical
          enforcement controls, and rules designed to protect the platform and its users.
        </p>
      </header>

      {/* 1. Purpose */}
      <section aria-labelledby="purpose-heading" className="space-y-4">
        <h2 id="purpose-heading" className="text-xl font-semibold text-slate-900">
          1. Purpose &amp; Scope
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          Prospect provides evidence-first financial document extraction in a shared, multi-tenant
          cloud environment. To ensure equitable access, resource availability, and system security
          for all users, your use of the platform must adhere strictly to this Acceptable Use
          Policy.
        </p>
      </section>

      {/* 2. Prohibited Content */}
      <section aria-labelledby="content-prohibitions-heading" className="space-y-4">
        <h2 id="content-prohibitions-heading" className="text-xl font-semibold text-slate-900">
          2. Prohibited Content &amp; Uploads
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          You may not upload, transmit, or store any file or content that:
        </p>
        <ul className="list-disc space-y-2 pl-5 text-sm text-slate-700">
          <li>
            <strong>Contains Malicious Code:</strong> Executables, macro payloads, viruses, worms,
            Trojans, malicious PDF objects, or corrupted byte streams intended to compromise host
            systems or parser runtimes;
          </li>
          <li>
            <strong>Is Not a Genuine Document:</strong> Executables or media disguised with a{" "}
            <code>.pdf</code> extension or deceptive MIME type headers;
          </li>
          <li>
            <strong>Infringes Intellectual Property:</strong> Materials uploaded without necessary
            copyright authorization, license, or legal right;
          </li>
          <li>
            <strong>Violates Law or Privacy:</strong> Documents containing unlawful content, trade
            secrets obtained through corporate espionage, or unauthorized non-public personal
            information (such as medical records or government identification documents unrelated to
            financial filings).
          </li>
        </ul>
      </section>

      {/* 3. Prohibited Activities */}
      <section aria-labelledby="activity-prohibitions-heading" className="space-y-4">
        <h2 id="activity-prohibitions-heading" className="text-xl font-semibold text-slate-900">
          3. Prohibited Technical Activities &amp; System Abuse
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          You agree not to engage in any activity that harms, probes, or overburdens the platform:
        </p>
        <ul className="list-disc space-y-2 pl-5 text-sm text-slate-700">
          <li>
            <strong>Unauthorized Access &amp; Session Probing:</strong> Attempting to access,
            modify, or delete documents belonging to another user&rsquo;s anonymous workspace, or
            tampering with document identifiers, user IDs, or signed URLs;
          </li>
          <li>
            <strong>Denial of Service &amp; Resource Exhaustion:</strong> Uploading compression
            bombs (flate bombs, deeply nested PDF dictionaries, or infinite object streams) designed
            to exhaust worker memory, disk space, or CPU cycles;
          </li>
          <li>
            <strong>Automated Abuse &amp; Scraping:</strong> Scripting automated requests, session
            floods, or high-frequency export calls that exceed configured API rate limits;
          </li>
          <li>
            <strong>Cryptographic &amp; Header Tampering:</strong> Modifying HMAC signatures in
            session tokens, forging proxy headers (such as <code>X-Prospect-Client-IP</code>), or
            bypassing CSRF validation;
          </li>
          <li>
            <strong>Sandbox Evasion &amp; Network Probing:</strong> Attempting to escape the PDF
            parser subprocess, initiate outbound network connections from worker sandboxes, or scan
            internal cloud infrastructure;
          </li>
          <li>
            <strong>Quota Circumvention:</strong> Automating the creation of multiple ephemeral
            sessions to evade document, storage, or scenario caps.
          </li>
        </ul>
      </section>

      {/* 4. Technical Controls & Enforcement */}
      <section aria-labelledby="controls-heading" className="space-y-4">
        <h2 id="controls-heading" className="text-xl font-semibold text-slate-900">
          4. Technical Enforcement Mechanisms
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          Prospect enforces technical controls directly in application code to uphold this policy:
        </p>
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wider text-slate-600">
              <tr>
                <th className="px-4 py-3">Control Area</th>
                <th className="px-4 py-3">Enforced Limit</th>
                <th className="px-4 py-3">Enforcement Layer</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 bg-white text-slate-700">
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Max Upload Size</td>
                <td className="px-4 py-3">50 MiB (52,428,800 bytes)</td>
                <td className="px-4 py-3">Signed URL exact length check &amp; API verification</td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">File Structure</td>
                <td className="px-4 py-3">
                  Valid <code>%PDF-</code> header and SHA-256 match
                </td>
                <td className="px-4 py-3">Server-side pre-processing inspection</td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Parser Limits</td>
                <td className="px-4 py-3">Max 2,000 pages, 500,000 objects, 120s timeout</td>
                <td className="px-4 py-3">Worker sandbox wall-clock kill and resource bounds</td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Database Protection</td>
                <td className="px-4 py-3">30-second statement timeout per query</td>
                <td className="px-4 py-3">PostgreSQL session configuration</td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Rate Limits</td>
                <td className="px-4 py-3">Per-IP and per-session rate windows</td>
                <td className="px-4 py-3">API middleware (429 Too Many Requests)</td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-slate-900">Workspace Quotas</td>
                <td className="px-4 py-3">100 documents, 2 GB storage, 200 scenarios</td>
                <td className="px-4 py-3">Application quota manager</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* 5. Violations & Remediation */}
      <section aria-labelledby="violations-heading" className="space-y-4">
        <h2 id="violations-heading" className="text-xl font-semibold text-slate-900">
          5. Violations &amp; Remedies
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          The operator reserves the right to investigate suspected violations of this policy. In
          response to violations, the operator may immediately:
        </p>
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
          <li>
            Reject or terminate active requests (returning 400, 403, 413, 422, or 429 status codes);
          </li>
          <li>Delete offending documents and purge associated workspaces;</li>
          <li>
            Block abusive client IP addresses or autonomous system numbers (ASNs) at the edge proxy;
          </li>
          <li>
            Report illegal conduct to competent law enforcement authorities where appropriate.
          </li>
        </ul>
      </section>

      {/* 6. Reporting Abuse */}
      <section aria-labelledby="reporting-heading" className="space-y-4">
        <h2 id="reporting-heading" className="text-xl font-semibold text-slate-900">
          6. Reporting Abuse
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          If you discover suspected abuse, security vulnerabilities, or violations of this policy,
          please contact:{" "}
          <span className="font-mono text-amber-700 bg-amber-100/60 px-1.5 py-0.5 rounded text-xs">
            [REQUIRES HUMAN INPUT — ABUSE REPORTING CONTACT]
          </span>
          . For security vulnerabilities, please refer to our{" "}
          <Link href="/security" className="text-slate-900 underline hover:text-slate-700">
            Security Disclosure
          </Link>{" "}
          guidelines.
        </p>
      </section>

      {/* Footer Navigation */}
      <footer className="border-t border-slate-200 pt-6 text-xs text-slate-500 flex flex-wrap gap-4">
        <Link href="/privacy" className="underline hover:text-slate-800">
          Privacy Policy
        </Link>
        <Link href="/terms" className="underline hover:text-slate-800">
          Terms of Use
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
