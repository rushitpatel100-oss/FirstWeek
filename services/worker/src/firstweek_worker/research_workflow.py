"""DailyResearchWorkflow: collect, then analyse, each golden role in turn.

One role failing never stops the others; the report says what happened to each.
"""

from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from firstweek_worker.research_activities import (
        AnalyseOutcome,
        CollectOutcome,
        RoleRunInput,
        analyse_role,
        collect_role,
    )


@dataclass
class DailyResearchInput:
    role_slugs: list[str]
    country: str = "GB"
    budget_usd_per_role: float = 1.0


@dataclass
class RoleReport:
    role_slug: str
    collected: CollectOutcome | None = None
    analysed: AnalyseOutcome | None = None
    error: str | None = None


@dataclass
class DailyResearchReport:
    roles: list[RoleReport] = field(default_factory=list)

    @property
    def cost_usd(self) -> float:
        return sum(r.analysed.cost_usd for r in self.roles if r.analysed)


def _cause(exc: ActivityError) -> str:
    return str(exc.cause or exc)[:300]


@workflow.defn(name="DailyResearchWorkflow")
class DailyResearchWorkflow:
    @workflow.run
    async def run(self, inp: DailyResearchInput) -> DailyResearchReport:
        report = DailyResearchReport()
        for slug in inp.role_slugs:
            role_input = RoleRunInput(slug, inp.country, inp.budget_usd_per_role)
            role = RoleReport(slug)
            report.roles.append(role)
            try:
                role.collected = await workflow.execute_activity(
                    collect_role,
                    role_input,
                    start_to_close_timeout=timedelta(minutes=20),
                    heartbeat_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=30), maximum_attempts=3
                    ),
                )
            except ActivityError as exc:
                role.error = f"collect: {_cause(exc)}"
                continue
            try:
                role.analysed = await workflow.execute_activity(
                    analyse_role,
                    role_input,
                    start_to_close_timeout=timedelta(minutes=60),
                    # Extraction reports progress every few postings; one can take a minute.
                    heartbeat_timeout=timedelta(minutes=10),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(minutes=1), maximum_attempts=2
                    ),
                )
            except ActivityError as exc:
                role.error = f"analyse: {_cause(exc)}"
        return report
