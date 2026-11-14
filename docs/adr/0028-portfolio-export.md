# ADR 0028: Portfolio export from a finished week

## Context
M6 asks for a skill matrix, CV bullets and a repo export. The supervisor already scores skills
(ADR 0023). The plan also says CV bullets use only numbers we measured.

## Decision
A pure-code module, `firstweek_simulation.portfolio`, with no model call.

- **Skill matrix.** The supervisor's scores laid against the rubric weights, strongest first, with
  a rubric-weighted mean out of 5.
- **CV bullets.** Built only from the final test run (passing and failing counts), the files the
  learner changed (tests added) and the supervisor's scores. Only skills scored 4 or 5 are named.
  Each bullet says it was a practice simulation and names the AI reviewer. Nothing is estimated.
- **Export.** `POST /roles/{slug}/internship/portfolio` re-runs the tests, so counts never come from
  the browser, and returns a zip of the learner's repo with `PRACTICE.md`, `CV_BULLETS.md` and
  `skill_matrix.json`. The hidden `key/` side is never included.
- **Zip, not a GitHub push.** Pushing needs a GitHub sign-in and write access to the learner's
  account. A zip works with no keys; the learner can push it themselves.

## Not done
Judge calibration (blind-score 30 submissions, kappa 0.6 or higher) needs the owner's own scores.
The scores in the matrix are the supervisor's and are not yet shown to agree with a human's.
