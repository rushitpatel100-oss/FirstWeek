"use server";

import type { Review, TestRun, Turn, WeekReview } from "@/lib/types";

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
  502: "The Tech Lead's answer could not be used. Please try again.",
  503: "The Tech Lead is busy or out of free quota. You can still run the tests.",
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

export type ChatState =
  | { status: "ok"; reply: string }
  | { status: "error"; message: string };

export type WeekState =
  | { status: "idle" }
  | { status: "error"; message: string }
  | { status: "done"; review: WeekReview };

const TEAM_MESSAGES: Record<number, string> = {
  404: "This project has no internship yet.",
  422: "That message cannot be sent.",
  429: "Too many messages just now. Please try again in a while.",
  502: "The supervisor's answer could not be used. Please try again.",
  503: "The team is busy or out of free quota. You can keep working on the code and try again later.",
};

async function internshipPost(slug: string, path: string, body: unknown, ms: number) {
  return fetch(`${API_URL}/roles/${encodeURIComponent(slug)}/internship/${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(ms),
  });
}

function teamFailure(status: number): { status: "error"; message: string } {
  return {
    status: "error",
    message: TEAM_MESSAGES[status] ?? "Something went wrong. Please try again.",
  };
}

/** One message to a colleague; they answer in character. */
export async function sendMessage(
  slug: string,
  colleague: string,
  day: number,
  message: string,
  history: Turn[],
): Promise<ChatState> {
  try {
    const res = await internshipPost(slug, "chat", { colleague, day, message, history }, 60_000);
    if (!res.ok) return teamFailure(res.status);
    return { status: "ok", reply: ((await res.json()) as { reply: string }).reply };
  } catch {
    return { status: "error", message: "That took too long or the API did not answer." };
  }
}

/** Ends the week: the API runs the tests and the supervisor writes the review. */
export async function finishWeek(slug: string, files: Files, chat: string[]): Promise<WeekState> {
  try {
    const res = await internshipPost(slug, "verdict", { files, chat }, 180_000);
    if (!res.ok) return teamFailure(res.status);
    return { status: "done", review: (await res.json()) as WeekReview };
  } catch {
    return { status: "error", message: "That took too long or the API did not answer." };
  }
}
