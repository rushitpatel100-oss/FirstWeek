# 0013. The report writer: numbers by code, prose from checked evidence

- Status: accepted
- Date: 2026-10-31

## Context

The Role Reality Report is the product's first deliverable. The plan sets its rules: the model writes "only from the aggregated statistics and retrieved evidence passages, never from free recall"; postings say what employers ask for and practitioners say what the work is like, so the two stay apart; forum posts are weak evidence (weight 0.5, "never the only source"); and the wording matches the data ("never says usually when the data says sometimes"). A separate verifier and a confidence score come next. This step writes the draft they will check.

## Decision

**Numbers are written by code.** The headline ("Based on 33 GB job postings from 21 employers, May 2026 to Oct 2026. Most roles ask for Python (78%) ...") and "What employers ask for" come straight from the latest statistics version, worded by the plan's bands: 60% or more is "most", 30 to 59% "many", 10 to 29% "some", and under 10% is left out. A model never computes or restates a share.

**Prose comes from retrieved passages, one section at a time.** Each section has its own question, its own evidence tiers and its own searches (ADR 0012's hybrid search, scoped to the role):

| Section | Evidence | Answers |
|---|---|---|
| What employers say the job involves | postings counted for the role | what is built and owned, with whom |
| What the work is like day to day | blogs, interviews, forums | activities, workflows, tools |
| A typical week | blogs, interviews, forums | how time is split |
| The hard parts | blogs, interviews, forums | what is difficult or unglamorous |
| In short (written last) | only the claims that survived the checks, and their passages | the job, the work, the hard parts |

Each section sees up to 24 passages, at most 3 from one source, labelled P1, P2... with the source type, publisher and title. The model returns a `SectionDraft`: up to 8 one-sentence claims, each citing 1 to 3 passages with a word-for-word quote, plus `not_covered` for what the evidence doesn't support. The prompt is `synthesise-section.v1`.

**Every claim is checked by code before it is kept:**

- each citation must name a passage the model was shown, and its quote must be in that passage (the same quote check as extraction, ADR 0007);
- a claim supported only by forum posts is dropped;
- "most", "usually", "typically", "generally" and "the majority" are never allowed in prose, since frequency comes only from the statistics. "Often", "many", "several" and "common" need at least two different sources;
- every number in a claim must appear in one of its quotes.

Dropped claims are listed with the reason in the draft, so a reviewer sees what the model tried to say and why it didn't survive.

**Model.** The frontier tier (Claude Opus 5.5), because the report is the product and a role's report is rewritten only when its statistics change. Five calls per report, an estimated $0.50 to $0.80, capped at $1.50 by default.

**Output.** `make report role="..."` prints the draft as markdown (claims with numbered sources, then what was left out) and saves it under `reports/` (git-ignored: it is generated, and full of third-party quotes). Nothing is stored in `role_reports` yet: a report is stored once the verifier has labelled every claim and given it a confidence score.

## Consequences

- A wrong number can't appear in a report: either code wrote it from the statistics or it is in a quote.
- The code checks catch invented citations, misquotes and overclaiming words, but not a real quote cited for a claim it doesn't support. That is the verifier's job (the next step), by a model from another family.
- Practitioner sections are only as good as the web evidence collected. When there's little, the sections are short and `not_covered` says what's missing, which is the honest outcome.
- The section searches are written for AI engineering roles. On-demand roles will need searches generated from the role definition.

## Addendum: after the first real draft (2026-10-31)

The first GenAI Engineer draft (statistics version 9, $0.44) held up on its citations but showed five problems. The fixes:

- **Claims that pointed at each other.** "The same writer describes ..." opened a section after the claim naming the writer was dropped by the checks. Claims are checked one by one, so each must stand alone: `synthesise-section.v2` says so, and a code check drops claims that open with "They", "He" or "She" or say "the same writer", "this team" and the like.
- **Off-topic evidence.** A claim about developers in general (16% of the week on coding) reached the role's report. v2 tells the model to stay on the role. The verifier will catch what the prompt misses.
- **"A typical week" is folded into "day to day".** Blogs rarely say how a week is split, so the section came out thin and padded. Its question now sits in "day to day" ("how their time is split, where sources say"), and the section comes back when interviews give real time splits. The `RoleRealityReport` contract keeps the field. Four model calls per report now, not five.
- **Training providers and papers are not practitioners.** CloudThat, Big Blue Data Academy and aiengineeringfromscratch.com sell courses, and the draft itself called one "a training provider's blog". They join the excluded domains, as course sellers did in ADR 0012. So does arxiv.org: a paper is research, not an account of the work. Re-running `make index-evidence` removes their passages. This makes the practitioner evidence thinner, which is the honest picture: interviews and forums are what fill it.
- **Reading the draft.** A source cited through two of its passages now gets one number (`[1][2]`, not `[1][2][1]`). "What employers ask for" lists the top 15 skills one per line with their interval (ties with the 15th included) and the rest on one line per band.

The dropped "30% of the job" claim was a correct drop: the article does say it, but the model didn't quote the sentence with the number.
