"""The gate: retry with feedback, approve only on measured numbers (ADR 0020)."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from test_artifacts import LocalRunner
from test_blueprint import FINDINGS, claim, good_draft, skill

from firstweek_core.config import Settings
from firstweek_core.contracts import RoleRealityReport
from firstweek_simulation import blueprint as bp
from firstweek_simulation import pipeline as pl
from firstweek_simulation.artifacts import BuiltArtifacts, Check


def built(ok: bool, metrics: dict[str, float] | None = None, detail: str = "") -> BuiltArtifacts:
    return BuiltArtifacts(
        starter={"src/a.py": "x = 1\n"},
        reference={"src/a.py": "x = 2\n"},
        key={"key/make_data.py": "pass\n"},
        metrics=metrics or {},
        summary="Fixed it.",
        checks=[Check("the reference solution passes every test", ok, detail)],
    )


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replaces model-driven design and build; returns the arguments each build received."""
    calls: list[dict[str, Any]] = []
    replies: list[BuiltArtifacts] = []

    async def fake_design(*_: Any, **kwargs: Any) -> bp.DesignedBlueprint:
        calls.append({"design_tier": kwargs["tier"]})
        return bp.DesignedBlueprint(bp.build_blueprint(good_draft(), FINDINGS), ["p"], 1, "m", 0.0)

    async def fake_build(*_: Any, **kwargs: Any) -> BuiltArtifacts:
        calls.append(kwargs)
        return replies.pop(0)

    async def no_week(*_: Any, **__: Any) -> Any:
        raise bp.BlueprintError("not under test here")

    monkeypatch.setattr(pl, "design_week", no_week)
    monkeypatch.setattr(pl, "design_blueprint", fake_design)
    monkeypatch.setattr(pl, "build", fake_build)
    calls.append({"replies": replies})
    return calls


async def run(
    replies_for: list[BuiltArtifacts], scripted: list[dict[str, Any]], **kw: Any
) -> tuple[pl.PipelineResult, list[str]]:
    scripted[0]["replies"].extend(replies_for)
    messages: list[str] = []
    result = await pl.run_pipeline(
        None,  # type: ignore[arg-type]
        LocalRunner(),
        "genai-engineer",
        FINDINGS,
        progress=messages.append, **kw,
    )  # fmt: skip
    return result, messages


async def test_a_first_attempt_that_passes_is_approved_without_retries(
    scripted: list[dict[str, Any]],
) -> None:
    result, _ = await run([built(True, {"accuracy": 0.9})], scripted)
    assert result.approved and result.attempts == 1
    assert scripted[1]["design_tier"] == "judge" and scripted[2]["feedback"] == ""


async def test_a_failed_attempt_is_retried_with_the_failures_in_the_prompt(
    scripted: list[dict[str, Any]],
) -> None:
    result, messages = await run(
        [built(False, detail="exit 1: ImportError in src/a.py"), built(True, {"a": 1.0})], scripted
    )
    assert result.approved and result.attempts == 2
    assert "ImportError in src/a.py" in scripted[3]["feedback"]
    assert len(result.history) == 2 and not result.history[0][0].ok
    assert any("Attempt 1: failed" in m for m in messages)


async def test_three_failures_end_unapproved_and_report_every_attempt(
    scripted: list[dict[str, Any]],
) -> None:
    result, _ = await run([built(False, detail=f"problem {i}") for i in range(3)], scripted)
    assert not result.approved and result.attempts == 3 and len(result.history) == 3
    assert "NOT APPROVED" in pl.report_text(result)


async def test_passing_checks_without_measured_numbers_is_not_approved(
    scripted: list[dict[str, Any]],
) -> None:
    result, _ = await run([built(True, {})], scripted, attempts=1)
    assert not result.approved


async def test_the_tier_and_attempts_are_passed_through(scripted: list[dict[str, Any]]) -> None:
    await run([built(True, {"a": 1.0})], scripted, tier="mid", attempts=2)
    assert scripted[1]["design_tier"] == "mid" and scripted[2]["tier"] == "mid"


async def test_the_output_folder_holds_everything_a_reviewer_needs(
    scripted: list[dict[str, Any]], tmp_path: Path
) -> None:
    result, _ = await run([built(True, {"accuracy": 0.9})], scripted)
    pl.write_output(tmp_path / "out", result)
    out = tmp_path / "out"
    assert (out / "starter/src/a.py").read_text() == "x = 1\n"
    assert (out / "reference/src/a.py").read_text() == "x = 2\n"
    assert (out / "key/key/make_data.py").exists()
    assert json.loads((out / "metrics.json").read_text()) == {"accuracy": 0.9}
    assert "APPROVED (automatic)" in (out / "report.md").read_text()
    assert json.loads((out / "blueprint.json").read_text())["answer_key"]["planted_issues"]
    assert json.loads((out / "attempts.json").read_text())[0][0]["ok"] is True


def test_a_report_file_gives_the_same_findings_as_the_database(tmp_path: Path) -> None:
    report = RoleRealityReport(
        archetype="GenAI Engineer",
        trust_level="golden",
        version=1,
        country="GB",
        sample_size=20,
        date_range=(date(2026, 5, 4), date(2026, 10, 28)),
        summary=[],
        asked_for=[skill("python", 0.8), skill("rare", 0.05)],
        responsibilities=[claim("Builds retrieval pipelines.")],
        day_to_day=[],
        typical_week=[],
        pain_points=[claim("Retrieval cites old documents.")],
    )
    path = tmp_path / "genai.json"
    path.write_text(
        json.dumps(
            {
                "slug": "genai-engineer",
                "role_name": "GenAI Engineer",
                "report": report.model_dump(mode="json"),
            }
        )
    )
    slug, findings = pl.findings_from_file(path)
    assert slug == "genai-engineer" and findings.version_id is None
    assert findings.pain_points == ["Retrieval cites old documents."]
    assert [s.skill_id for s in findings.skills] == ["python"]
    designed = bp.DesignedBlueprint(bp.build_blueprint(good_draft(), findings), ["p"], 1, "m", 0.0)
    with pytest.raises(bp.BlueprintError, match="from a file"):
        bp.store_blueprint(findings, designed)


def test_the_default_tier_is_the_free_one() -> None:
    assert Settings(_env_file=None).simulation_tier == "judge"


async def test_an_approved_project_gets_its_week_and_it_is_stored_beside_the_files(
    scripted: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from test_week import script

    from firstweek_simulation import week as wk

    week = script(bp.build_blueprint(good_draft(), FINDINGS))

    async def fake_week(*_: Any, **__: Any) -> wk.DesignedWeek:
        return wk.DesignedWeek(week, 0.01)

    monkeypatch.setattr(pl, "design_week", fake_week)
    result, messages = await run([built(True, {"accuracy": 0.9})], scripted)
    assert result.week == week and any("scripted week" in m for m in messages)
    pl.write_output(tmp_path / "out", result)
    assert (tmp_path / "out" / "week.json").is_file()


async def test_a_failed_week_leaves_the_project_approved(scripted: list[dict[str, Any]]) -> None:
    result, messages = await run([built(True, {"accuracy": 0.9})], scripted)
    assert result.approved and result.week is None
    assert any("No week script" in m for m in messages)
