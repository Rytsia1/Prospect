"use client";

import { useState } from "react";
import { flushSync } from "react-dom";
import { THEME_COOKIE, type Theme } from "@/lib/theme";

/** Light/dark switch. The choice is a first-party preference cookie (only "light" or "dark", no
 * identifier) so the server renders the right theme on the next visit without a flash. */
export function ThemeToggle({ initial }: { initial: Theme }) {
  const [theme, setTheme] = useState(initial);
  const dark = theme === "dark";

  function toggle(button: HTMLButtonElement) {
    const next: Theme = dark ? "light" : "dark";
    // Remembered for a year. Without the Cookie Store API (or if saving fails) the switch still
    // works; the next visit just starts light again.
    globalThis.cookieStore
      ?.set({
        name: THEME_COOKIE,
        value: next,
        path: "/",
        expires: Date.now() + 365 * 24 * 60 * 60 * 1000,
        sameSite: "lax",
      })
      .catch(() => {});
    const apply = () => {
      document.documentElement.classList.toggle("dark", next === "dark");
      setTheme(next);
    };
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced || !document.startViewTransition) return apply();

    // The new theme grows as a circle from the button until it covers the whole viewport.
    const box = button.getBoundingClientRect();
    const x = box.left + box.width / 2;
    const y = box.top + box.height / 2;
    const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
    const transition = document.startViewTransition(() => flushSync(apply));
    transition.ready
      .then(() =>
        document.documentElement.animate(
          { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
          { duration: 450, easing: "ease-out", pseudoElement: "::view-transition-new(root)" },
        ),
      )
      .catch(() => {}); // animation skipped (e.g. a hidden tab); the theme is already applied
  }

  return (
    <button
      type="button"
      aria-label="Dark mode"
      aria-pressed={dark}
      title={dark ? "Switch to light mode" : "Switch to dark mode"}
      onClick={(e) => toggle(e.currentTarget)}
      className="inline-flex min-h-11 min-w-11 items-center justify-center rounded text-slate-600 hover:text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-5 w-5"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {dark ? (
          // Sun: shown in dark mode, switches to light
          <>
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
          </>
        ) : (
          // Moon: shown in light mode, switches to dark
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        )}
      </svg>
    </button>
  );
}
