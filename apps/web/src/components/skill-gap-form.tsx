"use client";

import { useActionState } from "react";
import { compareBackground, type GapState } from "@/app/roles/[slug]/actions";
import { percent } from "@/lib/format";
import type { GapLine } from "@/lib/types";

const GROUPS: { status: GapLine["status"]; title: string }[] = [
  { status: "have", title: "You have" },
  { status: "transferable", title: "Close to what you have" },
  { status: "missing", title: "Missing" },
];

function Result({ state }: { state: Extract<GapState, { status: "done" }> }) {
  const { lines, coverage } = state.result;
  return (
    <div className="flex flex-col gap-6" aria-live="polite">
      <p className="text-lg">
        Weighted by how often postings ask for each skill, your background covers{" "}
        <strong className="tabular-nums">{percent(coverage)}</strong> of what this role asks for.
        A close match counts half.
      </p>
      {GROUPS.map(({ status, title }) => {
        const group = lines.filter((l) => l.status === status);
        if (group.length === 0) return null;
        return (
          <section key={status}>
            <h3 className="mb-2 text-sm font-medium uppercase tracking-wide text-zinc-500">
              {title} ({group.length})
            </h3>
            <ul className="space-y-2">
              {group.map((line) => (
                <li key={line.skill_id} className="text-sm">
                  <span className="font-medium">{line.label}</span>{" "}
                  <span className="text-zinc-500">(asked by {percent(line.share)} of postings)</span>
                  <br />
                  <span className="text-zinc-700 dark:text-zinc-300">{line.reason}</span>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
      <p className="text-xs text-zinc-500">
        The skills and shares come from the collected postings. Whether your background matches
        them is a model&apos;s judgement of your own words, so check it against what you know.
      </p>
    </div>
  );
}

export function SkillGapForm({ slug }: { slug: string }) {
  const [state, action, pending] = useActionState<GapState, FormData>(compareBackground, {
    status: "idle",
  });
  return (
    <div className="flex flex-col gap-5">
      <form action={action} className="flex flex-col gap-3">
        <input type="hidden" name="slug" value={slug} />
        <label htmlFor="background" className="text-sm font-medium">
          Your background
        </label>
        <textarea
          id="background"
          name="background"
          required
          maxLength={2000}
          rows={5}
          placeholder="For example: I was a mechanical engineer for six years. I write Python scripts to analyse test data."
          className="rounded-lg border border-zinc-300 bg-transparent p-3 text-sm dark:border-zinc-700"
        />
        <div className="flex flex-wrap items-center gap-4">
          <button
            type="submit"
            disabled={pending}
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900"
          >
            {pending ? "Comparing…" : "Compare"}
          </button>
          <p className="text-xs text-zinc-500">
            Your text is sent to Claude to make the comparison and is not stored.
          </p>
        </div>
      </form>
      {state.status === "error" && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-400">
          {state.message}
        </p>
      )}
      {state.status === "done" && <Result state={state} />}
    </div>
  );
}
