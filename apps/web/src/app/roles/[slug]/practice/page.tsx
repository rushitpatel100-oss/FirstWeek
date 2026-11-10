import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { InternshipView } from "@/components/internship";
import { article, panel } from "@/components/ui";
import { Workspace } from "@/components/workspace";
import { ApiUnreachable, getInternship, getProject } from "@/lib/api";

export const metadata: Metadata = { title: "Your first week" };

async function Practice({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  let project;
  let internship;
  try {
    project = await getProject(slug);
    internship = project ? await getInternship(slug) : null;
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
  if (!project) notFound();
  const role = project.blueprint.archetype;
  return (
    <>
      <header className="flex flex-col gap-3">
        <Link href={`/roles/${slug}`} className="w-fit text-sm text-muted hover:text-ink">
          Back to the {role} report
        </Link>
        <h1 className="text-3xl font-bold leading-tight sm:text-4xl">
          Your first week as {article(role)} {role}
        </h1>
        <p className="max-w-3xl leading-relaxed text-muted">
          {internship
            ? "A made-up company with a real-looking problem, and a team to work with. Everything you do here stays in this browser."
            : "A made-up company with a real-looking problem, built from what the report says this job is like. Change the code, run the tests and ask the Tech Lead for a review."}
        </p>
      </header>
      {internship ? (
        <InternshipView slug={slug} project={project} internship={internship} />
      ) : (
        <Workspace slug={slug} project={project} />
      )}
    </>
  );
}

export default function Page({ params }: { params: Promise<{ slug: string }> }) {
  return (
    <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-6 px-4 py-8 sm:px-6 sm:py-10">
      <Suspense fallback={<p className="text-muted">Loading your week…</p>}>
        <Practice params={params} />
      </Suspense>
    </main>
  );
}
