"use client";

import { useEffect, useRef, useState, useSyncExternalStore, useTransition } from "react";
import {
  finishWeek,
  sendMessage,
  type WeekState,
} from "@/app/roles/[slug]/practice/actions";
import { Workspace } from "@/components/workspace";
import type { Internship, Project, Turn } from "@/lib/types";

const LAST_DAY = 5;
const KINDS = { message: "Message", ticket: "New ticket", meeting: "Meeting" } as const;

/** `reached` is the furthest day of the week; `day` is the one on screen (earlier days can be
 * looked back at). Weeks saved before `reached` existed load with reached = day. */
type Saved = { day: number; reached?: number; chats: Record<string, Turn[]> };

const clampDay = (d: number) => Math.min(Math.max(Math.trunc(d) || 1, 1), LAST_DAY);

function load(key: string): Saved | null {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as Saved) : null;
  } catch {
    return null;
  }
}

function save(key: string, value: Saved) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Private windows and blocked storage: the week still works, it just is not kept.
  }
}

function WeekReviewCard({ state }: { state: WeekState }) {
  if (state.status === "idle") return null;
  if (state.status === "error") {
    return (
      <p role="alert" className="text-sm text-red-700 dark:text-red-400">
        {state.message}
      </p>
    );
  }
  const { verdict, model, tests } = state.review;
  return (
    <section
      aria-live="polite"
      className="flex flex-col gap-4 rounded-lg border border-zinc-300 p-5 dark:border-zinc-700"
    >
      <h3 className="text-sm font-medium uppercase tracking-wide text-zinc-500">
        How your week went
      </h3>
      <p className="leading-relaxed">{verdict.summary}</p>
      <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-3 text-sm">
        {verdict.skills.map((s) => (
          <div key={s.skill_id} className="contents">
            <div>
              <p className="font-medium">{s.skill_id.replaceAll("-", " ")}</p>
              <p className="text-zinc-600 dark:text-zinc-400">{s.evidence}</p>
            </div>
            <p className="font-medium">{s.score}/5</p>
          </div>
        ))}
      </div>
      <div className="grid gap-4 text-sm sm:grid-cols-2">
        <div>
          <p className="font-medium">Went well</p>
          <ul className="list-disc pl-5 text-zinc-600 dark:text-zinc-400">
            {verdict.went_well.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
        <div>
          <p className="font-medium">To work on</p>
          <ul className="list-disc pl-5 text-zinc-600 dark:text-zinc-400">
            {verdict.to_work_on.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
      </div>
      <p className="text-sm">
        <span className="font-medium">Next step: </span>
        {verdict.next_step}
      </p>
      <p className="text-xs text-zinc-500">
        Final tests: {tests.passed ? "passed" : "failing"}. Written by {model} from your code, your
        tests and what you wrote in chat. Evidence about this week&apos;s work, not a verdict on
        you.
      </p>
    </section>
  );
}

const noSubscribe = () => () => {};

/** Waits for the browser so the saved week can be read without a server/client mismatch. */
export function InternshipView(props: {
  slug: string;
  project: Project;
  internship: Internship;
}) {
  const ready = useSyncExternalStore(noSubscribe, () => true, () => false);
  if (!ready) return <p className="text-zinc-500">Opening your week…</p>;
  return <Week {...props} />;
}

function Week({
  slug,
  project,
  internship,
}: {
  slug: string;
  project: Project;
  internship: Internship;
}) {
  const storeKey = `firstweek:${slug}:internship`;
  const [saved] = useState(() => load(storeKey));
  const [reached, setReached] = useState(() =>
    saved ? clampDay(Math.max(saved.reached ?? saved.day, saved.day)) : 1,
  );
  const [day, setDay] = useState(() => (saved ? Math.min(clampDay(saved.day), reached) : 1));
  const [chats, setChats] = useState<Record<string, Turn[]>>(() => saved?.chats ?? {});
  const [round, setRound] = useState(0);
  const [confirmRestart, setConfirmRestart] = useState(false);
  const [who, setWho] = useState(internship.colleagues[0].key);
  const [draft, setDraft] = useState("");
  const [chatError, setChatError] = useState("");
  const [week, setWeek] = useState<WeekState>({ status: "idle" });
  const [pending, start] = useTransition();
  const filesRef = useRef<Record<string, string>>({});
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    save(storeKey, { day, reached, chats });
  }, [storeKey, day, reached, chats]);
  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: "nearest" });
  }, [chats, who]);

  const people = Object.fromEntries(internship.colleagues.map((c) => [c.key, c]));
  const events = internship.events.filter((e) => e.day <= day);
  // Work assigned so far stays in the workspace while you look back at an earlier day.
  const assigned = new Set(
    internship.events.filter((e) => e.day <= reached).flatMap((e) => (e.ticket ? [e.ticket] : [])),
  );
  const visible: Project = {
    ...project,
    blueprint: {
      ...project.blueprint,
      tickets: project.blueprint.tickets.filter((t) => assigned.has(t.key)),
    },
  };
  const talk = chats[who] ?? [];
  const person = people[who];

  function send() {
    const message = draft.trim();
    if (!message || pending) return;
    const history = talk;
    setDraft("");
    setChatError("");
    setChats((c) => ({ ...c, [who]: [...history, { who: "you", text: message }] }));
    start(async () => {
      const result = await sendMessage(slug, who, reached, message, history);
      if (result.status === "error") {
        setChatError(result.message);
        return;
      }
      setChats((c) => ({
        ...c,
        [who]: [...(c[who] ?? []), { who: "them", text: result.reply }],
      }));
    });
  }

  function nextDay() {
    const next = clampDay(reached + 1);
    setReached(next);
    setDay(next);
  }

  function restart() {
    setDay(1);
    setReached(1);
    setChats({});
    setDraft("");
    setChatError("");
    setWeek({ status: "idle" });
    setWho(internship.colleagues[0].key);
    filesRef.current = {};
    setRound((r) => r + 1); // a fresh workspace: the starter code again
    setConfirmRestart(false);
  }

  function end() {
    const sent = Object.values(chats).flatMap((turns) =>
      turns.filter((t) => t.who === "you").map((t) => t.text),
    );
    start(async () => setWeek(await finishWeek(slug, filesRef.current, sent)));
  }

  return (
    <div className="flex flex-col gap-12">
      <section className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <ol className="flex gap-2" aria-label="Days of the week">
            {Array.from({ length: LAST_DAY }, (_, i) => i + 1).map((d) => (
              <li key={d}>
                <button
                  type="button"
                  onClick={() => setDay(d)}
                  disabled={d > reached}
                  aria-current={d === day ? "step" : undefined}
                  title={d > reached ? "Finish the days before it first" : `Show day ${d}`}
                  className={`rounded-full border px-3 py-1 text-sm ${
                    d === day
                      ? "border-zinc-900 bg-zinc-900 text-white dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900"
                      : d <= reached
                        ? "border-zinc-300 text-zinc-600 hover:border-zinc-500 dark:border-zinc-700 dark:text-zinc-400"
                        : "cursor-not-allowed border-dashed border-zinc-300 text-zinc-400 dark:border-zinc-700"
                  }`}
                >
                  Day {d}
                </button>
              </li>
            ))}
          </ol>
          <div className="flex flex-wrap items-center gap-2">
            {day === reached && reached < LAST_DAY && (
              <button
                type="button"
                onClick={nextDay}
                className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium dark:border-zinc-700"
              >
                Finish day {day}, start day {day + 1}
              </button>
            )}
            {reached > 1 &&
              (confirmRestart ? (
                <span className="flex items-center gap-2 text-sm">
                  Clear your chats and code and go back to day 1?
                  <button
                    type="button"
                    onClick={restart}
                    className="rounded-lg bg-zinc-900 px-3 py-1.5 font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
                  >
                    Start again
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmRestart(false)}
                    className="rounded-lg border border-zinc-300 px-3 py-1.5 dark:border-zinc-700"
                  >
                    Keep my week
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmRestart(true)}
                  className="rounded-lg px-3 py-2 text-sm text-zinc-600 underline-offset-2 hover:underline dark:text-zinc-400"
                >
                  Start the week again
                </button>
              ))}
          </div>
        </div>
        {day < reached && (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Looking back at day {day}. Your week is on day {reached}.{" "}
            <button
              type="button"
              onClick={() => setDay(reached)}
              className="font-medium underline underline-offset-2"
            >
              Back to day {reached}
            </button>
          </p>
        )}
        <h2 className="text-xl font-semibold tracking-tight">Your inbox</h2>
        <ul className="flex flex-col gap-3">
          {[...events].reverse().map((e, i) => (
            <li
              key={`${e.day}-${e.sender}-${i}`}
              className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
            >
              <p className="text-xs text-zinc-500">
                Day {e.day} · {KINDS[e.kind]} · {people[e.sender]?.name} ({people[e.sender]?.role})
              </p>
              <p className="mt-1 text-sm leading-relaxed">{e.text}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-xl font-semibold tracking-tight">Team chat</h2>
        <div className="flex flex-wrap gap-2" role="tablist">
          {internship.colleagues.map((c) => (
            <button
              key={c.key}
              role="tab"
              aria-selected={c.key === who}
              onClick={() => setWho(c.key)}
              className={`rounded-full border px-3 py-1 text-sm ${
                c.key === who
                  ? "border-zinc-900 dark:border-zinc-100"
                  : "border-zinc-300 text-zinc-600 dark:border-zinc-700 dark:text-zinc-400"
              }`}
            >
              {c.name}
              <span className="text-zinc-500"> · {c.role}</span>
            </button>
          ))}
        </div>
        <div
          aria-live="polite"
          className="flex max-h-80 min-h-32 flex-col gap-2 overflow-auto rounded-lg border border-zinc-200 p-3 dark:border-zinc-800"
        >
          {talk.length === 0 && (
            <p className="text-sm text-zinc-500">
              Say hello to {person.name}. Ask what you need to know, as you would at work.
            </p>
          )}
          {talk.map((t, i) => (
            <p
              key={i}
              className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                t.who === "you"
                  ? "self-end bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                  : "self-start bg-zinc-100 dark:bg-zinc-900"
              }`}
            >
              {t.text}
            </p>
          ))}
          {pending && <p className="text-xs text-zinc-500">{person.name} is typing…</p>}
          <div ref={bottom} />
        </div>
        {chatError && (
          <p role="alert" className="text-sm text-red-700 dark:text-red-400">
            {chatError}
          </p>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
          className="flex gap-2"
        >
          <input
            aria-label={`Message ${person.name}`}
            value={draft}
            maxLength={1500}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={`Message ${person.name}`}
            className="min-w-0 flex-1 rounded-lg border border-zinc-300 bg-transparent px-3 py-2 text-sm dark:border-zinc-700"
          />
          <button
            type="submit"
            disabled={pending || !draft.trim()}
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900"
          >
            Send
          </button>
        </form>
        <p className="text-xs text-zinc-500">
          Your colleagues are AI characters. They only know what is in this project and may say so
          when they are not sure.
        </p>
      </section>

      <Workspace key={round} slug={slug} project={visible} onFiles={(f) => {
          filesRef.current = f;
        }} />

      {reached === LAST_DAY && (
        <section className="flex flex-col gap-3 border-t border-zinc-200 pt-8 dark:border-zinc-800">
          <h2 className="text-xl font-semibold tracking-tight">End of the week</h2>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            When you are done, your supervisor reads your code, runs your tests and looks at what
            you wrote in chat, then reviews your week.
          </p>
          <div>
            <button
              disabled={pending}
              onClick={end}
              className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900"
            >
              {pending ? "Working…" : "Finish the week"}
            </button>
          </div>
          <WeekReviewCard state={week} />
        </section>
      )}
    </div>
  );
}
