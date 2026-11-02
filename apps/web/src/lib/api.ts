import type { Internship, Project, PublishedReport, RoleSummary } from "./types";

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

/** The approved practice project for a role, or null when there is none yet. */
export async function getProject(slug: string): Promise<Project | null> {
  const res = await get(`/roles/${encodeURIComponent(slug)}/project`);
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiUnreachable(`The API answered ${res.status}.`);
  return (await res.json()) as Project;
}

/** The scripted week around the practice project, or null when it has none. */
export async function getInternship(slug: string): Promise<Internship | null> {
  const res = await get(`/roles/${encodeURIComponent(slug)}/internship`);
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiUnreachable(`The API answered ${res.status}.`);
  return (await res.json()) as Internship;
}
