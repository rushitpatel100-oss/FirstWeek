import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { AskedFor } from "@/components/asked-for";
import { ClaimList } from "@/components/claim-list";
import { SkillGapForm } from "@/components/skill-gap-form";
import { ApiUnreachable, getProject, getReport } from "@/lib/api";
import { month } from "@/lib/format";
import type { Claim } from "@/lib/types";

export const metadata: Metadata = { title: "Role Reality Report" };

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-4">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
        {hint && <p className="mt-1 text-sm text-zinc-500">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

function Claims({ claims, empty }: { claims: Claim[]; empty: string }) {
  return claims.length > 0 ? (
    <ClaimList claims={claims} />
  ) : (
    <p className="text-sm text-zinc-500">{empty}</p>
  );
}

async function Report({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  let published;
  try {
    published = await getReport(slug);
  } catch (error) {
    if (error instanceof ApiUnreachable) {
      return <p className="text-red-700 dark:text-red-400">{error.message} Try again in a moment.</p>;
    }
    throw error;
  }
  if (!published) notFound();
  const hasProject = await getProject(slug).then((p) => p !== null, () => false);

  const { report } = published;
  const [from, to] = report.date_range;
  const practitioner = [...report.day_to_day, ...report.typical_week];
  const researched = report.provenance?.method === "researched";
  return (
    <article className="flex flex-col gap-12">
      <header className="flex flex-col gap-3">
        <p className="text-sm font-medium uppercase tracking-wide text-zinc-500">
          Role Reality Report
        </p>
        <h1 className="text-4xl font-semibold tracking-tight">{published.name}</h1>
        <p className="text-zinc-600 dark:text-zinc-400">
          {researched
            ? `Based on ${report.sample_size} ${report.country} job postings that were open when we checked (first posted ${month(from)} to ${month(to)}), plus practitioner writing.`
            : `Based on ${report.sample_size} ${report.country} job postings, all open in the last six months (posted ${month(from)} to ${month(to)}), plus practitioner writing.`}{" "}
          Every claim below shows how much evidence stands behind it and links to the exact words
          it rests on.
        </p>
      </header>

      <Section title="In short">
        <Claims claims={report.summary} empty="No summary yet." />
      </Section>

      <Section
        title="What employers ask for"
        hint="Counted from the postings by code, not written by a model."
      >
        <AskedFor skills={report.asked_for} />
      </Section>

      <Section
        title="How do you compare?"
        hint="Optional. Tell us about your background and we compare it with the skills above."
      >
        <SkillGapForm slug={published.slug} />
      </Section>

      <Section title="What employers say the job involves" hint="From job postings.">
        <Claims claims={report.responsibilities} empty="Nothing here passed our checks yet." />
      </Section>

      <Section
        title="What the work is like day to day"
        hint="From blogs and practitioners' own writing. Employers describe the job; these people describe doing it."
      >
        <Claims claims={practitioner} empty="Nothing here passed our checks yet." />
      </Section>

      <Section title="The hard parts" hint="From blogs and practitioners' own writing.">
        <Claims claims={report.pain_points} empty="Nothing here passed our checks yet." />
      </Section>

      {hasProject && (
        <Section
          title="Try the job"
          hint="A practice project built from this report: tickets, starter code, tests and a Tech Lead who reviews your work."
        >
          <Link
            href={`/roles/${slug}/practice`}
            className="w-fit rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
          >
            Start the practice project
          </Link>
        </Section>
      )}

      <footer className="flex flex-col gap-2 border-t border-zinc-200 pt-6 text-sm text-zinc-500 dark:border-zinc-800">
        <p>
          <span className="font-medium">How to read the badges.</span> High means several
          independent, recent sources agree. Low means one source or an old one: a lead to
          check, not a finding.
        </p>
        {report.provenance && researched && (
          <p>
            Statistics version {report.provenance.stats_version}. Researched and written by{" "}
            {report.provenance.writer_model}, with no model calls at run time. The postings were
            matched to the role by hand, the skill shares counted from them by code, and every
            quote checked by {report.provenance.verifier_model}.
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
    </article>
  );
}

export default function Page({ params }: { params: Promise<{ slug: string }> }) {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-10 px-6 py-14">
      <Link href="/" className="text-sm text-zinc-500 underline-offset-2 hover:underline">
        ← All roles
      </Link>
      <Suspense fallback={<p className="text-zinc-500">Loading the report…</p>}>
        <Report params={params} />
      </Suspense>
    </main>
  );
}
