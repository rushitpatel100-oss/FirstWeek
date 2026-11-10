"use client";

import { useActionState } from "react";
import { compareBackground, type GapState } from "@/app/roles/[slug]/actions";
import { percent } from "@/lib/format";
import type { GapLine } from "@/lib/types";
import { button } from "./ui";

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
            <h3 className="mb-2 text-lg font-semibold">
              {title} ({group.length})
            </h3>
            <ul className="space-y-2">
              {group.map((line) => (
                <li key={line.skill_id} className="text-sm">
                  <span className="font-medium">{line.label}</span>{" "}
                  <span className="text-muted">(asked by {percent(line.share)} of postings)</span>
                  <br />
                  <span className="text-muted">{line.reason}</span>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
      <p className="text-xs text-muted">
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
          className="rounded-lg border border-line bg-page p-3 text-sm leading-relaxed placeholder:text-muted"
        />
        <div className="flex flex-wrap items-center gap-4">
          <button
            type="submit"
            disabled={pending}
            className={button.primary}
          >
            {pending ? "Comparing…" : "Compare my background"}
          </button>
          <p className="text-xs text-muted">
            Your text is sent to Claude to make the comparison and is not stored.
          </p>
        </div>
      </form>
      {state.status === "error" && (
        <p role="alert" className="text-sm text-danger">
          {state.message}
        </p>
      )}
      {state.status === "done" && <Result state={state} />}
    </div>
  );
}
