# 0009. Measure the role classifier against hand labels

- Status: accepted
- Date: 2026-10-31

## Context

Every number in a Role Reality Report depends on the classifier's yes or no: is this posting the role? On 2026-10-31, two runs with almost the same definition gave GenAI Engineer samples of 15 and 17. Without a reference, there was no way to tell which postings were right, or whether answers change between runs. Reading the classifier's reasons by eye (`make review-matches`) helps, but it doesn't scale and doesn't produce a number.

## Decision

- **A packaged labels file** (`data/eval/classifier_labels.yaml`): 112 UK postings, each judged yes, no or unsure for all three golden roles (336 labels), with a one-line reason. The sample is every candidate from the 80 job boards except generic "Machine Learning Engineer" titles, plus 15 of those with distinct titles. Generic ML titles are mostly clear negatives, while the agent, GenAI and software titles hold the hard cases.
- **Labels are keyed by posting URL**, so they work on any database that collected the same boards.
- **Provenance is explicit.** Claude drafted the labels from each posting's text, judged against the definitions as worded on 2026-10-31. `checked: true` marks a label Rushit has confirmed. Until most labels are checked, scores measure agreement with a second, stronger model, not accuracy, and the command says so.
- **"Unsure" is a first-class answer.** It means the definition doesn't settle the case (38 of 336). Unsure labels are reported but not scored, and each one points at wording that needs sharpening.
- **`make eval-classifier`** scores the stored decisions as the statistics use them (counted means judged the role with confidence ≥ 0.5). It reports agreement, precision, recall and F1 per role, plus how many labelled postings have no current decision, and lists every disagreement with both the model's reason and the label's reason.
- **`make eval-classifier repeats=N`** re-asks the classifier N times per labelled posting without storing anything, and reports how many postings change their answer. That is the run-to-run instability that moved the sample from 15 to 17.

## Consequences

- Reviewing disagreements is the cheapest way to improve both sides. Where the label is wrong, the label changes and is marked checked. Where the model is wrong, the definition or prompt changes, as a new prompt version, and the evaluation shows whether it helped.
- The labels describe the 2026-10-31 definitions. When a definition's meaning changes, the affected labels need revisiting; the file's notes say why each label was given.
- Postings close over time. Labels for postings outside the 6-month window drop out of scoring, so the set will need refreshing with new postings every few months.

## Alternatives considered

- **No labels, only reading reasons:** no number to track, and no way to compare prompt versions.
- **A second model as judge on every run:** cheaper for a person, but it measures agreement between models. That is what the unchecked drafts are; human checking is what turns them into a reference.
- **Labelling only GenAI Engineer:** faster, but the three roles overlap, and most hard cases sit on the boundaries between them.
