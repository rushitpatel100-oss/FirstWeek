import { confidenceLabel, type ConfidenceLabel } from "@/lib/format";

const WORD: Record<ConfidenceLabel, string> = {
  High: "Strong evidence",
  Medium: "Some evidence",
  Low: "Thin evidence",
};

const STYLE: Record<ConfidenceLabel, string> = {
  High: "bg-brand text-on-brand",
  Medium: "bg-brand-soft text-ink",
  Low: "border border-dashed border-muted text-muted",
};

const MEANING: Record<ConfidenceLabel, string> = {
  High: "Several independent, recent sources back this",
  Medium: "One or two sources back this",
  Low: "One source, or an old one, backs this. Treat it as a lead, not a finding",
};

// The words carry the meaning; the fill only reinforces it.
export function ConfidenceBadge({ confidence }: { confidence: number }) {
  const label = confidenceLabel(confidence);
  return (
    <span
      title={`${MEANING[label]} (score ${confidence.toFixed(2)})`}
      className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium ${STYLE[label]}`}
    >
      {WORD[label]}
    </span>
  );
}
