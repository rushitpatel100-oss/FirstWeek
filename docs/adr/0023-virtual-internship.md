# ADR 0023: The practice project becomes a virtual internship

Date: 2026-11-02. Status: accepted.

## Context

The product is a virtual internship, not a report with an exercise: someone joins a made-up company
for a week and learns whether they can do and like the work. The report is the evidence engine
behind it, not the front door. The workspace (ADR 0021) is the work loop; what was missing was the
week around it: people, things that happen each day, and a review at the end.

Collected UK postings for the three golden roles (94 postings, May to October 2026, matched by
title because classifier decisions were not stored in the container database) mention Jira in 0%,
agile or sprints in 3%, stakeholders in 37%, cross-functional work in 38% and
ambiguity, autonomy or ownership in 72%. Postings rarely name tools, so this is no proof that
teams skip tickets, but it is no evidence that they use them. The internship therefore delivers
work as requests of several kinds (a manager's message, a colleague's complaint, a ticket, a
meeting), and the ticket is one of them.

## Decision

- A week is data: `internship.json` beside the project's files (`Internship` contract: colleagues
  with private personas, events on days 1 to 5). A project without one keeps the plain workspace.
- Colleagues chat in character: one model call per message, built from the public blueprint and
  only the events up to the current day, so they cannot leak the answer key or the future.
  Personas never leave the server. They may say they do not know.
- The supervisor's review at the end of the week is one structured call (`SupervisorVerdict`):
  rubric scores 1 to 5 with evidence from the code, the final test run and what the learner wrote
  in chat. It is framed as evidence about the week's work, never a verdict on the person.
- The week's state (day, chats) lives in the browser only (localStorage, optional). No accounts.
- Limits: 40 chat messages per hour per client and 500 a day overall (about $0.02 each at most),
  5 reviews an hour and 100 a day (about $0.05 each at most).
- The demo project ships a hand-written week (`demo_internship.py`), written by `make seed-demo`,
  so the internship works without any model call to build it. Generated projects get scripts later.

## Not decided or not built

- Scripts for generated projects (the autopilot does not yet write one).
- Colleagues that act on their own (they only answer), and a longer week than five days.
- A progress screen beyond the end-of-week review.

## Addendum 2026-11-02: autopilot writes the week

After the gate approves a project, autopilot makes one more call (`design-week.v1`, up to 3 tries) that writes the colleagues and the week from the public blueprint only. Code rejects a script unless every ticket is assigned exactly once, on or before its due day, by a colleague who exists; no message mentions code or an unknown ticket; events fall on at least four days; and day 4 or 5 asks for a plain-words explanation. A week that never passes leaves the project approved and playable as a plain workspace. `internship.json` is written after `save_artifacts` (which clears the folder first); `make autopilot` also writes `week.json` to its output folder.

## Addendum: when the free quota runs out
Chat and the end-of-week review no longer fail with 503 when every free model is spent. The chat
returns a stock reply that says it is stock; the review is computed from the evidence alone (test
result, whether a new test was added, whether the intern wrote to anyone) and is labelled
"Automatic review". The response `model` is `offline`. A 502 (an answer that never validated) is
unchanged.
