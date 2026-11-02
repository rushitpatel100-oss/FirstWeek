"""Command line for simulation design.

python -m firstweek_simulation blueprint --role "GenAI Engineer"
"""

import argparse
import asyncio
import sys

from firstweek_core.config import get_settings
from firstweek_research.__main__ import database_unreachable
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
    _need_key(settings.simulation_tier)
    gateway = LLMGateway(settings=settings, recorder=record_to_db)
    try:
        findings = load_findings(slug)
        designed = asyncio.run(
            design_blueprint(
                gateway, slug, findings, tier=get_settings().simulation_tier, budget_usd=budget
            )
        )
    except BlueprintError as exc:
        print(exc)
        sys.exit(1)
    finally:
        gateway.flush()
    print(to_text(designed))
    if store:
        print(f"\nStored as draft blueprint {store_blueprint(findings, designed)}.")


def _artifacts(slug: str, budget: float, seed: int) -> None:
    from pathlib import Path

    from firstweek_core.llm import LLMGateway
    from firstweek_core.llm.recorder import record_to_db
    from firstweek_core.sandbox import get_runner
    from firstweek_simulation.artifacts import (
        build_artifacts,
        latest_draft,
        save_artifacts,
        to_text,
    )

    settings = get_settings()
    _need_key(settings.simulation_tier)
    gateway = LLMGateway(settings=settings, recorder=record_to_db)
    try:
        blueprint_id, blueprint = latest_draft(slug)
        built = asyncio.run(
            build_artifacts(
                gateway,
                get_runner(settings),
                blueprint,
                seed=seed,
                tier=settings.simulation_tier,
                budget_usd=budget,
            )
        )
    except BlueprintError as exc:
        print(exc)
        sys.exit(1)
    finally:
        gateway.flush()
    folder = save_artifacts(blueprint_id, built, Path(settings.artifacts_dir))
    print(to_text(built, folder))
    sys.exit(0 if built.ok else 1)


def _need_key(tier: str) -> None:
    settings = get_settings()
    if tier == "judge" and not settings.has_judge_key:
        print(
            "Set GEMINI_API_KEY (free: https://aistudio.google.com/apikey) or GROQ_API_KEY "
            "(free: https://console.groq.com) in .env or the environment, or use "
            "SIMULATION_TIER=mid with ANTHROPIC_API_KEY."
        )
        sys.exit(1)
    if tier != "judge" and settings.anthropic_api_key is None:
        print("Set ANTHROPIC_API_KEY in .env first.")
        sys.exit(1)


def _autopilot(args: argparse.Namespace) -> None:
    from pathlib import Path

    from firstweek_core.llm import LLMGateway
    from firstweek_core.sandbox import get_runner
    from firstweek_simulation.pipeline import (
        findings_from_file,
        report_text,
        run_pipeline,
        store_result,
        write_output,
    )

    settings = get_settings()
    tier = args.tier or settings.simulation_tier
    _need_key(tier)
    from_file = args.report_file is not None
    if from_file:
        slug, findings = findings_from_file(Path(args.report_file))
        gateway = LLMGateway(settings=settings)
    else:
        from firstweek_core.llm.recorder import record_to_db

        slug = _slug(args.role)
        findings = load_findings(slug)
        gateway = LLMGateway(settings=settings, recorder=record_to_db)
    try:
        result = asyncio.run(
            run_pipeline(
                gateway, get_runner(settings), slug, findings,
                tier=tier, attempts=args.attempts, seed=args.seed,
                budget_usd=args.budget, progress=lambda m: print(m, flush=True),
            )
        )  # fmt: skip
    except BlueprintError as exc:
        print(exc)
        sys.exit(1)
    finally:
        gateway.flush()
    out = Path(args.out or f"var/autopilot/{slug}")
    write_output(out, result)
    if not from_file:
        print("Stored as blueprint", store_result(findings, result, Path(settings.artifacts_dir)))
    print()
    print(report_text(result))
    print(f"\nFiles: {out}")
    sys.exit(0 if result.approved else 1)


def _seed_demo(slug: str) -> None:
    from pathlib import Path

    from firstweek_simulation.demo_project import seed_demo

    try:
        new_id = seed_demo(slug, Path(get_settings().artifacts_dir))
    except BlueprintError as exc:
        print(exc)
        sys.exit(1)
    print(f"Stored the hand-written demo project as approved blueprint {new_id}.")
    print(f"Open it at http://localhost:3000/roles/{slug}/practice (make web, make up).")


def _export_report(slug: str, out: str) -> None:
    import json
    from pathlib import Path

    from firstweek_simulation.pipeline import export_report

    try:
        data = export_report(slug)
    except BlueprintError as exc:
        print(exc)
        sys.exit(1)
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1))
    print(f"Wrote {path}")


def main() -> None:
    try:
        _main()
    except Exception as exc:
        if (message := database_unreachable(exc)) is None:
            raise
        print(message, file=sys.stderr)
        sys.exit(1)


def _main() -> None:
    parser = argparse.ArgumentParser(prog="firstweek_simulation")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("blueprint", help="Design a draft project blueprint for a role")
    p.add_argument("--role", required=True)
    p.add_argument("--budget", type=float, default=1.0, help="Spend limit in USD")
    p.add_argument("--no-store", action="store_true", help="Print only; do not save a draft")
    pilot = sub.add_parser("autopilot", help="Design, build and gate a project unattended")
    pilot.add_argument("--role", default="")
    pilot.add_argument("--report-file", help="Use an exported report instead of the database")
    pilot.add_argument("--out", help="Folder for the result (default var/autopilot/<slug>)")
    pilot.add_argument("--tier", choices=["judge", "small", "mid", "frontier"])
    pilot.add_argument("--attempts", type=int, default=3)
    pilot.add_argument("--seed", type=int, default=1)
    pilot.add_argument("--budget", type=float, default=1.0)
    d = sub.add_parser("seed-demo", help="Store the hand-written practice project (no model call)")
    d.add_argument("--role", required=True)
    exp = sub.add_parser("export-report", help="Write a stored report to a JSON file")
    exp.add_argument("--role", required=True)
    exp.add_argument("--out", required=True)
    a = sub.add_parser("artifacts", help="Build the starter repo, data and reference solution")
    a.add_argument("--role", required=True)
    a.add_argument("--budget", type=float, default=1.0, help="Spend limit in USD")
    a.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    if args.command == "autopilot":
        if not args.role and not args.report_file:
            print("Give --role or --report-file.")
            sys.exit(1)
        _autopilot(args)
        return
    if args.command == "export-report":
        _export_report(_slug(args.role), args.out)
        return
    if args.command == "seed-demo":
        _seed_demo(_slug(args.role))
        return
    if args.command == "artifacts":
        _artifacts(_slug(args.role), args.budget, args.seed)
        return
    _blueprint(_slug(args.role), args.budget, store=not args.no_store)


if __name__ == "__main__":
    main()
