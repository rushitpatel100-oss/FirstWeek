/** Shared class names, so a button looks and reads the same on every page. */

const base =
  "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-55";

export const button = {
  primary: `${base} bg-brand text-on-brand hover:brightness-110`,
  secondary: `${base} border border-line bg-paper text-ink hover:border-muted`,
  quiet: `${base} px-2 text-muted hover:text-ink`,
} as const;

export const panel = "rounded-xl border border-line bg-paper";

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function article(noun: string): string {
  return /^[aeiou]/i.test(noun) ? "an" : "a";
}
