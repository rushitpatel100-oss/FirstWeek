import { ConfidenceBadge } from "./confidence-badge";
import { publisher, TIER_LABEL, month } from "@/lib/format";
import type { Claim } from "@/lib/types";

function Sources({ claim }: { claim: Claim }) {
  const n = claim.citations.length;
  return (
    <details className="group mt-1.5 text-sm">
      <summary className="cursor-pointer text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200">
        {n} {n === 1 ? "source" : "sources"}
      </summary>
      <ul className="mt-2 space-y-3 border-l-2 border-zinc-200 pl-4 dark:border-zinc-800">
        {claim.citations.map((c) => (
          <li key={`${c.source_url}-${c.quote}`}>
            <blockquote className="text-zinc-700 dark:text-zinc-300">“{c.quote}”</blockquote>
            <p className="mt-0.5 text-xs text-zinc-500">
              {TIER_LABEL[c.tier]} ·{" "}
              <a
                href={c.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2 hover:text-zinc-800 dark:hover:text-zinc-200"
              >
                {publisher(c.source_url)}
              </a>
              {c.published ? ` · ${month(c.published)}` : " · undated"}
            </p>
          </li>
        ))}
      </ul>
    </details>
  );
}

export function ClaimList({ claims }: { claims: Claim[] }) {
  if (claims.length === 0) return null;
  return (
    <ul className="space-y-5">
      {claims.map((claim) => (
        <li key={claim.text} className={claim.confidence < 0.5 ? "opacity-80" : undefined}>
          <p className="flex items-start gap-3">
            <span className="flex-1">{claim.text}</span>
            <ConfidenceBadge confidence={claim.confidence} />
          </p>
          <Sources claim={claim} />
        </li>
      ))}
    </ul>
  );
}
