/**
 * Panel theme (TZ 34: Light + Dark).
 *
 * The visual system is CSS-first: `data-theme="light"` on <html> flips the
 * variables in globals.css. Persisted in localStorage so the choice survives
 * reloads, defaulting to the original dark look.
 */

const THEME_KEY = "soulchat.theme";

export type Theme = "dark" | "light";

export function currentTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  const stored = window.localStorage.getItem(THEME_KEY);
  return stored === "light" ? "light" : "dark";
}

export function applyTheme(theme: Theme) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(THEME_KEY, theme);
  window.document.documentElement.dataset.theme = theme;
}

export function toggleTheme(): Theme {
  const next: Theme = currentTheme() === "dark" ? "light" : "dark";
  applyTheme(next);
  return next;
}
