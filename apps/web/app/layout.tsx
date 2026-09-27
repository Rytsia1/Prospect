import type { Metadata } from "next";
import Link from "next/link";
import { Nav } from "@/components/nav";
import "./globals.css";

// Rendered per request so Next can put middleware.ts's CSP nonce on its scripts (a page
// prerendered at build time would carry no nonce and be blocked by the policy).
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: { default: "Prospect", template: "%s · Prospect" },
  description: "Evidence-first financial document intelligence",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="flex min-h-screen flex-col bg-white text-slate-900 antialiased">
        <header className="border-b border-slate-200">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-2">
            <Link href="/" className="font-semibold tracking-tight">
              Prospect
            </Link>
            <Nav />
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
