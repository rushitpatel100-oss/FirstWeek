"""Start the daily research workflow now and print its report.

Needs the stack running (make up). Usage: python -m firstweek_worker.run_research_now
"""

import asyncio
import sys
from datetime import UTC, datetime

from temporalio.client import Client

from firstweek_core.config import get_settings
from firstweek_worker.research_workflow import DailyResearchReport, DailyResearchWorkflow
from firstweek_worker.schedules import daily_input


def print_report(report: DailyResearchReport) -> None:
    for role in report.roles:
        print(f"\n{role.role_slug}")
        if role.collected:
            c = role.collected
            print(f"  collected: {c.new} new, {c.updated} updated postings")
            for line in c.errors + c.skipped:
                print(f"    note: {line}")
        if role.analysed:
            a = role.analysed
            if a.skipped:
                print(f"  analysis skipped: {a.skipped}")
            else:
                print(
                    f"  classified {a.classified}, extracted {a.extracted}, cost ${a.cost_usd:.4f}"
                )
                print(f"  sample: {a.sample_size} postings from {a.employers} employers")
            for line in a.failures[:5]:
                print(f"    failed: {line}")
        if role.error:
            print(f"  error: {role.error}")
    print(f"\nTotal model cost: ${report.cost_usd:.4f}")


async def main() -> int:
    settings = get_settings()
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    run_id = f"research-now-{datetime.now(UTC):%Y%m%d-%H%M%S}"
    print(f"Started {run_id}. Follow it at http://localhost:8233 (this waits until it finishes).")
    report = await client.execute_workflow(
        DailyResearchWorkflow.run,
        daily_input(settings),
        id=run_id,
        task_queue=settings.temporal_task_queue,
    )
    print_report(report)
    return 0 if all(r.error is None for r in report.roles) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
