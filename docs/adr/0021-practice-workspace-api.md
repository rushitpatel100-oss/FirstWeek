# ADR 0021: The practice workspace API

Status: accepted, 2026-11-02

## Context

The shortened finish line needs a learner to open an approved project, edit files, run the tests and get a code review, without the multi-agent simulation. The project already has a sandbox (ADR 0017), approved blueprints with starter files (ADR 0019, 0020) and a ground rule that agents never see the answer key.

## Decision

`firstweek_simulation.workspace` holds the logic; `firstweek_api.workspace` exposes it:

- `GET /roles/{slug}/project`: public blueprint and starter files of the newest approved project. Never the answer key, reference solution or hidden `key/` scripts.
- `POST /roles/{slug}/project/tests`: the starter plus the learner's edits run `pytest` in the sandbox. Given test files cannot be rewritten (new ones can be added); paths under `key/` are refused.
- `POST /roles/{slug}/project/review`: the server runs the tests itself, then one model call (prompt `tech-lead-review.v1`, tier from `SIMULATION_TIER`, free by default) reviews the work against one ticket. The reviewer reads the public view, the files and the real test output, so it cannot leak the key and cannot be fed fake test results by the browser.
- Limits in memory (as ADR 0016): 30 test runs and 10 reviews an hour per client, 200 reviews a day in all, 5 cents per review.

## Consequences

One reviewer instead of a team of colleagues, no five-day clock: enough for a demo and for a first real user. The reviewer does not know the planted issues, so it reviews like a colleague who only reads the code; catching them is the learner's job, and the evaluator (later) is the one that reads the key.
