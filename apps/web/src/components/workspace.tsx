"use client";

import { useState, useTransition } from "react";
import { askTechLead, runTests, type RunState } from "@/app/roles/[slug]/practice/actions";
import type { Project } from "@/lib/types";

function Output({ state }: { state: RunState }) {
  if (state.status === "idle") return null;
  if (state.status === "error") {
    return (
      <p role="alert" className="text-sm text-red-700 dark:text-red-400">
        {state.message}
      </p>
    );
  }
  const tests = state.status === "tests" ? state.tests : state.review.tests;
  return (
    <div className="flex flex-col gap-4" aria-live="polite">
      {state.status === "review" && (
        <section className="rounded-lg border border-zinc-300 p-4 dark:border-zinc-700">
          <h3 className="mb-2 text-sm font-medium uppercase tracking-wide text-zinc-500">
            Your Tech Lead says
          </h3>
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{state.review.review}</p>
          <p className="mt-3 text-xs text-zinc-500">
            Written by {state.review.model}. A review, not a grade: check it against the code.
          </p>
        </section>
      )}
      <section>
        <h3 className="mb-2 text-sm font-medium uppercase tracking-wide text-zinc-500">
          Tests: {tests.timed_out ? "timed out" : tests.passed ? "passed" : "failing"}
        </h3>
        <pre className="max-h-80 overflow-auto rounded-lg bg-zinc-100 p-3 text-xs dark:bg-zinc-900">
          {tests.output || "(no output)"}
        </pre>
      </section>
    </div>
  );
}

export function Workspace({ slug, project }: { slug: string; project: Project }) {
  const { tickets, scenario, company_context: company } = project.blueprint;
  const [files, setFiles] = useState<Record<string, string>>(project.files);
  const [open, setOpen] = useState(Object.keys(project.files).find((p) => p.endsWith(".py")) ?? "");
  const [ticketKey, setTicketKey] = useState(tickets[0].key);
  const [state, setState] = useState<RunState>({ status: "idle" });
  const [pending, start] = useTransition();
  const ticket = tickets.find((t) => t.key === ticketKey) ?? tickets[0];
  const paths = Object.keys(files).sort();
  // Only send what the learner changed; the server already has the rest.
  const changed = Object.fromEntries(
    Object.entries(files).filter(([p, t]) => project.files[p] !== t),
  );

  return (
    <div className="flex flex-col gap-10">
      <section className="flex flex-col gap-2">
        <h2 className="text-xl font-semibold tracking-tight">The situation</h2>
        <p className="text-zinc-700 dark:text-zinc-300">{scenario}</p>
        <p className="text-sm text-zinc-500">{company}</p>
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold tracking-tight">Your tickets</h2>
        <div className="flex flex-wrap gap-2" role="tablist">
          {tickets.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={t.key === ticketKey}
              onClick={() => setTicketKey(t.key)}
              className={`rounded-full border px-3 py-1 text-sm ${
                t.key === ticketKey
                  ? "border-zinc-900 bg-zinc-900 text-white dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900"
                  : "border-zinc-300 dark:border-zinc-700"
              }`}
            >
              {t.key} · day {t.due_day}
            </button>
          ))}
        </div>
        <div>
          <h3 className="font-medium">{ticket.title}</h3>
          <p className="mt-1 text-sm text-zinc-700 dark:text-zinc-300">{ticket.description}</p>
          <ul className="mt-2 list-disc pl-5 text-sm text-zinc-600 dark:text-zinc-400">
            {ticket.acceptance_criteria.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-xl font-semibold tracking-tight">Your project</h2>
        <div className="flex flex-wrap gap-2">
          {paths.map((p) => (
            <button
              key={p}
              onClick={() => setOpen(p)}
              aria-pressed={p === open}
              className={`rounded border px-2 py-1 font-mono text-xs ${
                p === open ? "border-zinc-900 dark:border-zinc-100" : "border-zinc-300 dark:border-zinc-700"
              }`}
            >
              {p}
              {project.files[p] !== files[p] && " •"}
            </button>
          ))}
        </div>
        <textarea
          aria-label={`Contents of ${open}`}
          value={files[open] ?? ""}
          onChange={(e) => setFiles({ ...files, [open]: e.target.value })}
          spellCheck={false}
          rows={22}
          className="rounded-lg border border-zinc-300 bg-transparent p-3 font-mono text-xs leading-relaxed dark:border-zinc-700"
        />
        <p className="text-xs text-zinc-500">
          Edit the code, then run. The given tests cannot be changed.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <button
            disabled={pending}
            onClick={() => start(async () => setState(await runTests(slug, changed)))}
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900"
          >
            {pending ? "Working…" : "Run tests"}
          </button>
          <button
            disabled={pending}
            onClick={() => start(async () => setState(await askTechLead(slug, ticket.key, changed)))}
            className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium disabled:opacity-60 dark:border-zinc-700"
          >
            Ask the Tech Lead to review {ticket.key}
          </button>
          <button
            disabled={pending || Object.keys(changed).length === 0}
            onClick={() => {
              setFiles(project.files);
              setState({ status: "idle" });
            }}
            className="text-sm text-zinc-500 underline-offset-2 hover:underline"
          >
            Reset
          </button>
        </div>
        <Output state={state} />
      </section>
    </div>
  );
}
