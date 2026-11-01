"""Research commands.

python -m firstweek_research resolve "Senior LLM Engineer"
python -m firstweek_research collect --role "GenAI Engineer"
python -m firstweek_research research --role "GenAI Engineer"
python -m firstweek_research review-skills
python -m firstweek_research review-matches --role "GenAI Engineer"
python -m firstweek_research eval-classifier [--repeats 2]
python -m firstweek_research eval-extraction
python -m firstweek_research index-evidence
python -m firstweek_research search "how is LLM output evaluated" [--role "GenAI Engineer"]
python -m firstweek_research report --role "GenAI Engineer" [--out report.md]
"""

import argparse
import asyncio
import sys
import textwrap
from typing import TYPE_CHECKING

from firstweek_core.config import get_settings
from firstweek_research.collect import CollectSummary, run_collect
from firstweek_research.research import ResearchResult, run_research
from firstweek_research.roles import load_roles, resolve_role

if TYPE_CHECKING:
    from firstweek_core.llm import LLMGateway


def _resolve_or_exit(title: str) -> str:
    result = resolve_role(title)
    if result.slug:
        how = "exact alias" if result.method == "exact" else f"fuzzy, score {result.score:.0f}"
        print(f"'{title}' -> {load_roles()[result.slug].name} ({how})")
        return result.slug
    print(f"'{title}' does not match a known role.")
    for s in result.suggestions:
        name = load_roles()[s.slug].name
        print(f"  Did you mean {name}? (matched '{s.matched_alias}', {s.score:.0f})")
    print("New roles are researched on demand from M1's second part onwards.")
    sys.exit(1)


def _progress(message: str) -> None:
    print(message, flush=True)


def _print_summary(s: CollectSummary) -> None:
    print(f"\nCollection for {s.role} ({s.country})\n")
    print(f"  {'source':<12}{'fetched':>9}{'kept':>7}{'new':>7}{'updated':>9}{'same':>7}")
    for name, st in sorted(s.providers.items()):
        print(f"  {name:<12}{st.fetched:>9}{st.kept:>7}{st.new:>7}{st.updated:>9}{st.unchanged:>7}")
    print(f"\n  Duplicate check: {s.duplicates} duplicates across {s.duplicate_groups} unique jobs")
    if s.top_companies:
        print("  Top employers this run: " + ", ".join(f"{c} ({n})" for c, n in s.top_companies))
    for name, reason in s.skipped.items():
        print(f"  Skipped {name}: {reason}")
    for name, error in s.errors.items():
        print(f"  Error {name}: {error}")
    print('\n  "fetched" = everything the source returned; "kept" = in the country, a matching')
    print("  title and real content. Adzuna rows are ~500-character snippets.")


def _print_research(r: ResearchResult) -> None:
    if r.collect:
        _print_summary(r.collect)
    print(f"\nResearch for {r.role}")
    print(f"  Classified {r.classified} new postings; {r.matched} judged to be the role")
    print(f"  Extracted {r.extracted} new postings; model cost this run ${r.cost_usd:.4f}")
    for name, error in list(r.failures.items())[:5]:
        print(f"  Failed {name}: {error}")
    s = r.stats
    if s is None or s.sample_size == 0:
        print("\n  Not enough evidence yet: no full-text postings were judged to be this role.")
        return
    start, end = s.date_range or ("?", "?")
    print(f"\n  Sample: {s.sample_size} unique postings, {s.employers} employers, {start} to {end}")
    if s.repeat_postings_merged:
        repeats = s.repeat_postings_merged
        print(f"  ({repeats} repeat postings of the same employer and title counted once)")
    print(f"  Sources: {s.sources}; Adzuna snippets with this title: {s.demand_snippets}")
    print(f"  Seniority: {s.seniority}")
    for sal in s.salary:
        print(
            f"  Salary ({sal.currency}, {sal.postings} postings): "
            f"median {sal.median_min:,.0f} to {sal.median_max:,.0f}"
        )
    for title, rows in (("Skills", s.skills), ("Tools", s.tools)):
        print(f"\n  {title} (share of postings, 95% interval)")
        for row in rows[:12]:
            bar = "#" * round(row.share * 20)
            print(
                f"    {row.label:<30}{row.share:>5.0%}  "
                f"[{row.ci_low:.0%} to {row.ci_high:.0%}]  {bar}"
            )
    print(f"\n  Quality: {s.unverified_items_dropped} extracted items dropped because their quote")
    print(f"  was not in the posting; {s.unmapped_terms} terms await review (make review-skills).")
    if r.version:
        print(f"  Saved as draft version {r.version} for review.")


UNSURE_BELOW = 0.65


def _print_matches(slug: str, country: str, show_urls: bool) -> None:
    import textwrap

    from firstweek_research.extract import CLASSIFIER_VERSION
    from firstweek_research.research import match_decisions
    from firstweek_research.stats import MATCH_CONFIDENCE

    rows = match_decisions(slug, country)
    groups = [
        ("Counted in the statistics", [r for r in rows if r.counted]),
        ("Not counted", [r for r in rows if r.is_match is not None and not r.counted]),
        ("Not classified yet (re-run make research)", [r for r in rows if r.is_match is None]),
    ]
    pad = " " * 12
    name = load_roles()[slug].name
    print(f"Classifier decisions for {name} ({country}), {CLASSIFIER_VERSION}")
    print(f"A posting counts if judged the role with confidence {MATCH_CONFIDENCE} or more.")
    unsure = sum(1 for r in rows if r.confidence is not None and r.confidence < UNSURE_BELOW)
    if unsure:
        print(f'"?" marks {unsure} decisions below {UNSURE_BELOW} confidence: worth a human look.')
    for heading, items in groups:
        if not items:
            continue
        print(f"\n{heading} ({len(items)})")
        for r in items:
            verdict = "" if r.is_match is None else ("yes" if r.is_match else "no")
            if r.confidence is not None and r.confidence < UNSURE_BELOW:
                verdict += "?"
            conf = "" if r.confidence is None else f"{r.confidence:.2f}"
            print(f"  {verdict:<4} {conf:<4}  {r.company or '?'} | {r.title}")
            if r.reason:
                print(textwrap.fill(r.reason, 96, initial_indent=pad, subsequent_indent=pad))
            if show_urls and r.url:
                print(pad + r.url)


def _pct(value: float | None) -> str:
    return "  n/a" if value is None else f"{value:>5.0%}"


def _print_evaluation(repeats: int, budget: float, show: int) -> None:
    import textwrap

    from firstweek_research.evaluate import evaluate, stability

    result = evaluate()
    labels = result.labels
    print(
        f"Classifier {result.classifier_version} against {len(labels.postings)} hand-labelled "
        f"postings (labelled {labels.labelled_on}; {result.checked_labels} of "
        f"{result.total_labels} labels checked by a person)."
    )
    if result.checked_labels < result.total_labels / 2:
        print("Most labels are unchecked drafts: read the scores as agreement with a second")
        print("model, not as accuracy, until the disagreements below have been reviewed.")
    print(
        f"\n  {'role':<22}{'scored':>7}{'agree':>7}{'prec.':>7}{'recall':>7}{'F1':>7}"
        f"{'unsure':>8}{'missing':>9}{'by title':>10}"
    )
    for r in result.roles:
        print(
            f"  {r.role:<22}{r.scored:>7}{_pct(r.agreement):>7}{_pct(r.precision):>7}"
            f"{_pct(r.recall):>7}{_pct(r.f1):>7}{r.unsure:>8}{r.missing:>9}"
            f"{r.by_title_filter:>10}"
        )
    print('\n  "missing": labelled, but this database cannot say (not collected, a duplicate,')
    print('  outside the 6-month window, or not classified yet). "by title": scored postings')
    print('  the title filter rejected before the model saw them; they count as "not counted".')

    pad = " " * 10
    for r in result.roles:
        if not r.disagreements:
            continue
        print(f"\n{r.role}: {len(r.disagreements)} disagreements (model vs label)")
        for d in r.disagreements[:show]:
            model = "counted" if d.counted else "not counted"
            conf = "title filter" if d.confidence is None else f"{d.confidence:.2f}"
            mark = "" if d.checked else " (label unchecked)"
            print(f"  model {model} ({conf}), label {d.label}{mark}")
            print(f"    {d.company} | {d.title}")
            for who, why in (("model", d.reason), ("label", d.note)):
                print(textwrap.fill(f"{who}: {why}", 96, initial_indent=pad, subsequent_indent=pad))
            print(pad + d.url)
        if len(r.disagreements) > show:
            print(f"  ...and {len(r.disagreements) - show} more (use --show)")

    if repeats:
        from firstweek_core.llm import LLMGateway
        from firstweek_core.llm.recorder import record_to_db

        settings = get_settings()
        if settings.anthropic_api_key is None:
            print("\nStability check skipped: set ANTHROPIC_API_KEY in .env.")
            return
        gateway = LLMGateway(settings=settings, recorder=record_to_db)
        print(f"\nStability: asking the classifier {repeats} more time(s) per posting...")
        runs = asyncio.run(stability(gateway, repeats, budget_usd=budget, progress=_progress))
        gateway.flush()
        for st in runs:
            print(
                f"  {st.role:<22} {len(st.flipped)} of {st.postings} postings changed answer "
                f"({_pct(st.flip_rate).strip()})"
                + (f"; {st.failures} skipped after errors" if st.failures else "")
            )
            for company, title, verdicts in st.flipped[:show]:
                answers = ", ".join("counted" if v else "not" for v in verdicts)
                print(f"      {company} | {title}: {answers}")


def _print_extraction_eval(show: int) -> None:
    from firstweek_research.evaluate_extraction import (
        PRECISION_TARGET,
        RECALL_TARGET,
        evaluate_extraction,
    )

    result = evaluate_extraction()
    labels = result.labels
    print(
        f"Extractor {result.extractor_version} against {len(labels.postings)} hand-labelled "
        f"postings (labelled {labels.labelled_on}; {result.checked} checked by a person)."
    )
    if result.checked < len(labels.postings) / 2:
        print("Most labels are unchecked drafts: read these as agreement with a second model.")
    print(f"Scored {len(result.postings)}; {len(result.missing)} not extracted in this database.")
    if not result.postings:
        print("Nothing to score yet: run make research-now first.")
        return

    def mark(value: float | None, target: float) -> str:
        return "" if value is None else ("  meets target" if value >= target else "  below target")

    print(f"\n  {'':<8}{'found':>7}{'labelled':>10}{'prec.':>8}{'recall':>8}{'F1':>7}")
    for name, kind in (("all", None), ("skills", "skill"), ("tools", "tool")):
        r = result.rates(kind)
        print(
            f"  {name:<8}{r.predicted:>7}{r.gold:>10}{_pct(r.precision):>8}"
            f"{_pct(r.recall):>8}{_pct(r.f1):>7}"
        )
    overall = result.rates()
    p_mark = mark(overall.precision, PRECISION_TARGET)
    r_mark = mark(overall.recall, RECALL_TARGET)
    print(
        f"\n  Targets: precision {PRECISION_TARGET:.0%}{p_mark}; recall {RECALL_TARGET:.0%}{r_mark}"
    )
    correct, scored = result.seniority
    if scored:
        print(f"  Seniority: {correct} of {scored} correct ({correct / scored:.0%})")

    print("\n  Most often missed:  " + ", ".join(f"{s} ({n})" for s, n in result.most_missed()))
    print("  Most often extra:   " + ", ".join(f"{s} ({n})" for s, n in result.most_extra()))
    print(
        "\nWorst-matching postings (missed = labelled but not found; extra = found, not labelled):"
    )
    for p in sorted(result.postings, key=lambda p: p.f1)[:show]:
        level = ""
        if p.seniority_gold and p.seniority_predicted not in p.seniority_gold:
            level = f"; seniority {p.seniority_predicted} (label: {'/'.join(p.seniority_gold)})"
        print(f"  F1 {p.f1:.0%}  {p.company} | {p.title}{level}")
        if p.missed:
            print(f"      missed: {', '.join(sorted(p.missed))}")
        if p.extra:
            print(f"      extra:  {', '.join(sorted(p.extra))}")
        if p.unmapped:
            print(f"      not in taxonomy: {', '.join(p.unmapped[:8])}")


def _print_esco_suggestions(show_linked: bool) -> None:
    from firstweek_research.esco import ESCO_VERSION, suggest
    from firstweek_research.sources.base import make_client
    from firstweek_research.taxonomy import load_taxonomy

    entries = [e for e in load_taxonomy().entries.values() if show_linked or not e.esco_uri]
    print(f"ESCO {ESCO_VERSION} candidates for {len(entries)} taxonomy entries.")
    print('"=" marks an ESCO skill with the same name as the entry. Link only true equivalents:')
    print("write `esco_uri: <uri>` into the entry in ai_skills.yaml; leave AI-specific ones empty.")

    async def run() -> None:
        async with make_client() as client:
            for entry in entries:
                candidates = await suggest(client, entry)
                linked = f"  (linked: {entry.esco_uri})" if entry.esco_uri else ""
                print(f"\n{entry.slug} | {entry.label}{linked}")
                for c in candidates[:5]:
                    mark = "=" if c.same_name_as(entry) else " "
                    print(f"  {mark} {c.uri.rsplit('/', 1)[-1]}  {c.label}")

    asyncio.run(run())


def _print_unmapped(limit: int) -> None:
    from sqlalchemy import func, select

    from firstweek_core.db.models import Extraction
    from firstweek_core.db.session import session_scope

    with session_scope() as session:
        rows = session.execute(
            select(Extraction.raw_text, Extraction.kind, func.count().label("n"))
            .where(Extraction.skill_id.is_(None), Extraction.kind.in_(["skill", "tool"]))
            .group_by(Extraction.raw_text, Extraction.kind)
            .order_by(func.count().desc())
            .limit(limit)
        ).all()
    if not rows:
        print("No unmapped skill or tool labels. The taxonomy covers everything extracted so far.")
        return
    print("Labels not in the taxonomy yet (add them as entries or aliases in ai_skills.yaml):\n")
    for row in rows:
        print(f"  {row.n:>4}  {row.kind:<6} {row.raw_text}")


def _gateway() -> "LLMGateway":
    from firstweek_core.llm import LLMGateway
    from firstweek_core.llm.recorder import record_to_db

    return LLMGateway(settings=get_settings(), recorder=record_to_db)


def _index_evidence() -> None:
    from firstweek_research.passages import index_evidence

    gateway = _gateway()
    s = asyncio.run(index_evidence(gateway, progress=_progress))
    gateway.flush()
    print(
        f"\n{s.sources} sources: {s.indexed} indexed ({s.passages_added:,} passages), "
        f"{s.unchanged} unchanged, {s.sources_removed} removed (no longer evidence)."
    )


def _search(query: str, slug: str | None, country: str, k: int, per_source: int | None) -> None:
    from firstweek_research.retrieve import search

    gateway = _gateway()
    hits = asyncio.run(
        search(gateway, query, role_slug=slug, country=country, k=k, per_source=per_source)
    )
    gateway.flush()
    if not hits:
        print("No passages found. Has `make index-evidence` been run?")
        return
    for i, h in enumerate(hits, 1):
        found = ", ".join(
            f"{how} #{rank}"
            for how, rank in (("meaning", h.vector_rank), ("words", h.keyword_rank))
            if rank is not None
        )
        print(f"\n{i}. [{h.tier}] {h.publisher or ''} | {h.title or h.url}  ({found})")
        print(f"   {h.url}")
        body = h.text if len(h.text) <= 400 else h.text[:400].rsplit(" ", 1)[0] + " ..."
        for line in body.splitlines():
            print(textwrap.fill(line, 96, initial_indent="   ", subsequent_indent="   "))


def preflight_judge(gateway: "LLMGateway") -> str | None:
    """One tiny call to the verifier before the paid draft, so a bad key fails in a second."""
    from firstweek_research.verify import VERIFIER_TIER

    model = gateway.model_for(VERIFIER_TIER)
    try:
        asyncio.run(
            gateway.complete(
                purpose="preflight-judge",
                messages=[{"role": "user", "content": "Reply with the word ok."}],
                tier=VERIFIER_TIER,
                max_tokens=32,
            )
        )
    except Exception as exc:
        return (
            f"The verifier ({model}) did not answer: {str(exc)[:200]}\n"
            "Check GEMINI_API_KEY and MODEL_JUDGE in .env. Nothing was spent on the draft."
        )
    return None


def judge_problem(model: str) -> str | None:
    """Why the verifier can't run, before any money is spent on the draft."""
    if model.startswith("anthropic/"):
        return (
            f"MODEL_JUDGE is {model}, but the verifier must come from another model family "
            "than the writer (Claude). Set MODEL_JUDGE in .env to an OpenAI or Google model."
        )
    settings = get_settings()
    missing = {
        "openai/": ("OPENAI_API_KEY", settings.openai_api_key),
        "gemini/": ("GEMINI_API_KEY", settings.gemini_api_key),
    }
    for prefix, (name, key) in missing.items():
        if model.startswith(prefix) and key is None:
            hint = (
                " (a free key: https://aistudio.google.com/apikey)"
                if name == "GEMINI_API_KEY"
                else ""
            )
            return (
                f"Set {name} in .env{hint}: the verifier ({model}) checks Claude's claims "
                "from another model family. Or use `make report ... verify=no` for a draft."
            )
    return None


def _report(slug: str, budget: float, out: str | None, verify: bool = True) -> None:
    from firstweek_research.report import NoStatisticsError, ReportDraft, draft_report, to_markdown
    from firstweek_research.verify import VERIFIER_TIER, store_report, verify_report

    if get_settings().anthropic_api_key is None:
        print("Set ANTHROPIC_API_KEY in .env first: the report is written by Claude.")
        sys.exit(1)
    gateway = _gateway()
    if verify and (problem := judge_problem(gateway.model_for(VERIFIER_TIER))):
        print(problem)
        sys.exit(1)
    if verify and (problem := preflight_judge(gateway)):
        print(problem)
        gateway.flush()
        sys.exit(1)

    async def run() -> tuple[ReportDraft, BaseException | None]:
        draft = await draft_report(gateway, slug, budget_usd=budget, progress=_progress)
        if not verify:
            return draft, None
        _progress(f"Checking every claim with {gateway.model_for(VERIFIER_TIER)}...")
        try:
            return await verify_report(gateway, draft), None
        except Exception as exc:  # keep the paid-for draft, then report the failure
            return draft, exc

    try:
        draft, failure = asyncio.run(run())
    except NoStatisticsError as exc:
        print(exc)
        sys.exit(1)
    finally:
        gateway.flush()
    text = to_markdown(draft)
    print("\n" + text)
    if out:
        from pathlib import Path

        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
        print(f"Saved to {out}")
    if failure is not None:
        print(f"Verification failed, so nothing was stored: {failure}")
        sys.exit(1)
    if draft.verifier_model is not None:
        print(f"Stored as report {store_report(draft)}.")


def database_unreachable(exc: BaseException) -> str | None:
    """One line instead of a traceback when Postgres isn't running (no credentials shown)."""
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import OperationalError

    if not isinstance(exc, OperationalError) or "connection" not in str(exc.orig).lower():
        return None
    url = make_url(get_settings().database_url)
    return (
        f"Can't reach the database at {url.host}:{url.port or 5432} ({url.database}). "
        "Start it with: docker compose up -d"
    )


def main(argv: list[str] | None = None) -> None:
    try:
        _main(argv)
    except Exception as exc:
        if (message := database_unreachable(exc)) is None:
            raise
        print(message, file=sys.stderr)
        sys.exit(1)


def _main(argv: list[str] | None) -> None:
    parser = argparse.ArgumentParser(prog="firstweek_research")
    sub = parser.add_subparsers(dest="command", required=True)

    p_resolve = sub.add_parser("resolve", help="Map a job title to a known role")
    p_resolve.add_argument("title")

    p_collect = sub.add_parser("collect", help="Collect postings and web sources for a role")
    p_collect.add_argument("--role", required=True, help='e.g. "GenAI Engineer"')
    p_collect.add_argument("--country", default="GB")
    p_collect.add_argument("--no-boards", action="store_true", help="Skip company job boards")
    p_collect.add_argument("--no-adzuna", action="store_true", help="Skip Adzuna")
    p_collect.add_argument("--no-web", action="store_true", help="Skip blogs and forums")
    p_collect.add_argument("--adzuna-pages", type=int, default=2, help="50 results per page")

    p_research = sub.add_parser("research", help="Collect, classify, extract and summarise a role")
    p_research.add_argument("--role", required=True)
    p_research.add_argument("--country", default="GB")
    p_research.add_argument("--no-collect", action="store_true", help="Use stored postings only")
    p_research.add_argument("--budget", type=float, default=5.0, help="Model spend cap in USD")

    p_review = sub.add_parser("review-skills", help="List extracted labels not in the taxonomy")
    p_review.add_argument("--limit", type=int, default=40)

    p_matches = sub.add_parser(
        "review-matches", help="Show what the classifier decided for each posting, and why"
    )
    p_matches.add_argument("--role", required=True)
    p_matches.add_argument("--country", default="GB")
    p_matches.add_argument("--urls", action="store_true", help="Also print each posting's link")

    p_esco = sub.add_parser("esco-suggest", help="Suggest ESCO links for taxonomy entries")
    p_esco.add_argument("--all", action="store_true", help="Include entries already linked")

    p_eval = sub.add_parser("eval-classifier", help="Score the classifier against hand labels")
    p_eval.add_argument(
        "--repeats", type=int, default=0, help="Re-ask N times to measure stability (costs money)"
    )
    p_eval.add_argument("--budget", type=float, default=1.0, help="Spend cap for --repeats, USD")
    p_eval.add_argument("--show", type=int, default=15, help="Disagreements to list per role")

    p_xeval = sub.add_parser("eval-extraction", help="Score extraction against hand labels")
    p_xeval.add_argument("--show", type=int, default=10, help="Worst postings to list")

    sub.add_parser("index-evidence", help="Split sources into passages and embed them")

    p_search = sub.add_parser("search", help="Find evidence passages by meaning and keywords")
    p_search.add_argument("query")
    p_search.add_argument("--role", help="Only evidence for this role (and all web sources)")
    p_search.add_argument("--country", default="GB")
    p_search.add_argument("-k", type=int, default=8, help="Passages to show")
    p_search.add_argument(
        "--per-source", type=int, default=2, help="Most passages from one source (0: no limit)"
    )

    p_report = sub.add_parser("report", help="Draft a Role Reality Report from the evidence")
    p_report.add_argument("--role", required=True)
    p_report.add_argument("--budget", type=float, default=1.5, help="Model spend cap in USD")
    p_report.add_argument("--out", help="Also save the report as markdown to this file")
    p_report.add_argument(
        "--no-verify", action="store_true", help="Draft only: skip the verifier, store nothing"
    )

    args = parser.parse_args(argv)
    if args.command == "index-evidence":
        _index_evidence()
        return
    if args.command == "search":
        slug = _resolve_or_exit(args.role) if args.role else None
        _search(args.query, slug, args.country.upper(), args.k, args.per_source or None)
        return
    if args.command == "eval-extraction":
        _print_extraction_eval(args.show)
        return
    if args.command == "review-skills":
        _print_unmapped(args.limit)
        return
    if args.command == "esco-suggest":
        _print_esco_suggestions(args.all)
        return
    if args.command == "eval-classifier":
        _print_evaluation(args.repeats, args.budget, args.show)
        return
    slug = _resolve_or_exit(args.title if args.command == "resolve" else args.role)
    if args.command == "report":
        _report(slug, args.budget, args.out, verify=not args.no_verify)
        return
    if args.command == "review-matches":
        _print_matches(slug, args.country.upper(), args.urls)
        return
    if args.command == "research":
        from firstweek_core.llm import LLMGateway
        from firstweek_core.llm.recorder import record_to_db

        settings = get_settings()
        if settings.anthropic_api_key is None:
            print("Set ANTHROPIC_API_KEY in .env first: classification and extraction use Claude.")
            sys.exit(1)
        gateway = LLMGateway(settings=settings, recorder=record_to_db)
        result = asyncio.run(
            run_research(
                slug,
                settings,
                gateway,
                country=args.country.upper(),
                collect=not args.no_collect,
                budget_usd=args.budget,
                progress=_progress,
            )
        )
        gateway.flush()
        _print_research(result)
        return
    if args.command == "collect":
        summary = asyncio.run(
            run_collect(
                slug,
                get_settings(),
                country=args.country.upper(),
                use_boards=not args.no_boards,
                use_adzuna=not args.no_adzuna,
                use_web=not args.no_web,
                adzuna_pages=args.adzuna_pages,
                progress=_progress,
            )
        )
        _print_summary(summary)


if __name__ == "__main__":
    main()
