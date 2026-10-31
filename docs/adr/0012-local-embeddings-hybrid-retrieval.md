# 0012. Free local embeddings and hybrid search for evidence passages

- Status: accepted
- Date: 2026-10-31

## Context

M2 turns the Role Reality Report from statistics into cited prose. Every claim has to point at a passage of collected evidence (a posting, an article, a forum thread or, later, an interview). That needs three things: sources cut into passages short enough to cite, a way to find the passages that support a sentence even when they use other words, and an index that stays in step with the daily collection.

The schema planned for this from M0: `evidence_passages` with a 1536-wide vector column, sized for OpenAI's `text-embedding-3-small`. Nothing had been written to it yet.

Options for the embedding model:

- **Hosted (OpenAI `text-embedding-3-small`, $0.02 per million tokens).** Good quality and cheap, but it needs a second provider key, sends every passage out, and turns every search into a network call and a budget entry.
- **Free open-source model run locally (`BAAI/bge-small-en-v1.5`, 384 dimensions, ~65 MB).** No key and no cost, works offline, and is deterministic. Quality on English retrieval benchmarks is close to the small hosted models. It costs CPU instead.

Rushit chose the free model (2026-10-31).

## Decision

**Embeddings.** `MODEL_EMBEDDING=local/BAAI/bge-small-en-v1.5`, run through `LLMGateway.embed` like every other model call (ground rule 1). `local/<name>` runs the model in-process with fastembed (ONNX Runtime, no PyTorch); any other value is a LiteLLM embedding model, priced and budgeted as usual. Every batch is recorded in `llm_calls` (tier `embedding`, cost 0 when local). Search queries start with BGE's retrieval instruction ("Represent this sentence for searching relevant passages: "), as the model card recommends for short queries; fastembed doesn't add it. Passages are embedded as they are. The vector columns are now 384 wide; the migration clears the never-used old vectors rather than converting them, and a run with a model of another width stops with the fix in the message.

**Passages.** `firstweek_research.passages` cuts each source at paragraph and bullet boundaries into passages of at most 900 characters (about 200 tokens: short enough to cite precisely, well inside the model's 512-token limit). Long paragraphs split at bullets, then sentences, and only as a last resort mid-word. Each passage starts with the heading of its section ("Requirements: ..."), because a bullet such as "3+ years" means nothing without it. Postings contribute their role text, so company boilerplate is never evidence; blogs, forums and interviews contribute their cleaned content.

**What is indexed.** Full-text, unique postings seen inside the 6-month window (ADR 0008), plus every blog, forum and interview source. A posting that ages out or turns out to be a duplicate loses its passages, so the index always matches what a report may cite.

**Incremental.** Each passage stores a key (a hash of its source text plus the chunking rules) and the embedding model. A run skips every source whose key and model are unchanged, re-cuts the rest, and saves after each batch of about 64 passages, so an interrupted run keeps its work. Changing `CHUNKER_VERSION` or the model rebuilds everything.

**Hybrid search.** `firstweek_research.retrieve.search` ranks passages two ways and fuses the rankings with reciprocal rank fusion (score = Σ 1/(60 + rank)):

- *Meaning*: cosine distance on the HNSW vector index. Finds "how do they test the quality of model answers" in a passage about "evaluation insights" and "model performance".
- *Words*: Postgres full-text search on a generated `tsvector` column with a GIN index. Catches exact names that embeddings blur. On the real postings, the passage nearest in meaning to "LangGraph" doesn't contain the word; the top five fused results all do.

Question words are OR-ed (a passage need not contain every word of a question), and "quoted phrases" still match as phrases. RRF needs no tuning between two very different score scales. The vector index filters after it searches, so each query examines 400 neighbours instead of pgvector's default 40, which keeps a role-scoped search from coming back short.

**Role scope.** With a role, search sees only postings counted in that role's statistics (judged the role under its current definition, confidence ≥ 0.5, inside the window), plus all web and interview sources. Report sentences about a role can't cite a posting that isn't in its sample.

**Pipeline.** `DailyResearchWorkflow` ends with one `index_evidence` activity after all roles, whatever happened to them; a failure there is reported without losing the research. The worker keeps the downloaded model in a Docker volume. By hand: `make index-evidence` and `make search q="..." role="..."`.

## Consequences

- Indexing and search cost nothing and need no key, so tests, CI and the daily run never spend money on them.
- Speed depends on the CPU: about 10 passages a second on a 2-vCPU cloud workspace (the first full index of 247 postings, 1,644 passages, took under 5 minutes there), faster on a laptop. A daily run only embeds what changed.
- The first run downloads the model (~65 MB) from Hugging Face; offline machines need it pre-cached.
- Switching to a hosted or larger model is a settings change plus a migration for the vector width; the index then rebuilds itself.
- The keyword side is English-only (`to_tsvector('english', ...)`), matching the UK-first scope. Other languages will need their own configuration.

## Addendum (2026-10-31, after the first search on Rushit's data)

The first real search, for "LangGraph" across postings and web pages, showed three problems, all now fixed:

- **Markdown noise.** Web pages arrive as markdown. One Udacity passage matched "LangGraph" only through an image's file name, and a dev.to passage was nothing but a link written out twice. Passages now hold only the words a reader sees: images and bare URLs go, links become their text, and emphasis markers and HTML tags are dropped. Passages under 8 words ("Location: #LI-Remote") are not indexed. `CHUNKER_VERSION` 2 re-cuts every source.
- **One source crowding out the rest.** Four of the top eight results came from one Udacity page. Search now returns at most 2 passages per source by default (`per_source`, `--per-source 0` for no limit), because a claim is better supported by several sources than by several paragraphs of one.
- **Course sellers aren't evidence.** A course seller's "what does an X engineer do" page is written to sell a course; the same Udacity page listed an "AI Trading Strategies" Nanodegree. Udacity, Coursera, Udemy, edX and 14 other course and bootcamp sites join the excluded domains. Collection skips them, and pages already stored drop out of the index on its next run.
