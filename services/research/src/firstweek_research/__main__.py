"""Research commands.

python -m firstweek_research resolve "Senior LLM Engineer"
python -m firstweek_research collect --role "GenAI Engineer"
"""

import argparse
import asyncio
import sys

from firstweek_core.config import get_settings
from firstweek_research.collect import CollectSummary, run_collect
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

    args = parser.parse_args(argv)
    slug = _resolve_or_exit(args.title if args.command == "resolve" else args.role)
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
