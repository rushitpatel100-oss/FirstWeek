# Handoff: where FirstWeek stands

Start a new conversation with: **"Continue FirstWeek: read `docs/handoff.md`."** This page, `CLAUDE.md`, the ADRs, the learning log and the plan doc hold everything a new conversation needs. Update this page at the end of every step.

Last updated: 2026-11-07 (portfolio version finished).

## Where we are: finished

The portfolio version is done (README "What is built, and what is not"):

- **Live:** the free static demo on GitHub Pages and a 45-second video (ADR 0025).
- **Practice projects:** hand-written projects and five-day internships for all three golden roles: GenAI Engineer (Northwind), Agentic AI Engineer (Harbor Travel), AI Software Engineer (Relay Systems). No model call needed (ADRs 0022, 0023, 0026). Colleagues and the supervisor fall back to stock replies without quota.
- **Research and reports:** M1 and M2 done, including the claim verifier, human review and publishing, and the skill-gap check. All three golden roles have a published report with no key: researched on 2026-11-07 from 96 hand-checked UK postings and practitioner blogs, kept in the repository, loaded by `make seed-reports`, re-checked by `make check-reports` (ADR 0027).
- **Workspace:** practice screen, tests in the Docker sandbox, Tech Lead review (ADR 0021).

**Parked: automatic project generation (`make autopilot`, ADR 0020).** Built and heavily hardened (local Ollama model, repair rounds, code-level fixes), but with free models its validation gate has never approved a project: the starter's tests and the separately planned reference solution disagree, and the generated code sometimes calls the network, which the sandbox does not have. If it is picked up again, the structural fix is to build the correct solution and its tests together first, make them pass, and only then plant the issues; and to require tests that never touch the network. Do not resume patching it failure by failure.

Not built: M6 (skill matrix, GitHub export, CV bullets) and a hosted deployment of the full app (kit ready in `docs/deploy.md`, ADR 0024).

## Waiting on Rushit (optional)

- Merge PR #40 (a stopped Docker shows "code runner unavailable" instead of a raw error).
- Run `make seed-reports` once so the three reports show on the home page. A pipeline report published later replaces the researched one for that role.
- Practitioner interviews (3 to 5) would fill "a typical week" in the reports.

## How we work

- Claude builds, Rushit reviews. Each step is one PR with tests and a walkthrough: What, Why, Decisions needed, Try it. Calls Claude makes on its own are flagged as such.
- Rushit runs things on his machine (WSL2 Ubuntu, Docker Desktop, `~/code/firstweek`) and replies "next", "go", "agree" or pastes output.
- After each step: an ADR if the decision is notable, one line in `docs/learning-log.md`, the plan doc checklist, and this page.
- To make usage limits last: one new conversation per step, Sonnet by default, Opus only for design-heavy steps.

## Links

- Plan doc: https://claude.ai/artifact/FAq86BNqUZTYUSLBUwfuhK (M2 checklist list `mbtr61qmkxy.27120`; status paragraph `mbtr61qmkxy.43393`).
- Repo: https://github.com/rushitpatel100-oss/FirstWeek

## Notes for Claude's workspace

- Attach the repo `rushitpatel100-oss/FirstWeek` and clone it before anything else.
- `gh pr create` fails there (GraphQL is blocked). Open PRs through the REST API:
  `jq -n --arg title "..." --arg head BRANCH --arg base main --rawfile body BODY.md '{title:$title,head:$head,base:$base,body:$body}' | gh api repos/rushitpatel100-oss/FirstWeek/pulls --input -`
- Database tests need Postgres: run `service postgresql start` before `make check`, or about 30 tests are skipped.
- There are no API keys in the workspace, so runs on real data (`make research`, `make report`) happen on Rushit's machine.
