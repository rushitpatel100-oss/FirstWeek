import Link from "next/link";
import { Suspense } from "react";
import { getRoles } from "@/lib/api";
import { month } from "@/lib/format";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

type Ready = { status: string; checks: Record<string, string> };

async function SystemStatus() {
  let ready: Ready | null = null;
  try {
    const res = await fetch(`${API_URL}/ready`, { signal: AbortSignal.timeout(5000) });
    ready = (await res.json()) as Ready;
  } catch {
    ready = null;
  }

  if (!ready) {
    return <p className="text-sm text-red-700 dark:text-red-400">API unreachable at {API_URL}</p>;
  }
  return (
    <ul className="grid gap-1 text-sm">
      {Object.entries(ready.checks).map(([name, state]) => (
        <li key={name} className="flex justify-between gap-8">
          <span className="capitalize">{name}</span>
          <span className={state === "ok" ? "text-emerald-700 dark:text-emerald-400" : "text-red-700 dark:text-red-400"}>
            {state}
          </span>
        </li>
      ))}
    </ul>
  );
}

async function Roles() {
  let roles;
  try {
    roles = await getRoles();
  } catch {
    return <p className="text-sm text-red-700 dark:text-red-400">The API did not answer. Try again in a moment.</p>;
  }
  if (roles.length === 0) {
    return <p className="text-zinc-600 dark:text-zinc-400">No role report is published yet.</p>;
  }
  return (
    <ul className="grid gap-3">
      {roles.map((role) => (
        <li key={role.slug}>
          <Link
            href={`/roles/${role.slug}`}
            className="flex items-baseline justify-between gap-6 rounded-lg border border-zinc-200 p-4 hover:border-zinc-400 dark:border-zinc-800 dark:hover:border-zinc-600"
          >
            <span className="text-lg font-medium">{role.name}</span>
            <span className="text-sm text-zinc-500">
              {role.sample_size} {role.country} postings · published {month(role.published_at)}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-10 px-6 py-20">
      <header className="flex flex-col gap-3">
        <h1 className="text-4xl font-semibold tracking-tight">FirstWeek</h1>
        <p className="text-lg text-zinc-600 dark:text-zinc-400">
          Live your first week in a new AI role. See what the job really involves, backed by
          evidence, then do it with AI colleagues who review your work.
        </p>
      </header>

      <section className="flex flex-col gap-4">
        <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-500">
          Role Reality Reports
        </h2>
        <Suspense fallback={<p className="text-sm text-zinc-500">Loading roles…</p>}>
          <Roles />
        </Suspense>
      </section>

      <section className="rounded-lg border border-zinc-200 p-5 dark:border-zinc-800">
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-zinc-500">
          System status
        </h2>
        <Suspense fallback={<p className="text-sm text-zinc-500">Checking services…</p>}>
          <SystemStatus />
        </Suspense>
      </section>
    </main>
  );
}
