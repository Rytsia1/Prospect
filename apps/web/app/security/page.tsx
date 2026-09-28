import type { Metadata } from "next";
import Link from "next/link";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Security & Responsible Disclosure",
  description:
    "Security architecture, vulnerability reporting, and incident transparency for Prospect.",
};

export default function SecurityPage() {
  return (
    <article className="mx-auto max-w-4xl space-y-10 py-2">
      {/* Header */}
      <header className="space-y-3 border-b border-slate-200 pb-6">
        <div className="inline-flex items-center gap-2 rounded bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800 border border-amber-200">
          <span>Notice: Baseline Draft Pending Final Human Review</span>
        </div>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900">
          Security &amp; Responsible Disclosure
        </h1>
        <p className="text-sm text-slate-600">
          Last updated: September 2026 · Overview of Prospect&rsquo;s defense-in-depth security
          model, vulnerability reporting procedures, and incident transparency commitments.
        </p>
      </header>

      {/* 1. Security Philosophy */}
      <section aria-labelledby="philosophy-heading" className="space-y-4">
        <h2 id="philosophy-heading" className="text-xl font-semibold text-slate-900">
          1. Security Architecture &amp; Philosophy
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          Prospect operates on the core principle that{" "}
          <strong>all external input is untrusted</strong>. Every PDF file, filename, HTTP header,
          query parameter, and client payload is validated at service boundaries.
        </p>
        <p className="text-sm leading-relaxed text-slate-700">
          Rather than relying on vague security promises, Prospect enforces defense-in-depth
          controls directly in application code and infrastructure configuration.
        </p>
      </section>

      {/* 2. Technical Controls Summary */}
      <section aria-labelledby="safeguards-heading" className="space-y-4">
        <h2 id="safeguards-heading" className="text-xl font-semibold text-slate-900">
          2. Enforced Technical Controls
        </h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="rounded-lg border border-slate-200 p-4 space-y-2 bg-slate-50/50">
            <h3 className="font-medium text-slate-900 text-sm">Anonymous Workspace Isolation</h3>
            <p className="text-xs text-slate-600 leading-relaxed">
              Every request requires a cryptographically signed HMAC token in an{" "}
              <code>HttpOnly</code>, <code>SameSite=Strict</code> cookie. Every document query is
              strictly scoped by user ID in SQL; no cross-session reads are permitted.
            </p>
          </div>
          <div className="rounded-lg border border-slate-200 p-4 space-y-2 bg-slate-50/50">
            <h3 className="font-medium text-slate-900 text-sm">Direct-to-Storage Ingest</h3>
            <p className="text-xs text-slate-600 leading-relaxed">
              PDFs are uploaded directly from the browser to private object storage via single-use,
              15-minute signed PUT URLs. The upload signature covers the exact file length and
              SHA-256 checksum, preventing buffer exhaustion and payload tampering.
            </p>
          </div>
          <div className="rounded-lg border border-slate-200 p-4 space-y-2 bg-slate-50/50">
            <h3 className="font-medium text-slate-900 text-sm">PDF Parser Sandboxing</h3>
            <p className="text-xs text-slate-600 leading-relaxed">
              The PDF parsing engine (PyMuPDF) executes in an isolated child process with stripped
              environment variables, memory and CPU limits, wall-clock timeouts, and network
              namespace isolation where supported by the operating system.
            </p>
          </div>
          <div className="rounded-lg border border-slate-200 p-4 space-y-2 bg-slate-50/50">
            <h3 className="font-medium text-slate-900 text-sm">Content Security Policy (CSP)</h3>
            <p className="text-xs text-slate-600 leading-relaxed">
              Pages are delivered with a strict CSP featuring a per-request cryptographic nonce,{" "}
              <code>strict-dynamic</code>, no inline scripts, and zero third-party script domains.
            </p>
          </div>
          <div className="rounded-lg border border-slate-200 p-4 space-y-2 bg-slate-50/50">
            <h3 className="font-medium text-slate-900 text-sm">Privacy-Safe Deletion</h3>
            <p className="text-xs text-slate-600 leading-relaxed">
              Deleting a document cascades across all derived facts, calculations, and scenarios.
              Audit rows that copied document text or filenames are purged, leaving only
              non-sensitive metadata event markers.
            </p>
          </div>
          <div className="rounded-lg border border-slate-200 p-4 space-y-2 bg-slate-50/50">
            <h3 className="font-medium text-slate-900 text-sm">Automated Data Retention</h3>
            <p className="text-xs text-slate-600 leading-relaxed">
              Documents are automatically removed after 30 days, failed attempts after 24 hours, and
              abandoned workspaces 24 hours after session expiration.
            </p>
          </div>
        </div>
      </section>

      {/* 3. Responsible Disclosure */}
      <section aria-labelledby="disclosure-heading" className="space-y-4">
        <h2 id="disclosure-heading" className="text-xl font-semibold text-slate-900">
          3. Responsible Vulnerability Disclosure
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          We welcome and encourage security researchers to responsibly report potential security
          vulnerabilities. To participate in responsible disclosure:
        </p>
        <ul className="list-disc space-y-2 pl-5 text-sm text-slate-700">
          <li>
            <strong>Protect User Privacy:</strong> Do not attempt to access, download, or alter data
            belonging to other users. Verify vulnerabilities using your own test session;
          </li>
          <li>
            <strong>Avoid Disruption:</strong> Do not execute denial-of-service (DoS) attacks, flood
            queues, or degrade service performance for active users;
          </li>
          <li>
            <strong>Allow Remediation Time:</strong> Provide a reasonable window for the team to
            investigate and patch the vulnerability before publishing any details or proof of
            concept.
          </li>
        </ul>
        <div className="rounded-md border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700 space-y-2">
          <p>
            <strong>Security Contact:</strong> Please send encrypted vulnerability reports and
            security findings to:{" "}
            <span className="font-mono text-amber-700 bg-amber-100/60 px-1.5 py-0.5 rounded text-xs">
              [REQUIRES HUMAN INPUT — SECURITY CONTACT EMAIL]
            </span>
            .
          </p>
          <p className="text-xs text-slate-500">
            <strong>Bounty Program Notice:</strong> Prospect does not currently operate a paid bug
            bounty program (
            <span className="font-mono text-amber-700 bg-amber-100/60 px-1 py-0.5 rounded">
              [REQUIRES HUMAN DECISION — BUG BOUNTY POLICY]
            </span>
            ), but will gladly acknowledge responsible researchers.
          </p>
        </div>
      </section>

      {/* 4. Incident Response & Transparency */}
      <section aria-labelledby="incidents-heading" className="space-y-4">
        <h2 id="incidents-heading" className="text-xl font-semibold text-slate-900">
          4. Incident Response &amp; Breach Transparency
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          Prospect maintains a structured incident response procedure (
          <code>docs/INCIDENT_RESPONSE.md</code>) covering detection, containment, credential
          rotation, investigation, and recovery.
        </p>
        <div className="space-y-2 text-sm text-slate-700">
          <p>
            <strong>Anonymous User Transparency:</strong> Because Prospect uses anonymous sessions
            without registered email addresses, there is no direct user contact list to notify
            individually.
          </p>
          <p>
            In the event of a verified security incident affecting data integrity or tenant
            isolation:
          </p>
          <ul className="list-disc space-y-1 pl-5">
            <li>
              The operator will publish a public incident advisory notice directly on this website;
            </li>
            <li>
              Any affected session secrets will be rotated immediately to invalidate compromised
              sessions;
            </li>
            <li>
              Applicable statutory regulatory notification requirements will be completed in
              accordance with relevant data protection laws:{" "}
              <span className="font-mono text-amber-700 bg-amber-100/60 px-1.5 py-0.5 rounded text-xs">
                [REQUIRES HUMAN REVIEW — REGULATORY NOTIFICATION REQUIREMENTS]
              </span>
              .
            </li>
          </ul>
        </div>
      </section>

      {/* Footer Navigation */}
      <footer className="border-t border-slate-200 pt-6 text-xs text-slate-500 flex flex-wrap gap-4">
        <Link href="/privacy" className="underline hover:text-slate-800">
          Privacy Policy
        </Link>
        <Link href="/terms" className="underline hover:text-slate-800">
          Terms of Use
        </Link>
        <Link href="/acceptable-use" className="underline hover:text-slate-800">
          Acceptable Use Policy
        </Link>
        <Link href="/copyright" className="underline hover:text-slate-800">
          Copyright &amp; IP
        </Link>
      </footer>
    </article>
  );
}
