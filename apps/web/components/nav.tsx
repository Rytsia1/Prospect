"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

// Where research starts. Everything else is reached from a document or company (in context) or
// from "More", so the header stays one short line on a phone.
const PRIMARY = [
  { href: "/", label: "Documents" },
  { href: "/companies", label: "Companies" },
  { href: "/watchlist", label: "Watchlist" },
];
const MORE = [
  { href: "/review", label: "Review figures" },
  { href: "/data-quality", label: "Data quality" },
  { href: "/scenarios", label: "Scenarios" },
  { href: "/diff", label: "Compare reports" },
  { href: "/audit", label: "Activity log" },
];

const isActive = (pathname: string, href: string) =>
  href === "/" ? pathname === "/" || pathname.startsWith("/documents") : pathname.startsWith(href);

const ITEM =
  "inline-flex min-h-11 items-center rounded px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900";

export function Nav() {
  const pathname = usePathname();
  const more = useRef<HTMLDetailsElement>(null);

  // A native disclosure: close it after navigating and when clicking anywhere else.
  // biome-ignore lint/correctness/useExhaustiveDependencies: runs on every route change
  useEffect(() => {
    if (more.current) more.current.open = false;
  }, [pathname]);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (more.current && !more.current.contains(e.target as Node)) more.current.open = false;
    };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, []);

  const moreActive = MORE.some(({ href }) => isActive(pathname, href));
  return (
    <nav aria-label="Main" className="flex items-center gap-1">
      {PRIMARY.map(({ href, label }) => {
        const active = isActive(pathname, href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={`${ITEM} ${
              active
                ? "bg-slate-100 font-medium text-slate-900"
                : "text-slate-600 hover:text-slate-900"
            }`}
          >
            {label}
          </Link>
        );
      })}
      <details ref={more} className="relative">
        <summary
          className={`${ITEM} cursor-pointer list-none [&::-webkit-details-marker]:hidden ${
            moreActive
              ? "bg-slate-100 font-medium text-slate-900"
              : "text-slate-600 hover:text-slate-900"
          }`}
        >
          More
          <span aria-hidden="true" className="ml-1 text-xs">
            ▾
          </span>
        </summary>
        <ul className="absolute right-0 z-30 mt-1 w-48 rounded border border-slate-200 bg-white py-1 shadow-lg">
          {MORE.map(({ href, label }) => {
            const active = isActive(pathname, href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`${ITEM} w-full rounded-none ${
                    active
                      ? "bg-slate-100 font-medium text-slate-900"
                      : "text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>
      </details>
    </nav>
  );
}
