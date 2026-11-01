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

export function publisher(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
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
