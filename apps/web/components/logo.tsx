/** Prospect's symbol, "held fact": citation brackets holding one dot (brand/README.md).
 * The small-size cut, since the header shows it at 24 px. Brackets follow the text colour, so
 * light and dark mode need nothing extra; the dot is the brand indigo. */
export function LogoSymbol({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 256 256" aria-hidden="true" className={className}>
      <path
        fill="currentColor"
        d="M70 22 H60 A36 36 0 0 0 24 58 V198 A36 36 0 0 0 60 234 H70 A18 18 0 0 0 70 198 H60 V58 H70 A18 18 0 0 0 70 22 Z M186 22 H196 A36 36 0 0 1 232 58 V198 A36 36 0 0 1 196 234 H186 A18 18 0 0 1 186 198 H196 V58 H186 A18 18 0 0 1 186 22 Z"
      />
      <circle cx="128" cy="128" r="34" className="fill-accent dark:fill-indigo-400" />
    </svg>
  );
}
