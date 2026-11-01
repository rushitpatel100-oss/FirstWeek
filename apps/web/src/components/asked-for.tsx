import { bandWord, percent } from "@/lib/format";
import type { SkillStat } from "@/lib/types";

const SHOWN = 15;

export function AskedFor({ skills }: { skills: SkillStat[] }) {
  const ranked = [...skills].sort((a, b) => b.share - a.share);
  const cut = ranked[SHOWN - 1]?.share ?? 0;
  const top = ranked.filter((s, i) => i < SHOWN || s.share >= cut);
  const rest = ranked.filter((s) => !top.includes(s) && bandWord(s.share) !== null);
  return (
    <div>
      <ul className="space-y-2.5">
        {top.map((s) => (
          <li key={s.skill_id} className="grid grid-cols-1 items-center gap-x-4 gap-y-1 sm:grid-cols-[minmax(0,12rem)_1fr]">
            <span className="truncate text-sm">{s.label}</span>
            <span className="flex items-center gap-3">
              <span
                className="relative h-2.5 flex-1 rounded-full bg-zinc-200 dark:bg-zinc-800"
                role="img"
                aria-label={`${percent(s.share)} of ${s.n} postings, 95% interval ${percent(s.ci_low)} to ${percent(s.ci_high)}`}
              >
                <span
                  className="absolute inset-y-0 rounded-full bg-zinc-300 dark:bg-zinc-700"
                  style={{ left: `${s.ci_low * 100}%`, width: `${(s.ci_high - s.ci_low) * 100}%` }}
                />
                <span
                  className="absolute inset-y-0 left-0 rounded-full bg-zinc-900 dark:bg-zinc-100"
                  style={{ width: `${s.share * 100}%` }}
                />
              </span>
              <span className="w-28 shrink-0 text-right text-sm tabular-nums">
                {percent(s.share)}{" "}
                <span className="text-xs text-zinc-500">
                  ({percent(s.ci_low)}–{percent(s.ci_high)})
                </span>
              </span>
            </span>
          </li>
        ))}
      </ul>
      {rest.length > 0 && (
        <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">
          <span className="font-medium">Also asked for: </span>
          {rest.map((s) => `${s.label} (${percent(s.share)})`).join(", ")}
        </p>
      )}
      <p className="mt-3 text-xs text-zinc-500">
        Bars show the share of postings that mention the skill; the lighter band is the 95%
        interval, which is wide because the sample is small.
      </p>
    </div>
  );
}
