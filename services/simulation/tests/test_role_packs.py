"""Every hand-written practice project beyond the first four (ADR 0029): the starter fails its
tests, the reference passes, each planted mistake is caught by its own test, the answer key stays
hidden, and the scripted week fits the project and gives no fix away."""

import re
from pathlib import Path

import pytest
from test_artifacts import LocalRunner

from firstweek_core.sandbox import SandboxJob
from firstweek_research.taxonomy import load_taxonomy
from firstweek_simulation import demo_project as demo

SLUGS = [
    "ml-engineer",
    "data-scientist",
    "mlops-engineer",
    "ai-data-engineer",
    "nlp-engineer",
    "computer-vision-engineer",
    "ai-product-manager",
    "ai-evaluation-engineer",
    "ai-safety-engineer",
]
TEST_COMMAND = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
GIVEAWAYS = [
    "leak",
    "split",
    "recall",
    "baseline",
    "latest",
    "dedupe",
    "normalise",
    "iou",
    "median",
]


async def run(files: dict[str, str]) -> int:
    return (await LocalRunner().run(SandboxJob(files=files, command=TEST_COMMAND))).exit_code


@pytest.mark.parametrize("slug", SLUGS)
async def test_the_starter_fails_and_the_reference_passes(slug: str) -> None:
    starter, reference = demo.pack_for(slug).files()
    assert await run(starter) == 1
    assert await run(reference) == 0


@pytest.mark.parametrize("slug", SLUGS)
async def test_each_planted_mistake_is_caught_by_its_own_test(slug: str) -> None:
    pack = demo.pack_for(slug)
    starter, reference = pack.files()
    differing = sorted(p for p in starter if starter[p] != reference[p])
    assert len(differing) == len(pack.planted) == 2
    for path in differing:
        assert await run({**reference, path: starter[path]}) == 1, path


@pytest.mark.parametrize("slug", SLUGS)
def test_the_public_view_hides_the_key_and_the_numbers_are_deterministic(
    slug: str, tmp_path: Path
) -> None:
    pack = demo.pack_for(slug)
    project = demo.blueprint(slug, tmp_path, pack)
    public = str(project.public_view())
    assert "planted_issues" not in public and "reference_solution_uri" not in public
    assert not any(issue in public for issue in pack.planted)
    assert pack.metrics() == pack.metrics() and pack.metrics()


@pytest.mark.parametrize("slug", SLUGS)
def test_the_week_fits_the_project_and_gives_no_fix_away(slug: str) -> None:
    pack = demo.pack_for(slug)
    script = pack.internship()
    people = {c.key for c in script.colleagues}
    due = {t.key: t.due_day for t in pack.tickets()}
    assigned = [e for e in script.events if e.ticket]
    assert sorted(e.ticket or "" for e in assigned) == sorted(due)
    assert all(e.sender in people for e in script.events)
    assert all(e.day <= due[e.ticket or ""] for e in assigned)
    assert {e.day for e in script.events} == {1, 2, 3, 4, 5}
    for event in script.events:
        lowered = event.text.lower()
        assert not any(word in lowered for word in GIVEAWAYS), event.text
        assert not re.search(r"`|\.py\b", event.text)


@pytest.mark.parametrize("slug", SLUGS)
def test_the_rubric_adds_up_and_only_names_known_skills(slug: str) -> None:
    pack = demo.pack_for(slug)
    rubric = pack.rubric()
    assert abs(sum(c.weight for c in rubric) - 1.0) < 1e-9
    known = set(load_taxonomy().entries)
    used = {c.skill_id for c in rubric} | {s for t in pack.tickets() for s in t.skills}
    assert used <= known, used - known
