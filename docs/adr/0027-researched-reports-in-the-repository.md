# ADR 0027: Researched reports kept in the repository

## Context
A Role Reality Report from the pipeline (ADRs 0013 to 0015) needs paid model calls (classifier,
extractor, writer), a free verifier quota, and a person to review 50 spot-checks before it is
published. The API serves only published reports, so on a fresh machine the three golden roles had
no report at all. The owner wants the reports to work with no money and no keys, and does not need
them regenerated on every run.

## Decision
The three golden roles get a report researched once, in one session, and kept as files in
`services/research/src/firstweek_research/data/static_reports/`. `make seed-reports` stores them as
published; nothing calls a model at run time.

- **Postings.** On 2026-11-07 every open posting on 119 public job boards (Greenhouse, Lever, Ashby;
  39 boards added to `job_boards.yaml` that day) was fetched, free, with the existing collector. UK
  postings whose title passed the shared AI title filter (364) were read by hand against each role
  definition; 32 per role fit (from 22 employers for GenAI Engineer, 26 for Agentic AI Engineer, 23 for AI Software Engineer). Vendor delivery roles (forward-deployed,
  Sierra and Decagon agent engineers) and people managers were left out, as the definitions say.
  `<slug>.sample.json` lists each one: employer, board, title, link, date and the skills it names.
- **Numbers by code.** `keyword_skills.py` finds taxonomy names in a posting's text: whole words,
  acronyms and product names with their case, ambiguous names left out ('search', 'cloud', 'CV'),
  an AI vendor's own name never counted in its own postings. Shares and 95% Wilson intervals come
  from the sample through the same `_skill_stats` and `asked_for` the pipeline uses. This counts
  mentions, as `SkillStat` documents; it is coarser than quote-verified extraction.
- **Claims with exact quotes.** Responsibilities quote postings in the sample; day-to-day, a typical
  week and the hard parts quote practitioner writing (engineering blogs and first-person accounts,
  fetched directly). A quote counts only if code finds it word for word in the page text (curly
  quotes, dashes and spacing aside). Confidence uses the pipeline's formula (tier weight, age,
  independent sources, three strong sources for certainty) with every cited source supporting.
  Two blogs give Medium; three employers' postings give High.
- **Honest provenance.** `ReportProvenance.method = "researched"`, cost 0. The web page says the
  postings were open when checked and that quotes were checked by code, not that a model verified
  each claim or that a person reviewed 50 spot-checks.
- **Staying true.** `make check-reports` fetches every source again: posting quotes from the
  company's board, blog quotes from the page. A closed posting is reported as closed, a vanished
  quote as missing (exit 1). On 2026-11-07 all 132 quotes were found.

## Consequences
The reports work on any machine after `make seed-reports`, with no key. They are a snapshot: the
numbers describe postings open on 7 November 2026, and the sample (32 per role) gives wide
intervals, which the page shows. The pipeline still exists for fresh, larger samples; a pipeline
report published later is newer and wins. Seeding twice changes nothing, and seeding after pipeline
statistics adds a new statistics version rather than touching them. No practitioner interviews yet,
so "a typical week" rests on blogs only.
