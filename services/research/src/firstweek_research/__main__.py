"""Research commands.

python -m firstweek_research resolve "Senior LLM Engineer"
python -m firstweek_research collect --role "GenAI Engineer"
python -m firstweek_research research --role "GenAI Engineer"
python -m firstweek_research review-skills
"""

import argparse
import asyncio
import sys

from firstweek_core.config import get_settings
from firstweek_research.collect import CollectSummary, run_collect
from firstweek_research.research import ResearchResult, run_research
from firstweek_research.roles import load_roles, resolve_role


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


def main(argv: list[str] | None = None) -> None:
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

    args = parser.parse_args(argv)
    if args.command == "review-skills":
        _print_unmapped(args.limit)
        return
    slug = _resolve_or_exit(args.title if args.command == "resolve" else args.role)
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
            )
        )
        _print_summary(summary)


if __name__ == "__main__":
    main()
