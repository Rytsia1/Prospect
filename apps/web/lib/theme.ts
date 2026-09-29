export type Theme = "light" | "dark";
export const THEME_COOKIE = "theme";

/** The cookie is client-controlled: anything but exactly "dark" means the default, light. */
export function parseTheme(value: string | undefined): Theme {
  return value === "dark" ? "dark" : "light";
}
