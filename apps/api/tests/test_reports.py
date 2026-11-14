"""The report endpoints serve published reports only (a test database)."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from sqlalchemy.exc import OperationalError

from firstweek_api.main import app
from firstweek_core.contracts import Citation, Claim, RoleRealityReport, SkillStat
from firstweek_core.db.models import ArchetypeVersion, Blueprint, RoleArchetype, RoleReport
from firstweek_core.db.session import get_engine, session_scope

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("No database available")
    with session_scope() as session:
        session.execute(delete(RoleReport))
        session.execute(delete(ArchetypeVersion))
        session.execute(delete(RoleArchetype))


def report(marker: str) -> RoleRealityReport:
    claim = Claim(
        text=f"{marker} says the week is mostly evaluation work.",
        citations=[
            Citation(
                source_url="https://blog.example.com/week",
                tier="blog",
                quote="evals every Monday",
            )
        ],
        confidence=0.4,
        verification="supported",
    )
    return RoleRealityReport(
        archetype="GenAI Engineer",
        trust_level="golden",
        version=1,
        country="GB",
        sample_size=15,
        date_range=(date(2026, 5, 1), date(2026, 10, 1)),
        summary=[claim],
        asked_for=[
            SkillStat(
                skill_id="python",
                label="Python",
                count=12,
                share=0.8,
                ci_low=0.55,
                ci_high=0.93,
                n=15,
            )
        ],
        day_to_day=[],
        typical_week=[],
        pain_points=[],
    )


def add_report(slug: str, name: str, status: str, marker: str, age_days: int = 0) -> None:
    with session_scope() as session:
        role = session.query(RoleArchetype).filter_by(slug=slug).one_or_none()
        if role is None:
            role = RoleArchetype(slug=slug, name=name, definition="d", trust_level="golden")
            session.add(role)
            session.flush()
        version = ArchetypeVersion(
            archetype_id=role.id,
            version=session.query(ArchetypeVersion).filter_by(archetype_id=role.id).count() + 1,
            country="GB",
            date_from=date(2026, 5, 1),
            date_to=date(2026, 10, 1),
            sample_size=15,
            status="published",
        )
        session.add(version)
        session.flush()
        session.add(
            RoleReport(
                archetype_version_id=version.id,
                report=report(marker).model_dump(mode="json"),
                status=status,
                published_at=datetime.now(UTC) - timedelta(days=age_days)
                if status == "published"
                else None,
            )
        )


@pytest.mark.db
def test_unpublished_reports_are_never_served() -> None:
    add_report("genai-engineer", "GenAI Engineer", "draft", "Draft")
    add_report("agentic-ai-engineer", "Agentic AI Engineer", "reviewed", "Reviewed")
    assert client.get("/roles").json() == []
    assert client.get("/roles/genai-engineer/report").status_code == 404
    assert client.get("/roles/no-such-role/report").status_code == 404


@pytest.mark.db
def test_the_newest_published_report_is_served_and_roles_are_listed_by_name() -> None:
    add_report("genai-engineer", "GenAI Engineer", "published", "Old", age_days=5)
    add_report("genai-engineer", "GenAI Engineer", "published", "New", age_days=1)
    add_report("agentic-ai-engineer", "Agentic AI Engineer", "published", "Agentic")

    roles = client.get("/roles").json()
    assert [r["slug"] for r in roles] == ["agentic-ai-engineer", "genai-engineer"]
    assert roles[1]["sample_size"] == 15 and roles[1]["country"] == "GB"

    body = client.get("/roles/genai-engineer/report").json()
    assert body["name"] == "GenAI Engineer"
    assert body["report"]["summary"][0]["text"].startswith("New says")
    assert body["report"]["summary"][0]["confidence"] == 0.4


@pytest.mark.db
def test_a_role_with_only_a_practice_project_is_listed_without_a_report() -> None:
    add_report("genai-engineer", "GenAI Engineer", "published", "Published")
    with session_scope() as session:
        role = RoleArchetype(
            slug="ml-engineer", name="ML Engineer", definition="d", trust_level="on_demand"
        )
        session.add(role)
        session.flush()
        version = ArchetypeVersion(
            archetype_id=role.id, version=1, country="GB", date_from=date(2026, 5, 1),
            date_to=date(2026, 10, 1), sample_size=0, status="draft",
        )  # fmt: skip
        session.add(version)
        session.flush()
        for status in ("draft", "approved"):  # a draft alone would not list the role
            session.add(
                Blueprint(
                    archetype_version_id=version.id,
                    scenario="s",
                    blueprint={},
                    answer_key={},
                    validated=True,
                    status=status,
                )
            )
    roles = {r["slug"]: r for r in client.get("/roles").json()}
    assert list(roles) == ["genai-engineer", "ml-engineer"]  # reports first
    assert roles["genai-engineer"]["has_report"] is True
    assert roles["ml-engineer"]["has_report"] is False
    assert roles["ml-engineer"]["sample_size"] is None
    assert client.get("/roles/ml-engineer/report").status_code == 404


@pytest.mark.db
def test_researched_reports_are_served_after_seeding() -> None:
    from firstweek_research import static_reports

    static_reports.seed()
    roles = client.get("/roles").json()
    assert {r["slug"] for r in roles} == {
        "agentic-ai-engineer",
        "ai-software-engineer",
        "genai-engineer",
    }
    body = client.get("/roles/ai-software-engineer/report").json()
    assert body["report"]["provenance"]["method"] == "researched"
    assert body["report"]["asked_for"][0]["n"] == body["report"]["sample_size"]
