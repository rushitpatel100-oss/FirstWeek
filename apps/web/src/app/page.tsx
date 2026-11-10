import Link from "next/link";
import { Suspense } from "react";
import { button, panel } from "@/components/ui";
import { getProject, getReport, getRoles } from "@/lib/api";
import { month, percent, place } from "@/lib/format";
import type { RoleSummary } from "@/lib/types";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

const WEEK = [
  ["Mon", "Meet your team and pick up your first ticket"],
  ["Tue", "Ask questions and read the code"],
  ["Wed", "Make the fix and run the tests"],
  ["Thu", "More work lands in your inbox"],
  ["Fri", "Your supervisor reviews the week"],
] as const;

type Ready = { status: string; checks: Record<string, string> };

async function SystemStatus() {
  let ready: Ready | null = null;
  try {
    const res = await fetch(`${API_URL}/ready`, { signal: AbortSignal.timeout(5000) });
    ready = (await res.json()) as Ready;
  } catch {
    ready = null;
  }
  if (!ready) return <p className="text-danger">The API at {API_URL} is not answering.</p>;
  return (
    <ul className="grid gap-1 sm:grid-cols-2">
      {Object.entries(ready.checks).map(([name, state]) => (
        <li key={name} className="flex justify-between gap-6">
          <span className="capitalize">{name}</span>
          <span className={state === "ok" ? "text-brand" : "text-danger"}>{state}</span>
        </li>
      ))}
    </ul>
  );
}

async function RoleRow({ role }: { role: RoleSummary }) {
  const [published, project] = await Promise.all([
    getReport(role.slug).catch(() => null),
    getProject(role.slug).catch(() => null),
  ]);
  const report = published?.report;
  const lead = report?.summary[0]?.text;
  const top = report ? [...report.asked_for].sort((a, b) => b.share - a.share).slice(0, 4) : [];
  return (
    <li className={`${panel} grid gap-5 p-5 sm:p-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end`}>
      <div className="flex flex-col gap-3">
        <h3 className="text-2xl font-semibold">{role.name}</h3>
        {lead && <p className="max-w-2xl text-muted">{lead}</p>}
        {top.length > 0 && (
          <ul className="flex flex-wrap gap-2 text-sm" aria-label="Most asked-for skills">
            {top.map((s) => (
              <li key={s.skill_id} className="rounded-md bg-page px-2.5 py-1">
                {s.label} <span className="tabular-nums text-muted">{percent(s.share)}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="text-sm text-muted">
          From {role.sample_size} {place(role.country)} job postings, published {month(role.published_at)}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Link href={`/roles/${role.slug}`} className={button.secondary}>
          Read the report
        </Link>
        {project && (
          <Link href={`/roles/${role.slug}/practice`} className={button.primary}>
            Start your first week
          </Link>
        )}
      </div>
    </li>
  );
}

async function Roles() {
  let roles;
  try {
    roles = await getRoles();
  } catch {
    return (
      <p className={`${panel} p-5 text-danger`}>
        The roles could not be loaded because the API is not answering. Start it with{" "}
        <code className="font-mono">make api</code>, then reload this page.
      </p>
    );
  }
  if (roles.length === 0) {
    return (
      <p className={`${panel} p-5 text-muted`}>
        No role is published yet. Run <code className="font-mono">make seed-reports</code> to add
        the three researched reports, then reload this page.
      </p>
    );
  }
  return (
    <ul className="grid gap-4">
      {roles.map((role) => (
        <RoleRow key={role.slug} role={role} />
      ))}
    </ul>
  );
}

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-16 px-4 py-12 sm:px-6 sm:py-20">
      <section className="grid items-center gap-10 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <div className="flex flex-col gap-6">
          <h1 className="text-5xl font-bold leading-[1.02] sm:text-6xl lg:text-7xl">
            Try the job before you take it.
          </h1>
          <p className="max-w-xl text-lg leading-relaxed text-muted">
            See what an AI role really involves, from real UK job postings and the people doing the
            work. Then spend a week doing it: a made-up company, real-looking tickets and AI
            colleagues who review what you build.
          </p>
          <div>
            <a href="#roles" className={button.primary}>
              Choose a role
            </a>
          </div>
        </div>
        <ol className={`${panel} divide-y divide-line overflow-hidden`} aria-label="What a week looks like">
          {WEEK.map(([day, what], i) => (
            <li key={day} className="flex items-center gap-4 px-5 py-4">
              <span
                className={`grid h-11 w-11 shrink-0 place-items-center rounded-lg font-display text-sm font-semibold ${
                  i === 0 ? "bg-brand text-on-brand" : "bg-page text-muted"
                }`}
              >
                {day}
              </span>
              <span>{what}</span>
            </li>
          ))}
        </ol>
      </section>

      <section id="roles" className="flex scroll-mt-8 flex-col gap-5">
        <div className="flex flex-col gap-1">
          <h2 className="text-3xl font-semibold">Pick a role</h2>
          <p className="text-muted">Start with the report, or go straight into the week.</p>
        </div>
        <Suspense fallback={<p className="text-muted">Loading the roles…</p>}>
          <Roles />
        </Suspense>
      </section>

      <details className="text-sm text-muted">
        <summary className="cursor-pointer hover:text-ink">Service status</summary>
        <div className="mt-3 max-w-md">
          <Suspense fallback={<p>Checking the services…</p>}>
            <SystemStatus />
          </Suspense>
        </div>
      </details>
    </main>
  );
}
