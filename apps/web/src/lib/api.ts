import type { PublishedReport, RoleSummary } from "./types";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export class ApiUnreachable extends Error {}

async function get(path: string): Promise<Response> {
  try {
    return await fetch(`${API_URL}${path}`, { signal: AbortSignal.timeout(5000) });
  } catch {
    throw new ApiUnreachable(`The API at ${API_URL} did not answer.`);
  }
}

export async function getRoles(): Promise<RoleSummary[]> {
  const res = await get("/roles");
  if (!res.ok) throw new ApiUnreachable(`The API answered ${res.status}.`);
  return (await res.json()) as RoleSummary[];
}

/** The newest published report for a role, or null when none is published. */
export async function getReport(slug: string): Promise<PublishedReport | null> {
  const res = await get(`/roles/${encodeURIComponent(slug)}/report`);
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiUnreachable(`The API answered ${res.status}.`);
  return (await res.json()) as PublishedReport;
}
