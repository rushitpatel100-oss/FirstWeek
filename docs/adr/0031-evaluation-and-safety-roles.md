# 0031: AI Evaluation Engineer and AI Safety Engineer roles

Status: accepted, 2026-11-14

## Context
ADR 0029 added seven on-demand roles. Two jobs that many AI teams now hire for were missing:
people who measure whether an AI system can be trusted, and people who test and build its
safeguards. Both are close to what the earlier projects teach (numbers that flatter), but in a
setting a learner will meet in every AI team.

## Decision
Two more on-demand roles, each with a hand-written stdlib-only project, two planted mistakes in
separate files and a five-day week, built from the same kit as ADR 0029:
- AI Evaluation Engineer (Halden Insurance): the grader passes answers that deny the fact, and the
  dashboard leaves out questions with no answer. Dashboard 88.5%; honest 63.3%.
- AI Safety Engineer (Brackenridge Bank): the guard misses attacks in capital letters, and the
  dashboard counts harmless prompts allowed as wins. Dashboard 90%; attacks actually stopped 50%.
Neither is scheduled. Each needs `make research role="..."` and then `make seed-demo role="..."`.

## Consequences
- Eleven roles can now have a project; the role definitions are not yet reviewed by a practitioner.
- The projects deliberately leave the guard's "password" rule in place: it wrongly blocks 5.6% of
  harmless prompts, which a good learner should notice and report, not fix silently.
