import { percent } from "@/lib/format";
import type { SkillStat } from "@/lib/types";

const SHOWN = 12;

function Row({ s }: { s: SkillStat }) {
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1.5 sm:grid-cols-[13rem_minmax(0,1fr)_7.5rem]">
      <span className="leading-snug">{s.label}</span>
      <span className="text-right tabular-nums sm:order-last">
        <span className="font-medium">{percent(s.share)}</span>{" "}
        <span className="text-xs text-muted">
          {percent(s.ci_low)}–{percent(s.ci_high)}
        </span>
      </span>
      <span
        className="relative col-span-2 h-3 rounded-sm bg-page sm:col-span-1"
        role="img"
        aria-label={`${percent(s.share)} of ${s.n} postings, likely between ${percent(s.ci_low)} and ${percent(s.ci_high)}`}
      >
        <span
          className="absolute inset-y-0 rounded-sm bg-brand-soft"
          style={{ left: `${s.ci_low * 100}%`, width: `${(s.ci_high - s.ci_low) * 100}%` }}
        />
        <span className="absolute inset-y-0 left-0 rounded-sm bg-brand" style={{ width: `${s.share * 100}%` }} />
      </span>
    </li>
  );
}

export function AskedFor({ skills }: { skills: SkillStat[] }) {
  const ranked = [...skills].sort((a, b) => b.share - a.share);
  const top = ranked.slice(0, SHOWN);
  const rest = ranked.slice(SHOWN);
  return (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-col gap-3">
        {top.map((s) => (
          <Row key={s.skill_id} s={s} />
        ))}
      </ul>
      {rest.length > 0 && (
        <details className="group">
          <summary className="w-fit cursor-pointer list-none text-sm text-muted underline decoration-line underline-offset-4 hover:text-ink">
            <span className="group-open:hidden">Show {rest.length} more skills</span>
            <span className="hidden group-open:inline">Show fewer</span>
          </summary>
          <ul className="mt-3 flex flex-col gap-3">
            {rest.map((s) => (
              <Row key={s.skill_id} s={s} />
            ))}
          </ul>
        </details>
      )}
      <p className="text-xs text-muted">
        The dark bar is the share of postings that mention the skill. The light band is where the
        true share probably lies (95% interval): wide, because the sample is small.
      </p>
    </div>
  );
}
