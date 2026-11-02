"""The practice workspace: the approved project, run-my-tests and the Tech Lead (ADR 0021).

Learners get the public blueprint and the starter files only. Running code goes through the
sandbox; a review runs the tests itself so the reviewer reads real results, not a claim from the
browser. Both endpoints are rate limited per client (a review also spends model money, so it has
a daily ceiling in all)."""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from firstweek_api.skill_gap import Limiter
from firstweek_core.config import Settings, get_settings
from firstweek_core.llm import LLMGateway, StructuredOutputError
from firstweek_core.llm.recorder import record_to_db
from firstweek_core.sandbox import JobResult, SandboxRunner, get_runner
from firstweek_simulation import workspace as ws

log = logging.getLogger(__name__)
router = APIRouter(prefix="/roles", tags=["workspace"])

MAX_EDIT_FILES = 40
tests_limit = Limiter(30, 3600)
review_limit = Limiter(10, 3600)
review_day_limit = Limiter(200, 86400)


class Edits(BaseModel):
    files: dict[str, str] = Field(default_factory=dict, max_length=MAX_EDIT_FILES)


class ReviewRequest(Edits):
    ticket: str = Field(pattern=r"^[A-Z][A-Z0-9]+-\d+$")


class TestRun(BaseModel):
    exit_code: int
    output: str
    timed_out: bool
    passed: bool


class ReviewResponse(BaseModel):
    review: str
    model: str
    tests: TestRun


def runner() -> SandboxRunner:
    """Overridden in tests."""
    return get_runner(get_settings())


def gateway() -> LLMGateway:
    """Overridden in tests."""
    return LLMGateway(settings=get_settings(), recorder=record_to_db)


def model_failure(exc: Exception) -> HTTPException:
    """A model call failed (out of free quota, overloaded, or an answer that never validated).
    The reason goes to the API log; the learner gets a clear status instead of a bare 500."""
    log.exception("model call failed", exc_info=exc)
    if isinstance(exc, StructuredOutputError):
        return HTTPException(502, "The model's answer could not be used. Please try again.")
    return HTTPException(503, "The model is busy or out of free quota. Please try again later.")


def current_settings() -> Settings:
    """The settings every workspace-style endpoint reads (tests replace `get_settings`)."""
    return get_settings()


def _project(slug: str) -> ws.Project:
    found = ws.approved_project(slug, Path(get_settings().artifacts_dir))
    if found is None:
        raise HTTPException(status_code=404, detail="No project for this role yet.")
    return found


def _who(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _run(project: ws.Project, edits: Edits) -> TestRun:
    try:
        result = await ws.run_tests(runner(), project, edits.files)
    except (ws.WorkspaceError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TestRun(
        exit_code=result.exit_code,
        output=result.stdout + result.stderr,
        timed_out=result.timed_out,
        passed=result.exit_code == 0 and not result.timed_out,
    )


@router.get("/{slug}/project")
def project(slug: str) -> dict[str, object]:
    """The scenario, tickets and starter files. Never the answer key."""
    found = _project(slug)
    return {"blueprint": found.blueprint, "files": found.files}


@router.post("/{slug}/project/tests")
async def run_tests(slug: str, body: Edits, request: Request) -> TestRun:
    found = _project(slug)
    if not tests_limit.allow(_who(request)):
        raise HTTPException(status_code=429, detail="Too many test runs. Try again later.")
    return await _run(found, body)


@router.post("/{slug}/project/review")
async def review(slug: str, body: ReviewRequest, request: Request) -> ReviewResponse:
    """Run the tests, then ask the Tech Lead to review the work against one ticket."""
    found = _project(slug)
    settings = get_settings()
    key = (
        settings.gemini_api_key
        if settings.simulation_tier == "judge"
        else settings.anthropic_api_key
    )
    if key is None:
        raise HTTPException(status_code=503, detail="The review is not available right now.")
    if not review_limit.allow(_who(request)) or not review_day_limit.allow("all"):
        raise HTTPException(status_code=429, detail="Too many reviews just now. Try again later.")
    tests = await _run(found, body)
    g = gateway()
    try:
        text, model = await ws.review(
            g,
            found,
            body.ticket,
            body.files,
            JobResult(
                exit_code=tests.exit_code,
                stdout=tests.output,
                stderr="",
                timed_out=tests.timed_out,
                duration_s=0,
            ),
            tier=settings.simulation_tier,
        )
    except ws.WorkspaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise model_failure(exc) from exc
    finally:
        g.flush()
    return ReviewResponse(review=text, model=model, tests=tests)
