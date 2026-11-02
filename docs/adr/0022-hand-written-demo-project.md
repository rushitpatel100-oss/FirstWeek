# ADR 0022: A hand-written demo project

Status: accepted, 2026-11-02

## Context

Autopilot (ADR 0020) writes projects with a free model and has not yet finished one end to end: the free Gemini tier allows 20 requests a day per model and a run needs 20 to 30. The workspace (ADR 0021) cannot be tried, demoed or tested against real data without an approved project.

## Decision

`make seed-demo role="..."` stores a project written by a person (`firstweek_simulation.demo_project`) as an approved blueprint for the role's newest version, with its starter and reference files under `ARTIFACTS_DIR`. No model call, no cost. The project: an insurer's claims assistant reports about 90% citation accuracy, support disagrees; two realistic bugs (substring match instead of equality; uncited answers dropped from the denominator) inflate the number. Three tickets, four tests, a rubric over four skills.

It is held to the same gate as model output: tests check that the starter fails, the reference passes, each bug is caught by its own test, and that the public view hides the key. It is labelled hand-written in the CLI and these docs, never presented as model output, and it makes no claim about any real company.

## Consequences

The workspace can be shown today, on all three AI roles (the story is about an LLM assistant). Autopilot stays the way to get role-specific projects; when it produces an approved one, the newest approved blueprint wins in the workspace.
