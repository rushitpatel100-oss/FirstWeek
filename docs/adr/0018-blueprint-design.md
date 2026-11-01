# ADR 0018: Blueprint design

Status: accepted (2026-11-01)

## Context

A simulation needs a project: a fictional company, tickets, and a rubric, built on what the job is really like. The plan's rule applies: facts about a real role come only from collected evidence. The company is fiction; the pain points it dramatises must not be.

## Decision

- **New package `services/simulation`** (`firstweek_simulation`) holds simulation design. The validation gate, dataset and starter repo (M3 steps 3 and 4) will live here too.
- **Built from the stored report**: its pain points (numbered), responsibilities and the skills postings ask for (10% of postings or more, at most 30). Rejected claims are already gone from the stored report.
- **Task-type library** (`data/task_types.yaml`): seven types, each marked checkable or not, and the types each golden role may use. Other roles get a default set. Every set includes `code`.
- **The model proposes, code checks** (`design-blueprint.v1`, mid tier, one structured call): pain point numbers must exist (one to three, distinct); task types must be allowed for the role; tickets must fall on at least three days and include a code ticket; ticket and rubric skills must be listed ids, each rubric skill assessed by a ticket and each ticket skill in the rubric; rubric anchors are a list of exactly five different descriptions (the schema enforces the count; a dict keyed 1 to 5 failed with a mid-tier model). On problems, the model gets the list and one repair attempt; after that the caller sees the problems.
- **Code does the bookkeeping**: ticket keys (`GENAI-101` ...) in due-day order, rubric weights scaled to sum to 1 (none under 0.05).
- **Saved as a draft** in `blueprints` (`validated=false`): the public view in `blueprint`, the answer key apart. The answer key's reference solution is `pending:reference-solution` until step 3 produces it.
- `make blueprint role="..."` prints the blueprint (answer key included, for the reviewer) and saves the draft; it costs a few cents on the mid tier. If the designs prove thin, move `BLUEPRINT_TIER` to frontier (about $0.30 each; blueprints are built once per role).

## Consequences

- Nothing checks yet that the planted issues can be built, that the acceptance criteria map to real checks, or that the starter repo fails and the reference solution passes. That is the validation gate (step 4); until then a blueprint stays a draft.
- Grounding is by pain point number, which stops invented evidence but not a scenario that drifts from the pain point it names. Rushit reviews each blueprint before approval.
- Temperature 0.7: blueprints should vary between roles and reruns; the gate, not the model, decides what is acceptable.
