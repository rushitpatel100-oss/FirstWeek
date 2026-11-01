"""Command line for simulation design.

python -m firstweek_simulation blueprint --role "GenAI Engineer"
"""

import argparse
import asyncio
import sys

from firstweek_core.config import get_settings
from firstweek_research.roles import load_roles, resolve_role
from firstweek_simulation.blueprint import (
    BlueprintError,
    design_blueprint,
    load_findings,
    store_blueprint,
    to_text,
)


def _slug(title: str) -> str:
    result = resolve_role(title)
    if result.slug:
        return result.slug
    print(f"'{title}' does not match a known role.")
    for s in result.suggestions:
        print(f"  Did you mean {load_roles()[s.slug].name}?")
    sys.exit(1)


def _blueprint(slug: str, budget: float, *, store: bool) -> None:
    from firstweek_core.llm import LLMGateway
    from firstweek_core.llm.recorder import record_to_db

    settings = get_settings()
    if settings.anthropic_api_key is None:
        print("Set ANTHROPIC_API_KEY in .env first: the blueprint is designed by Claude.")
        sys.exit(1)
    gateway = LLMGateway(settings=settings, recorder=record_to_db)
    try:
        findings = load_findings(slug)
        designed = asyncio.run(design_blueprint(gateway, slug, findings, budget_usd=budget))
    except BlueprintError as exc:
        print(exc)
        sys.exit(1)
    finally:
        gateway.flush()
    print(to_text(designed))
    if store:
        print(f"\nStored as draft blueprint {store_blueprint(findings, designed)}.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="firstweek_simulation")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("blueprint", help="Design a draft project blueprint for a role")
    p.add_argument("--role", required=True)
    p.add_argument("--budget", type=float, default=1.0, help="Spend limit in USD")
    p.add_argument("--no-store", action="store_true", help="Print only; do not save a draft")
    args = parser.parse_args()
    _blueprint(_slug(args.role), args.budget, store=not args.no_store)


if __name__ == "__main__":
    main()
