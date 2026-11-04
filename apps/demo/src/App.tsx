import { useEffect, useMemo, useRef, useState } from "react";
import data from "./data.json";
import { runTests } from "./python";
import { reply, techLeadReview, verdict as makeVerdict, type Verdict } from "./recorded";

type Chat = { from: "me" | string; text: string };
type Saved = {
  day: number;
  chats: Record<string, Chat[]>;
  edits: Record<string, string>;
  lastRun: { passed: boolean } | null;
};

const KEY = "firstweek-demo-v1";
const files = data.files as Record<string, string>;
const colleagues = data.internship.colleagues;
const events = data.internship.events as {
  day: number; kind: string; sender: string; text: string; ticket: string | null;
}[];
const tickets = data.blueprint.tickets;
const nameOf = (k: string) => colleagues.find((c) => c.key === k)?.name ?? k;
const LOCKED = (p: string) => p.startsWith("tests/test_metrics") || p.startsWith("key/");

function load(): Saved {
  const empty: Saved = { day: 1, chats: {}, edits: {}, lastRun: null };
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...empty, ...JSON.parse(raw) } : empty;
  } catch {
    return empty;
  }
}

export function App() {
  const [s, setS] = useState<Saved>(load);
  const [who, setWho] = useState(colleagues[0].key);
  const [draft, setDraft] = useState("");
  const [open, setOpen] = useState("src/metrics.py");
  const [running, setRunning] = useState(false);
  const [output, setOutput] = useState("");
  const [review, setReview] = useState("");
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [tab, setTab] = useState<"inbox" | "chat" | "code">("inbox");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* storage may be blocked */ }
  }, [s]);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "nearest" }); }, [s.chats, who, tab]);

  const current = useMemo(() => ({ ...files, ...s.edits }), [s.edits]);
  const paths = Object.keys(files).filter((p) => p.endsWith(".py") || p.endsWith(".md")).sort();
  const visible = events.filter((e) => e.day <= s.day);
  const chat = s.chats[who] ?? [];
  const hasNewTest = Object.keys(s.edits).some((p) => p.startsWith("tests/") && p !== "tests/test_metrics.py" && s.edits[p].trim());

  function send() {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    setS((p) => {
      const mine = p.chats[who] ?? [];
      const n = mine.filter((m) => m.from === "me").length;
      return { ...p, chats: { ...p.chats, [who]: [...mine, { from: "me", text }, { from: who, text: reply(who, n) }] } };
    });
  }

  async function run() {
    setRunning(true);
    setOutput("Starting Python in your browser. The first run downloads it (a few seconds)…");
    const changed: Record<string, string> = {};
    for (const p of Object.keys(current)) changed[p] = current[p];
    const r = await runTests(changed);
    setOutput(r.output);
    setS((p) => ({ ...p, lastRun: { passed: r.passed } }));
    setRunning(false);
  }

  function edit(text: string) {
    if (LOCKED(open)) return;
    setS((p) => ({ ...p, edits: { ...p.edits, [open]: text } }));
  }

  function newTest() {
    const p = "tests/test_regression.py";
    setS((x) => ({ ...x, edits: { ...x.edits, [p]: x.edits[p] ?? "from src.metrics import *\n\n\ndef test_regression():\n    ...\n" } }));
    setOpen(p);
    setTab("code");
  }

  const passed = s.lastRun?.passed ?? false;
  const msgs = Object.values(s.chats).reduce((n, c) => n + c.filter((m) => m.from === "me").length, 0);
  const allPaths = [...new Set([...paths, ...Object.keys(s.edits)])].sort();

  return (
    <div className="app">
      <header>
        <h1>FirstWeek <span>virtual internship · demo</span></h1>
        <p className="banner">
          Static demo: colleague replies, the Tech Lead review and the supervisor's verdict are{" "}
          <b>recorded samples</b>. The code runs for real (pytest in your browser). The full app
          answers with a live model.
        </p>
      </header>

      <section className="intro">
        <h2>{data.blueprint.archetype} at Northwind Claims</h2>
        <p>{data.blueprint.scenario}</p>
      </section>

      <nav className="days">
        {[1, 2, 3, 4, 5].map((d) => (
          <button key={d} className={d === s.day ? "on" : ""} disabled={d > s.day + 1} onClick={() => setS({ ...s, day: Math.max(s.day, d) })} >
            Day {d}
          </button>
        ))}
        <button className="ghost" onClick={() => { try { localStorage.removeItem(KEY); } catch { /* ignore */ } setS({ day: 1, chats: {}, edits: {}, lastRun: null }); setOutput(""); setReview(""); setVerdict(null); }}>Start over</button>
      </nav>

      <nav className="tabs">
        {(["inbox", "chat", "code"] as const).map((t) => (
          <button key={t} className={t === tab ? "on" : ""} onClick={() => setTab(t)}>{t === "inbox" ? "Inbox" : t === "chat" ? "Team chat" : "Code"}</button>
        ))}
      </nav>

      {tab === "inbox" && (
        <section>
          {visible.map((e, i) => {
            const t = tickets.find((x) => x.key === e.ticket);
            return (
              <article key={i} className={`card ${e.kind}`}>
                <div className="meta">Day {e.day} · {e.kind} · {nameOf(e.sender)}</div>
                {t ? (
                  <>
                    <h3>{t.key}: {t.title}</h3>
                    <p>{t.description}</p>
                    <ul>{t.acceptance_criteria.map((a) => <li key={a}>{a}</li>)}</ul>
                  </>
                ) : <p>{e.text}</p>}
              </article>
            );
          })}
          {s.day < 5 && <button className="primary" onClick={() => setS({ ...s, day: s.day + 1 })}>End of day {s.day}: go to day {s.day + 1}</button>}
        </section>
      )}

      {tab === "chat" && (
        <section className="chat">
          <div className="who">{colleagues.map((c) => (
            <button key={c.key} className={c.key === who ? "on" : ""} onClick={() => setWho(c.key)}>{c.name}<small>{c.role}</small></button>
          ))}</div>
          <div className="log">
            {chat.length === 0 && <p className="hint">Say hello to {nameOf(who)}. Try: "What should I look at first?"</p>}
            {chat.map((m, i) => <p key={i} className={m.from === "me" ? "me" : "them"}>{m.text}{m.from !== "me" && <em> · recorded sample</em>}</p>)}
            <div ref={endRef} />
          </div>
          <form onSubmit={(e) => { e.preventDefault(); send(); }}>
            <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={`Message ${nameOf(who)}`} maxLength={1500} />
            <button className="primary">Send</button>
          </form>
        </section>
      )}

      {tab === "code" && (
        <section className="code">
          <div className="files">
            {allPaths.map((p) => <button key={p} className={p === open ? "on" : ""} onClick={() => setOpen(p)}>{p}{LOCKED(p) ? " 🔒" : ""}</button>)}
            <button className="ghost" onClick={newTest}>+ new test</button>
          </div>
          <textarea spellCheck={false} value={current[open] ?? ""} readOnly={LOCKED(open)} onChange={(e) => edit(e.target.value)} />
          <div className="actions">
            <button className="primary" disabled={running} onClick={run}>{running ? "Running…" : "Run tests"}</button>
            <button disabled={!s.lastRun} onClick={() => setReview(techLeadReview(passed, hasNewTest))}>Ask Dev for a review</button>
            <button disabled={!s.lastRun} onClick={() => setVerdict(makeVerdict(passed, hasNewTest, msgs))}>Finish the week</button>
          </div>
          {output && <pre className={passed ? "ok" : "bad"}>{output}</pre>}
          {review && <div className="card"><div className="meta">Tech Lead review · recorded sample</div><p style={{ whiteSpace: "pre-wrap" }}>{review}</p></div>}
        </section>
      )}

      {verdict && (
        <section className="verdict">
          <div className="meta">Supervisor's end-of-week review · recorded sample</div>
          <h2>{verdict.summary}</h2>
          <ul className="skills">{verdict.skills.map((k) => <li key={k.skill}><b>{k.skill}</b> {k.score}/5<br /><small>{k.evidence}</small></li>)}</ul>
          <h3>Went well</h3><ul>{verdict.wentWell.map((x) => <li key={x}>{x}</li>)}</ul>
          <h3>To work on</h3><ul>{verdict.toWorkOn.map((x) => <li key={x}>{x}</li>)}</ul>
          <p><b>Next step:</b> {verdict.nextStep}</p>
        </section>
      )}
    </div>
  );
}
