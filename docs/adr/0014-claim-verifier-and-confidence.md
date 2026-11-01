# 0014. The claim verifier and confidence scores

- Status: accepted
- Date: 2026-10-31

## Context

The report writer (ADR 0013) checks its own output mechanically: real passages, word-for-word quotes, no frequency words it can't back, numbers only from quotes. It can't tell whether a real quote actually supports the sentence built on it. The plan's next steps close that gap. A separate model checks every sentence against its cited passages and labels it supported, partly supported or unsupported. Then each claim gets a confidence score: c = min(1, Σw / 3) × r × a, with tier weights 1.0 (postings), 0.8 (blogs) and 0.5 (forums), r for recency (1.0 under 12 months, 0.7 older) and a for agreement. High is 0.75 or more, Medium 0.5 to 0.75, Low under 0.5.

## Decision

**A model from another family checks every claim.** The verifier uses the gateway's judge tier (`MODEL_JUDGE`, Gemini 3.8 Flash on Google's free tier by default), so Claude's sentences are never graded by Claude. There is one call per section: it gets every claim, labelled C1, C2..., with the full text of each passage the claim cites, not just the quote. For each cited passage it says supports, partly, does not support or contradicts. For the whole claim it says supported, partial or unsupported, with a one-sentence reason. The prompt is `verify-claims.v1`. It is strict about attribution: a posting says what an employer asks for, a training provider isn't a practitioner, and one source can't back "several".

**Code decides what stays.** A claim is removed when:

- the verifier calls it unsupported;
- no cited passage supports it, whatever the claim-level label says;
- only forum posts support it (the plan: forums are never the only source).

Removed claims are listed with the reason, next to the ones the writer's checks dropped. A claim the verifier returns no verdict for counts as unsupported (fail closed).

**Confidence follows the plan's formula, with these readings of it:**

- *Independent sources.* Two adverts from one employer, or two pages from one site, are one source (grouped by tier and publisher). A source counts its best verdict.
- *Credit.* "supports" adds the tier weight; "partly" adds half of it.
- *Recency per source.* Each source's weight is multiplied by its own r, inside the sum. This equals the plan's r × Σw when all sources share an age, and doesn't let one old source drag down three new ones.
- *Dates.* A posting counts from when it was last seen live: an advert first published two years ago and still open is what the employer asks for today. A web page counts from its publication date. Pages have no date yet (the collector doesn't record one), so they count as old (0.7) for now: we can't call evidence current without knowing when it was written.
- *Agreement* is the share of independent sources that support rather than contradict.
- *Partly supported* claims are capped at 0.7, so they never show as High.

**Stored.** `make report` now writes, verifies and stores. The report goes in `role_reports` as the `RoleRealityReport` contract, against the statistics version it was written from. A new `provenance` block records the writer and verifier models and prompts, the cost, and every removed claim with its reason. Each kept claim gets a `report_claims` row with its confidence, label and passage ids. The admin review and publish flow (next) works from these rows. If the verifier fails, the draft is still saved as markdown and nothing is stored. `verify=no` gives an unverified draft.

## Consequences

- A single-source claim is Low by design: one recent posting scores 0.33 and one undated blog 0.19. Medium needs two independent sources; High needs about three. The first real report will show many Low claims. That is the formula doing its job, not a bug, and it is the plan's case for widening evidence and for interviews.
- Practitioner claims are held down until pages carry publication dates. Recording `publishedTime` from page metadata when collecting is a small follow-up.
- The verifier needs a free Gemini key (https://aistudio.google.com/apikey, no card), or another non-Anthropic `MODEL_JUDGE` with its key. `make report` refuses a Claude judge and says which key is missing before anything is spent.
- **Free means rate-limited, and Google may use free-tier prompts to improve its products.** Our prompts hold only public job postings and web pages, so that is acceptable here; it would not be for private data. The four section checks run at once and LiteLLM retries a refused call twice; if a free quota runs out, the draft is kept and nothing is stored. Gemini Flash is a smaller model than GPT-6 Sol, so its strictness is unmeasured: the 50-claim spot-check below matters more. Swap `MODEL_JUDGE` back to a paid model when the product is deployed.
- Free-tier Gemini models are priced at zero in `llm/pricing.py`. If billing is turned on for the key, replace them with the paid prices.
- The plan says interviews "validate, never generate", but the writer may cite them (ADR 0013), and `TIER_WEIGHTS` gives them 1.0. To settle when the first interviews arrive.
- The verifier's own accuracy is unmeasured. The plan's check is a spot-check of 50 verified claims by hand, which should come before reports are published.
