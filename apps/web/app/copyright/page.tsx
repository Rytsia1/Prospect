import type { Metadata } from "next";
import Link from "next/link";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Copyright & Intellectual Property",
  description:
    "Intellectual property ownership, licensing, and copyright takedown notices for Prospect.",
};

export default function CopyrightPage() {
  return (
    <article className="mx-auto max-w-4xl space-y-10 py-2">
      {/* Header */}
      <header className="space-y-3 border-b border-slate-200 pb-6">
        <div className="inline-flex items-center gap-2 rounded bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800 border border-amber-200">
          <span>Notice: Baseline Draft Pending Final Human Review</span>
        </div>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900">
          Copyright &amp; Intellectual Property
        </h1>
        <p className="text-sm text-slate-600">
          Last updated: September 2026 · Clarification of software ownership, user content rights,
          and procedures for reporting copyright concerns.
        </p>
      </header>

      {/* 1. Software & Platform IP */}
      <section aria-labelledby="platform-ip-heading" className="space-y-4">
        <h2 id="platform-ip-heading" className="text-xl font-semibold text-slate-900">
          1. Platform Software &amp; Proprietary Rights
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          The Prospect platform, including its software architecture, source code, user interface,
          design system, analytical algorithms, and documentation, is protected by applicable
          copyright and intellectual property laws.
        </p>
        <p className="text-sm leading-relaxed text-slate-700">
          Third-party open-source components utilized by the platform are governed by their
          respective licenses. Notably, document text and layout extraction utilizes PyMuPDF, which
          is licensed under the GNU Affero General Public License (AGPL-3.0) or commercial terms
          from Artifex Software.
        </p>
      </section>

      {/* 2. User Content Ownership */}
      <section aria-labelledby="user-content-heading" className="space-y-4">
        <h2 id="user-content-heading" className="text-xl font-semibold text-slate-900">
          2. User-Uploaded Documents
        </h2>
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-5 space-y-3 text-sm text-slate-700">
          <p className="font-semibold text-slate-900">
            Users retain all ownership rights in the content they upload.
          </p>
          <p>
            Prospect does <strong>not</strong> claim ownership, copyright, or perpetual rights over
            any financial statement, annual report, prospectus, or analysis uploaded by users.
          </p>
          <p>
            By uploading a document, you grant Prospect only the minimal, limited, non-exclusive
            license strictly necessary to receive, store, parse, extract figures, compute
            deterministic ratios, display results, generate user exports, and delete the data in
            accordance with our retention and deletion schedules.
          </p>
        </div>
      </section>

      {/* 3. Infringement & Takedown Requests */}
      <section aria-labelledby="takedown-heading" className="space-y-4">
        <h2 id="takedown-heading" className="text-xl font-semibold text-slate-900">
          3. Reporting Copyright Infringement &amp; Takedown Requests
        </h2>
        <p className="text-sm leading-relaxed text-slate-700">
          If you believe that content hosted or processed on Prospect infringes your copyright or
          the copyright of an entity you represent, please send a written notification containing
          the following details to our designated contact:
        </p>
        <ul className="list-disc space-y-2 pl-5 text-sm text-slate-700">
          <li>Identification of the copyrighted work claimed to have been infringed;</li>
          <li>
            Identification of the material on Prospect that is claimed to be infringing, including
            sufficient information to locate the document (such as document ID or URL);
          </li>
          <li>
            Your contact information, including your full legal name, physical address, telephone
            number, and email address;
          </li>
          <li>
            A statement that you have a good-faith belief that use of the material in the manner
            complained of is not authorized by the copyright owner, its agent, or the law;
          </li>
          <li>
            A statement, made under penalty of perjury, that the information in the notification is
            accurate and that you are authorized to act on behalf of the owner of the copyright;
          </li>
          <li>A physical or electronic signature of the authorized person.</li>
        </ul>
        <div className="rounded-md border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700 space-y-1">
          <p>
            <strong>Designated Copyright Contact / Agent:</strong>
          </p>
          <p>
            <span className="font-mono text-amber-700 bg-amber-100/60 px-1.5 py-0.5 rounded text-xs">
              [REQUIRES HUMAN INPUT — COPYRIGHT CONTACT EMAIL / AGENT]
            </span>
          </p>
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
        <Link href="/security" className="underline hover:text-slate-800">
          Security Disclosure
        </Link>
      </footer>
    </article>
  );
}
