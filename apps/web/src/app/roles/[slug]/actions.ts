"use server";

import type { GapResult } from "@/lib/types";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export type GapState =
  | { status: "idle" }
  | { status: "error"; message: string }
  | { status: "done"; result: GapResult };

const MESSAGES: Record<number, string> = {
  404: "This role has no published report yet.",
  422: "Write a few lines about your experience first (up to 2,000 characters).",
  429: "Too many comparisons just now. Please try again later.",
  503: "The comparison is not available right now.",
};

/** Sends the background to the API once and returns the result. Nothing is stored here. */
export async function compareBackground(
  _previous: GapState,
  formData: FormData,
): Promise<GapState> {
  const slug = String(formData.get("slug") ?? "");
  const background = String(formData.get("background") ?? "").trim();
  if (!slug || !background) return { status: "error", message: MESSAGES[422] };
  try {
    const res = await fetch(`${API_URL}/roles/${encodeURIComponent(slug)}/skill-gap`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ background }),
      signal: AbortSignal.timeout(60000),
    });
    if (!res.ok) {
      return { status: "error", message: MESSAGES[res.status] ?? "Something went wrong. Please try again." };
    }
    return { status: "done", result: (await res.json()) as GapResult };
  } catch {
    return { status: "error", message: "The comparison took too long or the API did not answer." };
  }
}
