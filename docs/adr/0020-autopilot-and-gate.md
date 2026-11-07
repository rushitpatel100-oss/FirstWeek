# ADR 0020: Autopilot, the validation gate and the free model tier

Status: accepted (2026-11-02)

## Context

The project needs to be finished quickly and almost free, with as little hand-holding as possible. Up to now each step was run by Rushit on his machine and pasted back, and design and build used the paid mid tier.

## Decision

- **Free by default**: `SIMULATION_TIER` (default `judge`, the free Gemini model) picks the tier that designs and builds projects. `mid` or `frontier` is a one-line change. A weaker free model will get more things wrong, so:
- **The gate decides, and retries**: `run_pipeline` designs a blueprint, builds the project (ADR 0019) and, if any check fails, builds again up to three times with the failures written into the planner's prompt (`plan-starter.v3`; v2 stays as released). A blueprint is approved only if the starter runs and fails its target tests, the reference solution passes them, and the reference's measured numbers exist. Approval is automatic and labelled so: `validated=true`, `status='approved'` in the database, "APPROVED (automatic)" in the report. Nobody has looked at it; a person can still review it later.
- **One command**: `make autopilot role="..."` (database) or `python -m firstweek_simulation autopilot --report-file data/reports/<slug>.json` (no database). The output folder holds the blueprint with its answer key, the checks of every attempt, the measured metrics and the starter, reference and key files.
- **Cloud run**: `.github/workflows/autopilot.yml` (manual) does the same on a GitHub runner, which has Docker, so the pipeline runs without anyone's terminal. It needs the repository secret `GEMINI_API_KEY` and a report snapshot from `make export-reports`. The result is uploaded as a private workflow artifact.

## Consequences

- Cost is zero on the free tier (rate limits apply; the gateway already retries). Free-tier prompts and replies may be used by the provider to improve its models: only public report text and invented project material go in, never personal data or keys.
- The gate checks that the material runs and that the numbers are measured. It does not check that the tickets are good or the flaws are interesting; that is still a human's call, now after the fact.
- Not yet checked: that every acceptance criterion maps to a check, and that the dataset matches the brief. Those are cheap to add once real runs show which failures actually happen.

## Addendum: the free tier waits out overload

The first real autopilot run died on a Gemini 503 ("high demand") after LiteLLM's two quick retries. Free models are overloaded in bursts, so for tier `judge` only the gateway now tries the models in `model_judge_fallbacks` in turn, and if all are busy waits 20, 40 and 80 seconds between four passes before giving up. Only overload, rate limit and connection errors count (`is_transient`); a bad request fails at once. Paid tiers never fall back or wait: silently swapping a model you pay for would hide cost and quality changes. The result records the model that actually answered.

Second real run: the first call hung 10 minutes (LiteLLM's default timeout is 600s), and `gemini-2.5-flash` answered 404 (retired for new users). Free-tier calls now time out after 120s with LiteLLM's own retries off (the gateway does the retrying), a 404 skips to the next model, and the dead model left the fallback list.

Third real run: the pipeline got through design and one full build attempt, then hit the free tier's hard cap of 20 requests per day per model (`GenerateRequestsPerDayPerProject`). The gateway now recognises a per-day 429, stops asking that model, and fails at once when every free model is spent instead of waiting minutes for a quota that returns tomorrow. Consequence: one autopilot run needs roughly 20 to 30 calls, so the free tier finishes about one run per day at best; paying for the same Gemini flash models (cents per run) is the cheap way past it.

## Addendum 2026-11-02: Groq as a second free source

With `GROQ_API_KEY` set, `groq/openai/gpt-oss-120b` joins the end of the free chain (Gemini, the Gemini fallback, then Groq), so one provider's daily cap no longer stops chat, reviews or autopilot. Groq's free limits (about 1,000 requests, 200K tokens a day and 8K tokens a minute on that model) are tight for long reviews; billing on the Gemini key is the lasting fix. `Settings.has_judge_key` replaces the Gemini-only key checks.

## Addendum (2026-11-03): fewer calls, fewer tokens
Free quotas ran out mid-build. Three changes:
- Files are written up to four per call (`write-files.v1`, `write-reference-files.v1`, each file
  after a `=== path ===` line). A cut-off batch is split in half; a file left out is asked for alone.
- Writers see outlines of earlier code files (signatures, docstrings, constants) and the first
  12 lines of data files, not everything written so far. The reference planner and writers see the
  starter's data the same way (it can be 200 KB per file).
- A retry whose starter passed its checks keeps it and redoes only the reference solution
  (`plan-reference.v2` takes the failures as feedback).
A typical attempt drops from about 19 calls to about 7, and a reference-only retry to 2.

## Addendum (2026-11-03): never lose work to the free quota
- **Pre-flight**: before any call, the autopilot counts today's successful calls per free model in
  `llm_calls` since the last Pacific midnight (`firstweek_core.llm.quota`) and refuses to start
  unless what is left covers the worst case (`WORST_CASE_CALLS` = 36; two fresh Gemini models give
  40). `make autopilot-check role=...` shows the numbers without calling a model; `--force`
  starts anyway. Calls made outside this app are not seen, so the count is a floor.
- **Pause and resume**: when every free model is spent the gateway raises
  `FreeQuotaExhaustedError`; the pipeline saves a checkpoint (`var/autopilot/.checkpoints/<slug>.json`:
  blueprint, attempts used, feedback, a starter that passed) and exits with code 2. The same
  command later continues from there. A finished run deletes the checkpoint.
- **Groq's per-minute cap**: Groq counts prompt plus `max_tokens` against 8,000 tokens a minute,
  so an 8,000-token reply limit could never fit. Each Groq call now asks for only the room that
  fits, and a prompt that cannot fit skips Groq instead of failing.
- **Ask, do not only count** (later the same day): the check said 30 Gemini calls were left while
  Google refused both models with 429. Our records miss requests Google counts. The pre-flight now
  probes each free model with a one-token request (`LLMGateway.probe`, no fallback, recorded as
  `quota-probe`), says why one refused (spent for today, no free tier, busy this minute, not
  found), and counts only models that answered. It costs one request per model.
- **Check the plan before writing files** (first real build, 2026-11-04): all three attempts failed
  on slips visible in the plan itself (tests planned under `evals/`, `metrics.json` listed as
  generated, a path both written and generated), after six calls of file writing each. The path
  checks now run on the plan (`plan_problems`), `repair_plan` fixes by code what needs no judgement
  (`metrics.json` is not generated; a generated path is not also written), and a plan that still
  fails is made again with the problems as feedback (up to `REPLANS` = 3, one call each) before any
  file is written. `plan-starter.v4` states the tests/ and one-owner-per-path rules.

## Addendum 2026-11-04: a local model with no limit

Free hosted tiers cap requests and tokens a day, so the autopilot cannot run whenever the author wants. `MODEL_LOCAL=ollama/<model>` puts a model on this machine (Ollama) first in the judge chain: no daily limit, no key, no cost (priced at zero, reported as "no limit" by the pre-flight). The hosted free models stay behind it as fallbacks. Gateway passes `api_base`, a 12K `num_ctx` (Ollama's default silently cuts long prompts) and a 15-minute timeout for local models. Trade-off: a 7B model on a 6 GB graphics card makes more plan mistakes than the hosted ones; the plan repair and retries absorb some. Generate, review, commit.

Follow-up the same day: a 7B model could not produce a valid project design (invalid task types, rubric gaps). `MODEL_LOCAL_PURPOSES` (default: the two file-writing calls) now decides which calls go to the local model first; the design and the plans stay on the hosted free models, a few requests a run.

## Addendum 2026-11-06: repair where it fails, not a whole new attempt

With a local model doing the writing, every failure still threw away the attempt and spent hosted planning calls on a new one: a stray `---` in `make_data.py`, a generator that forgot one of its files, a test with a miscalculated expected value. Now each check is repaired where it fails, then run again:

- Code first, no model: fences and a trailing separator with an explanation are removed when that makes the file compile.
- Every Python file must compile and every JSON file parse before anything runs; a file that does not is rewritten on its own, with the error.
- The generator, the starter's tests, the reference's tests and the metrics script each get up to 4 fix-and-run rounds (`repair-files.v1`): the error output and the files it names (or the modules a failing test imports) go back to the writer, which returns whole files. Only those files may change; a cut-off reply, or one that does not compile, changes nothing.
- Rounds escalate, because a small model asked the same way repeats the same broken answer: round 2 says the earlier fix failed and runs warmer; from round 3 the broken file is withheld and written fresh from the plan's notes, which every starter repair sees.
- A test may be corrected only if the corrected test still fails on the starter (otherwise it no longer finds the planted issue) and still asserts something.
- With a local model the rounds are free; with hosted models only, each check gets 1 round so the daily quota lasts.
- A model on this machine writes one file per call (`write-one-file.v1`, `write-one-reference-file.v1`): the exact header line is given, the reply stops at the next header, 4,000 tokens at most, and a reply that wrote some other file is asked again twice. Small models otherwise write the whole repository on every call, and take the placeholder `=== path ===` literally. The reference writer sees the files it changes in full and the rest as outlines. A local reply is sized so prompt and reply fit `ollama_num_ctx`.
- What the person receives gives nothing away: comments, docstring lines and README sections that mention a planted, deliberate or intentional flaw are removed by code (small models write `# FLAW: ...` however they are asked).
- A file under 150 lines that runs past the limit is a model repeating itself: it is asked again at the same limit, warmer, not at double the room.
- The two key scripts are asked for with how they are run spelled out (exact paths, `main()`, `--seed`, folders, the `__main__` guard): the generator was the file small models got wrong most often.
- A later attempt writes warmer (a deterministic local model writes the same files again otherwise). A good starter is reused once, to redo only the solution; if that fails too, the next attempt starts fresh, because the starter's own tests may be what cannot be satisfied.
- A test file with no failing test on the starter is noted for the reviewer (the planted issue it targets may be missing); it does not fail the gate.
- The local model is also the last fallback for the calls that try hosted models first (design, plans), so a run never stops for quota.
- A plan that never parses, or an attempt that crashes, is a failed try with its error recorded, not a lost run.

How this was tested: unit tests for every path above, and real runs of the pipeline code against a real local model, Qwen2.5-Coder 3B on CPU (the 7B the author runs did not fit the test machine's memory), with the design from the author's last run and a hand-written plan standing in for the hosted planner. Those runs found most of the problems fixed here (placeholder headers taken literally, whole repositories written per call, `# FLAW` comments, looping replies, a repeated broken repair). With the 3B model, file writing, the starter stage and the repair rounds worked as designed; the 3B could not write a correct data generator or fix its own wrong test expectations, so no 3B run reached approval. The 7B is the model to use.

## Addendum 2026-11-07: fix by code what a run should never fail on

The author's first run with the repair rounds still failed, three times, on things no repair should have to fix: `import requests` (not installed in the sandbox), a model-written `pytest.ini` with `addopts = --flake8` (pytest stopped before any test ran), and `List` used without importing it. Its report also showed the repairs had gone to Groq, not the local model: a dataset written as one long JSON line went whole into every repair prompt (previews cut by lines, not characters), which no longer fit the local model's window, so the gateway sent each repair to a hosted model and spent the daily quota.

- Data previews are cut by characters as well as lines, and a repair prompt shows the other files most related to the ones it repairs first, within 12,000 characters, then only names.
- The sandbox image has `requests` (models reach for it for any API client), and `make autopilot` builds the image first (cached: seconds).
- Imports of anything else the sandbox lacks are found by code before anything runs, and the file is repaired with that reason.
- Config files a model plans (`pytest.ini`, `setup.cfg`, `pyproject.toml`, `tox.ini`, `.flake8`, `mypy.ini`) are dropped, and tests run with `-o addopts=`, for the learner too.
- A typing name or common standard-library module a file uses but never imports is imported by code.
- Each repair round works on one failing test file, a different one each round, with the sources its traceback names and the modules it imports. 6 rounds with a local model.
- Round 3 of each repair goes to a hosted model first (purpose `repair-hard`): a 7B model often cannot see a bug it wrote itself and repeats it every round (seen: a rate counted per retry instead of per call, five rounds running). One hosted call per failing check costs little quota; without quota it falls back to the local model.
- A test file is never withheld in a rewrite round (it is the spec, and a wrong expected value is corrected in it), and the plan's notes stay with a reused starter, so a later attempt's repairs still know which of code and test is wrong.
- A syntax error shows the offending line; `name = lambda ...: raise ...`, a slip the 7B made repeatedly, is turned into a def by code.
- The report lists the calls each model made, so a run shows whether repairs stayed local.

Tested with the 7B model (Qwen2.5-Coder 7B, Q3 to fit the test machine; the author runs Q4) writing every file from a stand-in plan: the generator ran first time, the starter stage passed, and the reference failed 1 test of 4 on a bug the local repair rounds could not see, which is what the hosted round 3 is for. The test machine has no hosted model, so that round could only be tested by unit tests.

## Status 2026-11-07: parked

The portfolio is finished without it: learners use the hand-written projects (ADRs 0022, 0026). The author's last run, with every fix above, passed every starter check and kept repairs local (23 local calls, 3 Gemini), then failed the reference check in all three attempts for two reasons the patches cannot reach: generated code called a real URL, which the sandbox cannot resolve, and the tests (written from the starter plan) and the reference (written from a separate plan) disagreed on behaviour, such as raising versus returning an error. Fixing one failure at a time moved the failure one stage on each time. If this is picked up again, change the design instead: write the correct solution and its tests together, make them pass, then plant the issues into a copy; and require tests that never touch the network.
