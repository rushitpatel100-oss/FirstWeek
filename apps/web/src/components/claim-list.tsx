import { ConfidenceBadge } from "./confidence-badge";
import { month, publisher, TIER_LABEL } from "@/lib/format";
import type { Claim } from "@/lib/types";

function Sources({ claim }: { claim: Claim }) {
  const n = claim.citations.length;
  return (
    <details className="group mt-2 text-sm">
      <summary className="w-fit cursor-pointer list-none text-muted hover:text-ink">
        <span className="underline decoration-line underline-offset-4 group-open:hidden">
          Show {n === 1 ? "the source" : `${n} sources`}
        </span>
        <span className="hidden underline decoration-line underline-offset-4 group-open:inline">
          Hide {n === 1 ? "the source" : "sources"}
        </span>
      </summary>
      <ul className="mt-3 flex flex-col gap-4">
        {claim.citations.map((c) => (
          <li key={`${c.source_url}-${c.quote}`} className="flex flex-col gap-1.5">
            <blockquote className="leading-relaxed">
              <mark className="box-decoration-clone rounded-sm bg-mark px-1 text-mark-ink">{c.quote}</mark>
            </blockquote>
            <p className="text-xs text-muted">
              {TIER_LABEL[c.tier]} from{" "}
              <a
                href={c.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-ink underline decoration-line underline-offset-2 hover:decoration-ink"
              >
                {publisher(c.source_url)}
              </a>
              {c.published ? `, ${month(c.published)}` : ", undated"}
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
    <ul className="flex flex-col divide-y divide-line">
      {claims.map((claim) => (
        <li key={claim.text} className="py-4 first:pt-0 last:pb-0">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
            <p className="max-w-[68ch] leading-relaxed">{claim.text}</p>
            <ConfidenceBadge confidence={claim.confidence} />
          </div>
          <Sources claim={claim} />
        </li>
      ))}
    </ul>
  );
}
