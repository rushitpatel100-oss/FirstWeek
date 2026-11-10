"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore, useTransition } from "react";
import { finishWeek, sendMessage, type WeekState } from "@/app/roles/[slug]/practice/actions";
import { Workspace } from "@/components/workspace";
import type { Internship, InternshipEvent, Project, Turn } from "@/lib/types";
import { button, initials, panel } from "./ui";

const LAST_DAY = 5;
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"] as const;
const KINDS = { message: "Message", ticket: "New ticket", meeting: "Meeting" } as const;

/** `reached` is the furthest day of the week; `day` is the one on screen (earlier days can be
 * looked back at). Weeks saved before `reached` existed load with reached = day. */
type Saved = { day: number; reached?: number; chats: Record<string, Turn[]>; guideClosed?: boolean };

const clampDay = (d: number) => Math.min(Math.max(Math.trunc(d) || 1, 1), LAST_DAY);
const weekday = (d: number) => WEEKDAYS[clampDay(d) - 1];

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

function Avatar({ name, size = "md" }: { name: string; size?: "sm" | "md" }) {
  return (
    <span
      aria-hidden
      className={`grid shrink-0 place-items-center rounded-full bg-brand-soft font-medium text-ink ${
        size === "sm" ? "h-7 w-7 text-[11px]" : "h-9 w-9 text-xs"
      }`}
    >
      {initials(name)}
    </span>
  );
}

function WeekReviewCard({ state }: { state: WeekState }) {
  if (state.status === "idle") return null;
  if (state.status === "error") {
    return (
      <p role="alert" className="rounded-lg border border-danger/40 p-4 text-sm text-danger">
        {state.message}
      </p>
    );
  }
  const { verdict, model, tests } = state.review;
  return (
    <section aria-live="polite" className="flex flex-col gap-6">
      <p className="max-w-3xl text-lg leading-relaxed">{verdict.summary}</p>
      <ul className="grid gap-3 sm:grid-cols-2">
        {verdict.skills.map((s) => (
          <li key={s.skill_id} className="flex flex-col gap-2 rounded-lg bg-page p-4">
            <div className="flex items-center justify-between gap-3">
              <p className="font-medium capitalize">{s.skill_id.replaceAll("-", " ")}</p>
              <p className="flex items-center gap-1" aria-label={`${s.score} out of 5`}>
                {Array.from({ length: 5 }, (_, i) => (
                  <span key={i} className={`h-2 w-5 rounded-sm ${i < s.score ? "bg-brand" : "bg-line"}`} />
                ))}
              </p>
            </div>
            <p className="text-sm leading-relaxed text-muted">{s.evidence}</p>
          </li>
        ))}
      </ul>
      <div className="grid gap-6 sm:grid-cols-2">
        <div>
          <h3 className="mb-2 text-lg font-semibold">Went well</h3>
          <ul className="flex list-disc flex-col gap-1 pl-5 text-muted">
            {verdict.went_well.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="mb-2 text-lg font-semibold">To work on</h3>
          <ul className="flex list-disc flex-col gap-1 pl-5 text-muted">
            {verdict.to_work_on.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
      </div>
      <p className="rounded-lg bg-brand-soft p-4">
        <span className="font-medium">Your next step: </span>
        {verdict.next_step}
      </p>
      <p className="text-xs text-muted">
        Final tests: {tests.passed ? "passed" : "failing"}. Written by {model} from your code, your
        tests and what you wrote in chat. Evidence about this week&apos;s work, not a verdict on you.
      </p>
    </section>
  );
}

const noSubscribe = () => () => {};

/** Waits for the browser so the saved week can be read without a server/client mismatch. */
export function InternshipView(props: { slug: string; project: Project; internship: Internship }) {
  const ready = useSyncExternalStore(noSubscribe, () => true, () => false);
  if (!ready) return <p className="text-muted">Opening your week…</p>;
  return <Week {...props} />;
}

function Inbox({
  events,
  day,
  people,
}: {
  events: InternshipEvent[];
  day: number;
  people: Record<string, { name: string; role: string }>;
}) {
  const today = events.filter((e) => e.day === day);
  const earlier = events.filter((e) => e.day < day).reverse();
  const item = (e: InternshipEvent, i: number, fresh: boolean) => {
    const from = people[e.sender];
    return (
      <li key={`${e.day}-${e.sender}-${i}`} className="flex gap-3 py-4 first:pt-0 last:pb-0">
        <Avatar name={from?.name ?? "?"} size="sm" />
        <div className="flex min-w-0 flex-col gap-1">
          <p className="text-sm">
            <span className="font-medium">{from?.name}</span>{" "}
            <span className="text-muted">{from?.role}</span>
          </p>
          <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
            <span className={`rounded px-1.5 py-0.5 ${fresh ? "bg-brand-soft text-ink" : "bg-page"}`}>
              {KINDS[e.kind]}
            </span>
            {!fresh && weekday(e.day)}
          </p>
          <p className="leading-relaxed">{e.text}</p>
        </div>
      </li>
    );
  };
  return (
    <section className={`${panel} flex flex-col gap-4 p-5`} aria-label="Inbox">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-xl font-semibold">Inbox</h2>
        <span className="text-sm text-muted">
          {today.length} new on {weekday(day)}
        </span>
      </div>
      {today.length > 0 ? (
        <ul className="flex flex-col divide-y divide-line">{today.map((e, i) => item(e, i, true))}</ul>
      ) : (
        <p className="text-sm text-muted">Nothing new today. Carry on with your tickets.</p>
      )}
      {earlier.length > 0 && (
        <details className="group border-t border-line pt-3">
          <summary className="cursor-pointer list-none text-sm text-muted hover:text-ink">
            <span className="group-open:hidden">Earlier this week ({earlier.length})</span>
            <span className="hidden group-open:inline">Hide earlier messages</span>
          </summary>
          <ul className="mt-4 flex flex-col divide-y divide-line">{earlier.map((e, i) => item(e, i, false))}</ul>
        </details>
      )}
    </section>
  );
}

function Week({ slug, project, internship }: { slug: string; project: Project; internship: Internship }) {
  const storeKey = `firstweek:${slug}:internship`;
  const [saved] = useState(() => load(storeKey));
  const [reached, setReached] = useState(() =>
    saved ? clampDay(Math.max(saved.reached ?? saved.day, saved.day)) : 1,
  );
  const [day, setDay] = useState(() => (saved ? Math.min(clampDay(saved.day), reached) : 1));
  const [chats, setChats] = useState<Record<string, Turn[]>>(() => saved?.chats ?? {});
  const [guideClosed, setGuideClosed] = useState(() => saved?.guideClosed ?? false);
  const [round, setRound] = useState(0);
  const [confirmRestart, setConfirmRestart] = useState(false);
  const [who, setWho] = useState(internship.colleagues[0].key);
  const [draft, setDraft] = useState("");
  const [chatError, setChatError] = useState("");
  const [week, setWeek] = useState<WeekState>({ status: "idle" });
  const [pending, start] = useTransition();
  const [ending, setEnding] = useState(false);
  const filesRef = useRef<Record<string, string>>({});
  const thread = useRef<HTMLDivElement>(null);

  useEffect(() => {
    save(storeKey, { day, reached, chats, guideClosed });
  }, [storeKey, day, reached, chats, guideClosed]);
  useEffect(() => {
    const el = thread.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chats, who, pending]);

  const onFiles = useCallback((f: Record<string, string>) => {
    filesRef.current = f;
  }, []);

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
      setChats((c) => ({ ...c, [who]: [...(c[who] ?? []), { who: "them", text: result.reply }] }));
    });
  }

  function nextDay() {
    const next = clampDay(reached + 1);
    setReached(next);
    setDay(next);
    window.scrollTo?.({ top: 0, behavior: "smooth" });
  }

  function restart() {
    setDay(1);
    setReached(1);
    setChats({});
    setDraft("");
    setChatError("");
    setWeek({ status: "idle" });
    setWho(internship.colleagues[0].key);
    setGuideClosed(false);
    filesRef.current = {};
    setRound((r) => r + 1); // a fresh workspace: the starter code again
    setConfirmRestart(false);
  }

  function end() {
    const sent = Object.values(chats).flatMap((turns) =>
      turns.filter((t) => t.who === "you").map((t) => t.text),
    );
    setEnding(true);
    start(async () => {
      setWeek(await finishWeek(slug, filesRef.current, sent));
      setEnding(false);
    });
  }

  return (
    <div className="flex flex-col gap-6">
      <section className={`${panel} flex flex-col gap-4 p-4 sm:p-5`} aria-label="Your week">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <ol className="grid grid-cols-5 gap-1.5 sm:gap-2 lg:min-w-[36rem]" aria-label="Days of the week">
            {WEEKDAYS.map((name, i) => {
              const d = i + 1;
              const current = d === day;
              const done = d < reached;
              const locked = d > reached;
              return (
                <li key={name}>
                  <button
                    type="button"
                    onClick={() => setDay(d)}
                    disabled={locked}
                    aria-current={current ? "step" : undefined}
                    title={locked ? "Finish the days before it first" : `Show ${name}`}
                    className={`flex w-full flex-col items-start rounded-lg border px-2.5 py-2 text-left sm:px-3 ${
                      current
                        ? "border-brand bg-brand text-on-brand"
                        : locked
                          ? "cursor-not-allowed border-dashed border-line text-muted"
                          : "border-line hover:border-muted"
                    }`}
                  >
                    <span className="font-display text-sm font-semibold sm:hidden">{name.slice(0, 3)}</span>
                    <span className="hidden font-display text-base font-semibold sm:inline">{name}</span>
                    <span className={`text-xs ${current ? "opacity-85" : "text-muted"}`}>
                      {done ? "Done" : d === reached ? "Today" : `Day ${d}`}
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
          <div className="flex flex-wrap items-center gap-2">
            {day === reached && reached < LAST_DAY && (
              <button type="button" onClick={nextDay} className={button.primary}>
                Finish {weekday(day)}
              </button>
            )}
            {reached === LAST_DAY && day === reached && (
              <a href="#end-of-week" className={button.primary}>
                Finish the week
              </a>
            )}
            {(reached > 1 || Object.keys(chats).length > 0) && !confirmRestart && (
              <button type="button" onClick={() => setConfirmRestart(true)} className={button.quiet}>
                Start the week again
              </button>
            )}
          </div>
        </div>
        {confirmRestart && (
          <div role="alertdialog" aria-label="Start the week again?" className="flex flex-wrap items-center gap-3 rounded-lg bg-page p-3 text-sm">
            <span className="flex-1">This clears your chats and code and takes you back to Monday.</span>
            <button type="button" onClick={restart} className={button.primary}>
              Start again
            </button>
            <button type="button" onClick={() => setConfirmRestart(false)} className={button.secondary}>
              Keep my week
            </button>
          </div>
        )}
        {day < reached && (
          <p className="rounded-lg bg-page p-3 text-sm">
            You are looking back at {weekday(day)}. Your week is on {weekday(reached)}.{" "}
            <button type="button" onClick={() => setDay(reached)} className="font-medium underline underline-offset-2">
              Back to {weekday(reached)}
            </button>
          </p>
        )}
      </section>

      {!guideClosed && reached === 1 && (
        <section className="flex flex-col gap-4 rounded-xl bg-brand-soft p-5" aria-label="How your week works">
          <div className="flex items-start justify-between gap-4">
            <h2 className="text-xl font-semibold">How your week works</h2>
            <button type="button" onClick={() => setGuideClosed(true)} className={`${button.quiet} -mr-2 -mt-1`}>
              Got it
            </button>
          </div>
          <ol className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            {[
              ["Read your inbox", "Your manager explains what matters this week."],
              ["Talk to your team", "Ask the colleagues on the left anything you would ask at work."],
              ["Do the ticket", "Change the code, run the tests and ask for a review."],
              ["Finish the day", "Each day brings new messages. On Friday, your week is reviewed."],
            ].map(([title, text], i) => (
              <li key={title} className="flex gap-3">
                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand text-xs font-semibold text-on-brand">
                  {i + 1}
                </span>
                <span>
                  <span className="block font-medium">{title}</span>
                  <span className="text-muted">{text}</span>
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-6 lg:sticky lg:top-4">
          <Inbox events={events} day={day} people={people} />

          <section className={`${panel} flex flex-col`} aria-label="Team chat">
            <div className="flex flex-col gap-3 border-b border-line p-5 pb-4">
              <h2 className="text-xl font-semibold">Your team</h2>
              <div className="flex flex-col gap-1" role="tablist" aria-label="Colleagues">
                {internship.colleagues.map((c) => (
                  <button
                    key={c.key}
                    role="tab"
                    aria-selected={c.key === who}
                    onClick={() => setWho(c.key)}
                    className={`flex items-center gap-3 rounded-lg px-2 py-1.5 text-left ${
                      c.key === who ? "bg-page" : "hover:bg-page"
                    }`}
                  >
                    <Avatar name={c.name} />
                    <span className="flex min-w-0 flex-col">
                      <span className="text-sm font-medium">{c.name}</span>
                      <span className="truncate text-xs text-muted">{c.role}</span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
            <div ref={thread} aria-live="polite" className="flex h-72 flex-col gap-2 overflow-y-auto p-4">
              {talk.length === 0 && (
                <p className="m-auto max-w-[16rem] text-center text-sm text-muted">
                  Say hello to {person.name}. Ask what you need to know, as you would at work.
                </p>
              )}
              {talk.map((t, i) => (
                <p
                  key={i}
                  className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
                    t.who === "you" ? "self-end rounded-br-md bg-brand text-on-brand" : "self-start rounded-bl-md bg-page"
                  }`}
                >
                  {t.text}
                </p>
              ))}
              {pending && !ending && talk.at(-1)?.who === "you" && (
                <p className="self-start text-xs text-muted">{person.name} is typing…</p>
              )}
            </div>
            {chatError && (
              <p role="alert" className="px-4 pb-2 text-sm text-danger">
                {chatError}
              </p>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                send();
              }}
              className="flex gap-2 border-t border-line p-3"
            >
              <input
                aria-label={`Message ${person.name}`}
                value={draft}
                maxLength={1500}
                onChange={(e) => setDraft(e.target.value)}
                placeholder={`Message ${person.name}`}
                className="min-w-0 flex-1 rounded-lg border border-line bg-page px-3 py-2 text-sm placeholder:text-muted"
              />
              <button type="submit" disabled={pending || !draft.trim()} className={button.primary}>
                Send
              </button>
            </form>
            <p className="px-4 pb-4 text-xs text-muted">
              Your colleagues are AI characters. They only know this project, and say so when they
              are not sure.
            </p>
          </section>
        </div>

        <Workspace key={round} slug={slug} project={visible} onFiles={onFiles} briefOpen={reached === 1} />
      </div>

      {reached === LAST_DAY && (
        <section id="end-of-week" className={`${panel} flex scroll-mt-6 flex-col gap-5 p-5 sm:p-7`}>
          <div className="flex flex-col gap-2">
            <h2 className="text-2xl font-semibold">End of the week</h2>
            <p className="max-w-2xl text-muted">
              Your supervisor reads your code, runs your tests and looks at what you wrote in chat,
              then tells you how the week went.
            </p>
          </div>
          {week.status !== "done" && (
            <div>
              <button disabled={pending} onClick={end} className={button.primary}>
                {ending ? "Your supervisor is reviewing…" : "Finish the week and get my review"}
              </button>
            </div>
          )}
          <WeekReviewCard state={week} />
        </section>
      )}
    </div>
  );
}
