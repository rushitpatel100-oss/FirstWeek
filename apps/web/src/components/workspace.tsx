"use client";

import { useEffect, useMemo, useRef, useState, useTransition } from "react";
import { askTechLead, runTests, type RunState } from "@/app/roles/[slug]/practice/actions";
import type { Project, TestRun } from "@/lib/types";
import { button, panel } from "./ui";

const INDENT = "    ";

/** pytest's last line, e.g. "2 failed, 4 passed in 0.31s", as a short summary. */
function testSummary(tests: TestRun): string {
  if (tests.timed_out) return "The tests took too long and were stopped";
  const line = tests.output
    .trim()
    .split("\n")
    .reverse()
    .find((l) => /\b(passed|failed|error)/.test(l));
  const counts = line?.replace(/=+/g, "").replace(/\s+in\s+[\d.]+s.*$/, "").trim();
  return counts ? `${tests.passed ? "All tests pass" : "Some tests fail"}: ${counts}` : tests.passed ? "All tests pass" : "The tests fail";
}

function Output({ state }: { state: RunState }) {
  if (state.status === "idle") return null;
  if (state.status === "error") {
    return (
      <p role="alert" className="rounded-lg border border-danger/40 p-4 text-sm text-danger">
        {state.message}
      </p>
    );
  }
  const tests = state.status === "tests" ? state.tests : state.review.tests;
  const ok = tests.passed && !tests.timed_out;
  return (
    <div className="flex flex-col gap-4" aria-live="polite">
      {state.status === "review" && (
        <section className={`${panel} flex flex-col gap-3 p-5`}>
          <h3 className="text-lg font-semibold">Your Tech Lead&apos;s review</h3>
          <p className="whitespace-pre-wrap leading-relaxed">{state.review.review}</p>
          <p className="text-xs text-muted">
            Written by {state.review.model}. A review, not a grade: check it against your code.
          </p>
        </section>
      )}
      <details className={`${panel} overflow-hidden`} open={!ok}>
        <summary className="flex cursor-pointer items-center gap-3 px-4 py-3">
          <span
            aria-hidden
            className={`h-2.5 w-2.5 shrink-0 rounded-full ${ok ? "bg-brand" : "bg-danger"}`}
          />
          <span className="font-medium">{testSummary(tests)}</span>
          <span className="ml-auto text-sm text-muted">Test output</span>
        </summary>
        <pre className="max-h-80 overflow-auto bg-code-bg p-4 font-mono text-xs leading-relaxed text-code-ink">
          {tests.output || "(no output)"}
        </pre>
      </details>
    </div>
  );
}

function Editor({
  path,
  value,
  readOnly,
  onChange,
}: {
  path: string;
  value: string;
  readOnly: boolean;
  onChange: (text: string) => void;
}) {
  const gutter = useRef<HTMLPreElement>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const leaving = useRef(false);
  const lines = Math.max(value.split("\n").length, 1);

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Escape") {
      leaving.current = true; // the next Tab moves focus out of the editor
      return;
    }
    if (e.key !== "Tab" || e.shiftKey || leaving.current || readOnly) {
      leaving.current = false;
      return;
    }
    e.preventDefault();
    const el = e.currentTarget;
    const { selectionStart: start, selectionEnd: end } = el;
    onChange(value.slice(0, start) + INDENT + value.slice(end));
    requestAnimationFrame(() => {
      area.current?.setSelectionRange(start + INDENT.length, start + INDENT.length);
    });
  }

  return (
    <div className="flex h-[30rem] overflow-hidden bg-code-bg font-mono text-[13px] leading-6">
      <pre
        ref={gutter}
        aria-hidden
        className="select-none overflow-hidden py-3 pl-3 pr-3 text-right text-code-dim"
      >
        {Array.from({ length: lines }, (_, i) => i + 1).join("\n")}
      </pre>
      <textarea
        ref={area}
        aria-label={`Contents of ${path}. Tab indents; press Escape then Tab to leave the editor.`}
        value={value}
        readOnly={readOnly}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        onScroll={(e) => {
          if (gutter.current) gutter.current.scrollTop = e.currentTarget.scrollTop;
        }}
        spellCheck={false}
        wrap="off"
        className="min-w-0 flex-1 resize-none bg-transparent py-3 pr-4 text-code-ink caret-mark outline-none"
      />
    </div>
  );
}

function firstFile(files: Record<string, string>): string {
  const paths = Object.keys(files).sort();
  return (
    paths.find((p) => /^readme\.md$/i.test(p)) ??
    paths.find((p) => p.endsWith(".py") && !p.endsWith("__init__.py") && files[p].trim()) ??
    paths[0] ??
    ""
  );
}

export function Workspace({
  slug,
  project,
  onFiles,
  briefOpen = true,
}: {
  slug: string;
  project: Project;
  /** Called with the changed files whenever they change (the internship sends them at the end). */
  onFiles?: (changed: Record<string, string>) => void;
  briefOpen?: boolean;
}) {
  const { tickets, scenario, company_context: company } = project.blueprint;
  const [files, setFiles] = useState<Record<string, string>>(project.files);
  const [open, setOpen] = useState(() => firstFile(project.files));
  const [ticketKey, setTicketKey] = useState(tickets[0]?.key ?? "");
  const [state, setState] = useState<RunState>({ status: "idle" });
  const [pending, start] = useTransition();
  const [busy, setBusy] = useState<"tests" | "review" | null>(null);
  const ticket = tickets.find((t) => t.key === ticketKey) ?? tickets[0];
  const paths = Object.keys(files).sort();
  // Only send what the learner changed; the server already has the rest.
  const changed = useMemo(
    () => Object.fromEntries(Object.entries(files).filter(([p, t]) => project.files[p] !== t)),
    [files, project.files],
  );
  const nChanged = Object.keys(changed).length;
  // The server keeps the given tests as they are (simulation workspace.with_edits).
  const isGivenTest = (p: string) => p.startsWith("tests/") && p in project.files;

  useEffect(() => {
    onFiles?.(changed);
  }, [onFiles, changed]);

  function run(kind: "tests" | "review") {
    setBusy(kind);
    start(async () => {
      setState(kind === "tests" ? await runTests(slug, changed) : await askTechLead(slug, ticket.key, changed));
      setBusy(null);
    });
  }

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <details className={`${panel} group p-5`} open={briefOpen}>
        <summary className="flex cursor-pointer list-none items-center justify-between gap-4">
          <h2 className="text-xl font-semibold">The situation</h2>
          <span className="text-sm text-muted group-open:hidden">Show</span>
          <span className="hidden text-sm text-muted group-open:inline">Hide</span>
        </summary>
        <div className="mt-3 flex flex-col gap-2">
          <p className="leading-relaxed">{scenario}</p>
          <p className="text-sm leading-relaxed text-muted">{company}</p>
        </div>
      </details>

      {ticket ? (
        <section className={`${panel} flex flex-col gap-4 p-5`} aria-label="Your tickets">
          <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label="Tickets">
            {tickets.map((t) => (
              <button
                key={t.key}
                role="tab"
                aria-selected={t.key === ticket.key}
                onClick={() => setTicketKey(t.key)}
                className={`rounded-md px-2.5 py-1 font-mono text-xs font-medium ${
                  t.key === ticket.key ? "bg-ink text-paper" : "bg-page text-muted hover:text-ink"
                }`}
              >
                {t.key}
              </button>
            ))}
            <span className="ml-auto text-sm text-muted">Due on day {ticket.due_day}</span>
          </div>
          <div className="flex flex-col gap-2">
            <h2 className="text-xl font-semibold leading-snug">{ticket.title}</h2>
            <p className="leading-relaxed text-muted">{ticket.description}</p>
          </div>
          <div>
            <p className="mb-2 text-sm font-medium">Done when</p>
            <ul className="flex flex-col gap-1.5 text-sm">
              {ticket.acceptance_criteria.map((c) => (
                <li key={c} className="flex gap-2.5">
                  <span aria-hidden className="mt-1 h-3.5 w-3.5 shrink-0 rounded-sm border border-muted" />
                  <span>{c}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      ) : (
        <p className={`${panel} p-5 text-muted`}>No ticket yet. Your first one arrives in your inbox.</p>
      )}

      <section className={`${panel} overflow-hidden`} aria-label="Code">
        <div className="flex flex-col md:flex-row">
          <nav
            aria-label="Files"
            className="flex gap-1 overflow-x-auto border-b border-line p-2 md:w-56 md:shrink-0 md:flex-col md:overflow-visible md:border-b-0 md:border-r"
          >
            {paths.map((p) => {
              const slash = p.lastIndexOf("/");
              return (
                <button
                  key={p}
                  onClick={() => setOpen(p)}
                  aria-current={p === open ? "true" : undefined}
                  title={isGivenTest(p) ? `${p} (given tests can be read, not changed)` : p}
                  className={`flex shrink-0 items-center gap-2 rounded-md px-2.5 py-1.5 text-left font-mono text-xs ${
                    p === open ? "bg-page font-medium text-ink" : "text-muted hover:text-ink"
                  }`}
                >
                  <span className="truncate">
                    <span className="opacity-60">{slash >= 0 ? p.slice(0, slash + 1) : ""}</span>
                    {p.slice(slash + 1)}
                  </span>
                  {project.files[p] !== files[p] && (
                    <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-brand" aria-label="changed" />
                  )}
                </button>
              );
            })}
          </nav>
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2 text-xs text-muted">
              <span className="truncate font-mono">{open}</span>
              {isGivenTest(open) && <span>Given tests: read only</span>}
            </div>
            <Editor
              path={open}
              value={files[open] ?? ""}
              readOnly={isGivenTest(open)}
              onChange={(text) => setFiles({ ...files, [open]: text })}
            />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t border-line p-3">
          <button disabled={pending} onClick={() => run("tests")} className={button.primary}>
            {busy === "tests" ? "Running the tests…" : "Run the tests"}
          </button>
          {ticket && (
            <button disabled={pending} onClick={() => run("review")} className={button.secondary}>
              {busy === "review" ? "Waiting for the review…" : `Ask for a review of ${ticket.key}`}
            </button>
          )}
          <span className="ml-auto text-sm text-muted">
            {nChanged === 0 ? "No changes yet" : `${nChanged} ${nChanged === 1 ? "file" : "files"} changed`}
          </span>
          <button
            disabled={pending || nChanged === 0}
            onClick={() => {
              setFiles(project.files);
              setState({ status: "idle" });
            }}
            className={button.quiet}
          >
            Undo all changes
          </button>
        </div>
      </section>

      <Output state={state} />
    </div>
  );
}
