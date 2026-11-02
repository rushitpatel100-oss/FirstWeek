"use server";

import type { Review, TestRun } from "@/lib/types";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export type RunState =
  | { status: "idle" }
  | { status: "error"; message: string }
  | { status: "tests"; tests: TestRun }
  | { status: "review"; review: Review };

const MESSAGES: Record<number, string> = {
  404: "This role has no practice project yet.",
  422: "That change cannot be run. Check the file names and that each file is plain text.",
  429: "Too many runs just now. Please try again in a while.",
  503: "The code runner or the Tech Lead is not available right now. Please try again later.",
};

type Files = Record<string, string>;

async function post(slug: string, path: string, body: unknown, ms: number): Promise<Response> {
  return fetch(`${API_URL}/roles/${encodeURIComponent(slug)}/project/${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(ms),
  });
}

function failure(status: number): RunState {
  return { status: "error", message: MESSAGES[status] ?? "Something went wrong. Please try again." };
}

const TIMEOUT: RunState = { status: "error", message: "That took too long or the API did not answer." };

/** Runs the learner's files against the project's tests in the sandbox. */
export async function runTests(slug: string, files: Files): Promise<RunState> {
  try {
    const res = await post(slug, "tests", { files }, 90_000);
    return res.ok ? { status: "tests", tests: (await res.json()) as TestRun } : failure(res.status);
  } catch {
    return TIMEOUT;
  }
}

/** Asks the Tech Lead to review the files against one ticket. The API runs the tests itself. */
export async function askTechLead(slug: string, ticket: string, files: Files): Promise<RunState> {
  try {
    const res = await post(slug, "review", { ticket, files }, 150_000);
    return res.ok ? { status: "review", review: (await res.json()) as Review } : failure(res.status);
  } catch {
    return TIMEOUT;
  }
}
