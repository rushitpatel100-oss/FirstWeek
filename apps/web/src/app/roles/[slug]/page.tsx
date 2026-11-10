import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { AskedFor } from "@/components/asked-for";
import { ClaimList } from "@/components/claim-list";
import { SkillGapForm } from "@/components/skill-gap-form";
import { button, panel } from "@/components/ui";
import { ApiUnreachable, getProject, getReport } from "@/lib/api";
import { month, place } from "@/lib/format";
import type { Claim } from "@/lib/types";

export const metadata: Metadata = { title: "Role Reality Report" };

const SECTIONS = [
  ["short", "In short"],
  ["skills", "What employers ask for"],
  ["job", "What the job involves"],
  ["day", "Day to day"],
  ["hard", "The hard parts"],
  ["compare", "How you compare"],
] as const;

function Section({
  id,
  title,
  hint,
  children,
}: {
  id: string;
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className={`${panel} flex scroll-mt-6 flex-col gap-5 p-5 sm:p-7`}>
      <div className="flex flex-col gap-1">
        <h2 className="text-2xl font-semibold">{title}</h2>
        {hint && <p className="text-sm text-muted">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

function Claims({ claims }: { claims: Claim[] }) {
  return claims.length > 0 ? (
    <ClaimList claims={claims} />
  ) : (
    <p className="text-sm text-muted">Nothing here passed the evidence checks yet.</p>
  );
}

async function Report({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  let published;
  try {
    published = await getReport(slug);
  } catch (error) {
    if (error instanceof ApiUnreachable) {
      return (
        <p className={`${panel} p-5 text-danger`}>
          {error.message} Start it with <code className="font-mono">make api</code>, then reload.
        </p>
      );
    }
    throw error;
  }
  if (!published) notFound();
  const hasProject = await getProject(slug).then(
    (p) => p !== null,
    () => false,
  );

  const { report } = published;
  const [from, to] = report.date_range;
  const practitioner = [...report.day_to_day, ...report.typical_week];
  const researched = report.provenance?.method === "researched";
  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-5 pb-2">
        <Link href="/#roles" className="w-fit text-sm text-muted hover:text-ink">
          All roles
        </Link>
        <div className="flex flex-col gap-3">
          <p className="text-muted">Role Reality Report</p>
          <h1 className="text-4xl font-bold leading-tight sm:text-5xl">{published.name}</h1>
          <p className="max-w-2xl leading-relaxed text-muted">
            {researched
              ? `Built from ${report.sample_size} ${place(report.country)} job postings that were open when we checked (first posted ${month(from)} to ${month(to)}), and from people who write about doing the work.`
              : `Built from ${report.sample_size} ${place(report.country)} job postings open in the last six months (posted ${month(from)} to ${month(to)}), and from people who write about doing the work.`}{" "}
            Every claim shows how much evidence backs it; open its sources to read the exact words.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {hasProject && (
            <Link href={`/roles/${slug}/practice`} className={button.primary}>
              Start your first week
            </Link>
          )}
          <a href="#compare" className={button.secondary}>
            Compare your background
          </a>
        </div>
      </header>

      <div className="grid gap-8 lg:grid-cols-[13rem_minmax(0,1fr)]">
        <nav aria-label="On this page" className="hidden lg:block">
          <ul className="sticky top-6 flex flex-col gap-1 text-sm">
            {SECTIONS.map(([id, label]) => (
              <li key={id}>
                <a href={`#${id}`} className="block rounded-md px-3 py-1.5 text-muted hover:bg-paper hover:text-ink">
                  {label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="flex min-w-0 flex-col gap-6">
          <Section id="short" title="In short">
            <Claims claims={report.summary} />
          </Section>

          <Section
            id="skills"
            title="What employers ask for"
            hint={`Share of the ${report.sample_size} postings that mention each skill, counted by code.`}
          >
            <AskedFor skills={report.asked_for} />
          </Section>

          <Section
            id="job"
            title="What the job involves"
            hint="What employers write in their job ads."
          >
            <Claims claims={report.responsibilities} />
          </Section>

          <Section
            id="day"
            title="What the work is like day to day"
            hint="From engineering blogs and practitioners' own writing: employers describe the job, these people describe doing it."
          >
            <Claims claims={practitioner} />
          </Section>

          <Section id="hard" title="The hard parts" hint="From engineering blogs and practitioners' own writing.">
            <Claims claims={report.pain_points} />
          </Section>

          <Section
            id="compare"
            title="How do you compare?"
            hint="Describe your background in a few sentences and see which of the skills above you already have."
          >
            <SkillGapForm slug={published.slug} />
          </Section>

          {hasProject && (
            <section className="flex flex-col items-start gap-4 rounded-xl bg-brand p-6 text-on-brand sm:p-8">
              <h2 className="text-2xl font-semibold">Ready to try it?</h2>
              <p className="max-w-xl opacity-90">
                Spend a week at a made-up company: read your inbox, talk to your team, fix real-looking
                code and get a review at the end.
              </p>
              <Link
                href={`/roles/${slug}/practice`}
                className="inline-flex items-center rounded-lg bg-paper px-4 py-2 text-sm font-medium text-ink hover:opacity-90"
              >
                Start your first week
              </Link>
            </section>
          )}

          <footer className="flex flex-col gap-2 pt-2 text-sm text-muted">
            <p>
              <span className="font-medium text-ink">Reading the labels.</span> Strong evidence
              means several independent, recent sources agree. Some evidence means one or two
              sources. Thin evidence is a lead to check, not a finding.
            </p>
            {report.provenance && researched && (
              <p>
                Statistics version {report.provenance.stats_version}. Researched and written by{" "}
                {report.provenance.writer_model}, with no model calls when you read it. The postings
                were matched to the role by hand, the skill shares counted from them by code, and
                every quote checked by {report.provenance.verifier_model}.
              </p>
            )}
            {report.provenance && !researched && (
              <p>
                Statistics version {report.provenance.stats_version}. Written by{" "}
                {report.provenance.writer_model}, checked claim by claim by{" "}
                {report.provenance.verifier_model}, then reviewed by a person.{" "}
                {report.provenance.removed.length} draft claims were removed on the way.
              </p>
            )}
          </footer>
        </div>
      </div>
    </div>
  );
}

export default function Page({ params }: { params: Promise<{ slug: string }> }) {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col px-4 py-10 sm:px-6 sm:py-14">
      <Suspense fallback={<p className="text-muted">Loading the report…</p>}>
        <Report params={params} />
      </Suspense>
    </main>
  );
}
