import { confidenceLabel, type ConfidenceLabel } from "@/lib/format";

const STYLE: Record<ConfidenceLabel, string> = {
  High: "border-emerald-600/40 bg-emerald-50 text-emerald-900 dark:border-emerald-400/40 dark:bg-emerald-950 dark:text-emerald-200",
  Medium:
    "border-amber-600/40 bg-amber-50 text-amber-900 dark:border-amber-400/40 dark:bg-amber-950 dark:text-amber-200",
  Low: "border-zinc-400/60 bg-zinc-100 text-zinc-700 dark:border-zinc-500/60 dark:bg-zinc-900 dark:text-zinc-300",
};

const MEANING: Record<ConfidenceLabel, string> = {
  High: "Several independent, recent sources back this",
  Medium: "A couple of sources, or one strong recent one, back this",
  Low: "One source, or an old one, backs this. Treat it as a lead, not a finding",
};

// The word and the number carry the meaning; colour only reinforces it.
export function ConfidenceBadge({ confidence }: { confidence: number }) {
  const label = confidenceLabel(confidence);
  return (
    <span
      title={MEANING[label]}
      className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${STYLE[label]}`}
    >
      {label}
      <span className="tabular-nums opacity-70">{confidence.toFixed(2)}</span>
    </span>
  );
}
