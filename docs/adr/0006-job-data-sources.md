# 0006. Job data: company job boards for depth, Adzuna for breadth

- Status: accepted
- Date: 2026-10-31

## Context

Skill statistics ("most GenAI Engineer roles ask for RAG") need the full text of each posting. The plan named the Adzuna API as the main posting source, but its free search API returns only a ~500-character snippet of each description ([source](https://jaymountconsulting.com/data-sources/adzuna-job-search-api)). Fetching the full ad from the employer's site via Adzuna's redirect would breach Adzuna's terms, which require all queries to go through Adzuna.

Many companies publish their openings through public job-board APIs (Greenhouse, Lever, Ashby) that power their own careers pages. These return the full posting text without a key. On 2026-10-31, 25 boards in `data/sources/job_boards.yaml` returned about 5,000 postings, of which 114 were UK AI roles across 21 employers.

## Decision

Two posting sources, each used for what it does well:

| Source | Text | Used for |
| --- | --- | --- |
| Company job boards (Greenhouse, Lever, Ashby) | Full | Skill, tool and responsibility statistics |
| Adzuna (`title_only` search per role alias, last 60 days) | ~500-character snippet, stored with `is_full_text = false` | UK demand: volume, salaries (employer-stated only), locations, employers |

Rules that follow from this:

- A snippet never counts as evidence that a skill is absent, because most of the text is missing.
- Adzuna is credited wherever its data is shown, as its licence requires.
- Every source row records a licence note and links back to the original posting.
- Web evidence (blogs, docs, forums) comes from Firecrawl search, excluding sites whose terms forbid scraping (LinkedIn, Glassdoor, Indeed and other job boards).

## Consequences

- **Bias:** board companies lean towards AI-native firms and scale-ups. Reports must say "based on N postings from M employers" and name the source mix, and Adzuna counts show how much of the wider market that sample covers.
- **Title pre-filter misses vague titles.** Board postings are kept only if the title could be the role (for example "LLM", "GenAI", "AI engineer"), so generic titles such as "Member of Technical Staff" are missed. The classifier in M1 part 2 makes the precise call on what is kept.
- **Coverage grows by adding boards**, a one-line change per company.

## Alternatives considered

- **Adzuna snippets only:** too little text for reliable extraction.
- **Scraping job aggregators (Indeed, LinkedIn):** forbidden by their terms.
- **Paid job-data APIs** (for example TheirStack): good coverage, but cost money; worth revisiting if FirstWeek becomes a startup.

## Update, 2026-10-31: the first live run

The first live research run (GenAI Engineer) counted only 5 of 63 candidate postings as the role. Most candidates were generic Machine Learning Engineer jobs (self-driving, recommendations, hardware), which the classifier rightly rejected. The UK employers that use the title "GenAI Engineer" are mostly banks, consultancies and large enterprises, and we see those only as Adzuna snippets.

- **Boards widened from 25 to 80** by probing 164 UK-relevant employers on Greenhouse, Lever and Ashby. On the same day's data, GenAI Engineer candidates rose from 64 to 86, and candidates with GenAI-type titles from about 17 to 32.
- **Checked and not added:** SmartRecruiters and Recruitee (a handful of UK roles, none AI); Workable (rate-limited every request from our environment, so unverified); Greenhouse's EU-hosted boards (served by the same API, nothing extra found).
- **Still open:** sample sizes stay small for any single day's UK postings. The levers are (a) collecting daily and keeping a rolling window, (b) using international postings for "what the work is" while keeping pay and demand UK-only, and (c) Workday career sites, which many UK enterprises use but which offer no official public API.
