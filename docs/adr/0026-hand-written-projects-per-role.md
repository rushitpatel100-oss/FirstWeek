# ADR 0026: Hand-written projects per role

## Decision
Free model quotas cannot build a project reliably (about 30 calls per attempt against roughly 20
a day per Gemini model). The three golden roles therefore get projects written by a person, like
the GenAI one (ADR 0022), and the autopilot stays an extra.

- `demo_project.Pack` bundles a project: scenario, tickets, rubric, planted issues, measured
  numbers, files and week. `PACKS` maps a role slug to its pack; other roles get the GenAI one.
- `demo_agentic.py` is the Agentic AI Engineer project: a travel-booking agent whose nightly report
  is green. Bugs: tool errors swallowed to an empty string, a loop that ignores `MAX_STEPS` and always
  says done, and a report that drops crashed runs. The model is scripted, so it runs offline.
- Tests run the starter (fails) and reference (passes) through the same sandbox check as the
  autopilot gate, and each bug has a test that catches it alone.

## Consequences
`make seed-demo role="Agentic AI Engineer"` works with no model. The AI Software Engineer project is
still to write. Hand-written projects are labelled as such to the owner and make no claim about a
real company.

## Addendum 2026-11-04: AI Software Engineer

The third golden role now has its own hand-written project (`demo_software.py`): a completion service with a cache and retries in front of a fake model API. Two planted bugs: the cache key ignores the model (dashboard claims 60% hits, true rate 38.3%), and retry swallows every error, including bad requests and a final rate limit. All three golden roles now work with no model call and no quota; the autopilot stays an optional extra.
