"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/documents", label: "Documents" },
  { href: "/companies", label: "Companies" },
  { href: "/watchlist", label: "Watchlist" },
  { href: "/review", label: "Review" },
  { href: "/data-quality", label: "Data Quality" },
  { href: "/scenarios", label: "Scenarios" },
  { href: "/diff", label: "Diff" },
  { href: "/audit", label: "Audit" },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="flex gap-1 text-sm">
      {LINKS.map(({ href, label }) => {
        const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={`rounded px-3 py-1.5 ${
              active
                ? "bg-slate-100 font-medium text-slate-900"
                : "text-slate-600 hover:text-slate-900"
            }`}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
