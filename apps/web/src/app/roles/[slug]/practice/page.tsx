import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { Workspace } from "@/components/workspace";
import { ApiUnreachable, getProject } from "@/lib/api";

export const metadata: Metadata = { title: "Practice project" };

async function Practice({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  let project;
  try {
    project = await getProject(slug);
  } catch (error) {
    if (error instanceof ApiUnreachable) {
      return <p className="text-red-700 dark:text-red-400">{error.message} Try again in a moment.</p>;
    }
    throw error;
  }
  if (!project) notFound();
  return (
    <>
      <Link href={`/roles/${slug}`} className="text-sm text-zinc-500 underline-offset-2 hover:underline">
        ← Back to the report
      </Link>
      <header className="flex flex-col gap-3">
        <p className="text-sm font-medium uppercase tracking-wide text-zinc-500">
          Practice project
        </p>
        <h1 className="text-4xl font-semibold tracking-tight">Your first week as a {project.blueprint.archetype}</h1>
        <p className="text-zinc-600 dark:text-zinc-400">
          A made-up company with a real-looking problem, built from what the report says this job
          is like. Edit the code, run the tests, and ask the Tech Lead for a review.
        </p>
      </header>
      <Workspace slug={slug} project={project} />
    </>
  );
}

export default function Page({ params }: { params: Promise<{ slug: string }> }) {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-10 px-6 py-14">
      <Suspense fallback={<p className="text-zinc-500">Loading the project…</p>}>
        <Practice params={params} />
      </Suspense>
    </main>
  );
}
