# ADR 0029: Seven more roles, each with its own practice project

## Context
The goal is a place where someone can see what any AI job is like, not only the three golden
roles. Adding a role must not add a daily paid research run, nor break the evaluation labels,
and the practice project must work with no model call and no ML library (the sandbox has numpy
and pandas only, and a project written with libraries would hide how little code the point needs).

## Decision
Seven roles are added: ML Engineer, Data Scientist, MLOps Engineer, AI Data Engineer, NLP
Engineer, Computer Vision Engineer and AI Product Manager.

- **On-demand, not golden.** Each `data/roles/<slug>.yaml` has `trust_level: on_demand`. The daily
  schedule runs golden roles only and the classifier labels cover golden roles only, so neither
  changes. A role is researched when asked for: `make research role="..."`.
- **Hand-written practice projects**, same method as ADR 0026, one module per role
  (`demo_ml.py`, `demo_data_scientist.py`, `demo_mlops.py`, `demo_data_engineer.py`,
  `demo_nlp.py`, `demo_vision.py`, `demo_product.py`) on top of `demo_kit.py` (tickets, rubric and
  the five-day week are built from short specs). Each has the same shape: a dashboard number that
  looks good, two realistic mistakes behind it in two separate files, a starter whose tests fail,
  a reference that passes, and a regression-test ticket. All stdlib Python.
  - ML Engineer: late-payment model; the same customer on both sides of the split, and accuracy
    only (91% shown; 62% honest, below the 75% of always guessing "on time").
  - Data Scientist: checkout A/B test; conversion per session not per shopper, and no
    confidence interval (+16.5% shown; +1.3%, interval spans zero).
  - MLOps Engineer: drift monitor; compares each week with the last, and fills missing inputs
    with old values (green for twelve weeks; drift is visible by week 3).
  - AI Data Engineer: feature pipeline; keeps the first record, not the latest, and a load rate
    that cannot fall below 100% (28 of 40 customers stale; 93.3% really loaded).
  - NLP Engineer: ticket router; live text not cleaned like training text, and no "other" option
    (90% offline; 30% live with the starter code).
  - Computer Vision Engineer: detector scoring; duplicates counted as finds, and photos with no
    detections skipped (98% precision and 90% recall shown; 64% and 60% honest).
  - AI Product Manager: assistant launch readout; abandoned chats counted as resolved, and cost
    divided by all conversations (78% and 1.59 shown; 46% and 3.46 honest, so the launch rule
    fails).
- **Numbers are measured by code** (in each answer key) and tests check that the dashboard
  numbers overstate and that the project's own two tests catch each mistake alone.
- **Skills** use the existing taxonomy.

## Not done
- No researched report for any of the seven. A project needs one report version for its role to
  exist in the database (`make seed-demo` says so): run `make research role="..."` first, which
  needs `ANTHROPIC_API_KEY` and job-board access on the owner's machine. The home page lists roles
  with a published report only.
- No real practitioner has reviewed the scenarios or rubrics. Treat them as first drafts.
- No web or demo-site changes: the static demo still shows one role.
