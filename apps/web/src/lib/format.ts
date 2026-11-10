import type { Tier } from "./types";

/** The plan's wording bands: how often something is asked for, in words. */
export function bandWord(share: number): string | null {
  if (share >= 0.6) return "Most roles";
  if (share >= 0.3) return "Many roles";
  if (share >= 0.1) return "Some roles";
  return null;
}

export type ConfidenceLabel = "High" | "Medium" | "Low";

export function confidenceLabel(confidence: number): ConfidenceLabel {
  if (confidence >= 0.75) return "High";
  if (confidence >= 0.5) return "Medium";
  return "Low";
}

export function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

const JOB_BOARDS = new Set([
  "job-boards.greenhouse.io",
  "job-boards.eu.greenhouse.io",
  "boards.greenhouse.io",
  "jobs.lever.co",
  "jobs.eu.lever.co",
  "jobs.ashbyhq.com",
]);

/** Who published a source: the employer for a job-board ad (its board name), else the site. */
export function publisher(url: string): string {
  try {
    const { hostname, pathname } = new URL(url);
    const host = hostname.replace(/^www\./, "");
    if (JOB_BOARDS.has(host)) {
      const board = (pathname.split("/").filter(Boolean)[0] ?? host).replace(/\d+$/, "");
      return board.charAt(0).toUpperCase() + board.slice(1);
    }
    return host;
  } catch {
    return url;
  }
}

export const TIER_LABEL: Record<Tier, string> = {
  posting: "Job posting",
  blog: "Blog",
  forum: "Forum",
  interview: "Interview",
};

const MONTH = new Intl.DateTimeFormat("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });

export function month(iso: string): string {
  return MONTH.format(new Date(iso));
}

/** "UK" rather than the ISO code "GB", which reads like gigabytes next to a number. */
export function place(country: string): string {
  return country.toUpperCase() === "GB" ? "UK" : country;
}
