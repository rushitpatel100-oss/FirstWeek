"""The virtual internship: the scripted week, chat with colleagues, the supervisor's review
(ADR 0023).

Same rules as the workspace: learners get the public script only (no personas, no answer key),
every model call is rate limited per client with a daily ceiling in all."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from firstweek_api import workspace as wsapi
from firstweek_api.skill_gap import Limiter
from firstweek_api.workspace import Edits, TestRun
from firstweek_core.contracts import Internship, SupervisorVerdict
from firstweek_core.sandbox import JobResult
from firstweek_simulation import internship as work
from firstweek_simulation import workspace as ws

router = APIRouter(prefix="/roles", tags=["internship"])

MAX_TURNS = 40
chat_limit = Limiter(40, 3600)
chat_day_limit = Limiter(500, 86400)
verdict_limit = Limiter(5, 3600)
verdict_day_limit = Limiter(100, 86400)


class Turn(BaseModel):
    who: str = Field(pattern=r"^(you|them)$")
    text: str = Field(max_length=work.MAX_MESSAGE_CHARS)


class ChatRequest(BaseModel):
    colleague: str = Field(pattern=r"^[a-z][a-z0-9-]{1,30}$")
    day: int = Field(ge=1, le=5)
    message: str = Field(min_length=1, max_length=work.MAX_MESSAGE_CHARS)
    history: list[Turn] = Field(default_factory=list, max_length=MAX_TURNS)


class ChatReply(BaseModel):
    reply: str
    model: str


class VerdictRequest(Edits):
    chat: list[str] = Field(default_factory=list, max_length=MAX_TURNS)


class VerdictResponse(BaseModel):
    verdict: SupervisorVerdict
    model: str
    tests: TestRun


def _result(tests: TestRun) -> JobResult:
    return JobResult(
        exit_code=tests.exit_code,
        stdout=tests.output,
        stderr="",
        timed_out=tests.timed_out,
        duration_s=0,
    )


def _script(project: ws.Project) -> Internship:
    found = work.load_internship(Path(wsapi.current_settings().artifacts_dir), project.blueprint_id)
    if found is None:
        raise HTTPException(status_code=404, detail="This project has no internship script.")
    return found


def _need_key() -> None:
    settings = wsapi.current_settings()
    has_key = (
        settings.has_judge_key
        if settings.simulation_tier == "judge"
        else settings.anthropic_api_key is not None
    )
    if not has_key:
        raise HTTPException(status_code=503, detail="The team is not available right now.")


@router.get("/{slug}/internship")
def internship(slug: str) -> dict[str, object]:
    """Who works here and what happens on each day. No personas."""
    return work.public_view(_script(wsapi._project(slug)))


@router.post("/{slug}/internship/chat")
async def chat(slug: str, body: ChatRequest, request: Request) -> ChatReply:
    found = wsapi._project(slug)
    script = _script(found)
    _need_key()
    if not chat_limit.allow(wsapi._who(request)) or not chat_day_limit.allow("all"):
        raise HTTPException(status_code=429, detail="Too many messages just now. Try again later.")
    g = wsapi.gateway()
    try:
        text, model = await work.chat(
            g,
            found,
            script,
            body.colleague,
            body.day,
            [(t.who, t.text) for t in body.history],
            body.message,
            tier=wsapi.current_settings().simulation_tier,
        )
    except ws.WorkspaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        failure = wsapi.model_failure(exc)
        if failure.status_code != 503:
            raise failure from exc
        # Out of free quota: a stock reply beats an error. It says so.
        text, model = (
            work.offline_reply([(t.who, t.text) for t in body.history]),
            work.OFFLINE_MODEL,
        )
    finally:
        g.flush()
    return ChatReply(reply=text, model=model)


@router.post("/{slug}/internship/verdict")
async def verdict(slug: str, body: VerdictRequest, request: Request) -> VerdictResponse:
    """Run the tests, then the supervisor writes the end-of-week review."""
    found = wsapi._project(slug)
    _script(found)
    _need_key()
    if not verdict_limit.allow(wsapi._who(request)) or not verdict_day_limit.allow("all"):
        raise HTTPException(status_code=429, detail="Too many reviews just now. Try again later.")
    tests = await wsapi._run(found, body)
    g = wsapi.gateway()
    try:
        written, model = await work.verdict(
            g,
            found,
            body.files,
            _result(tests),
            body.chat,
            tier=wsapi.current_settings().simulation_tier,
        )
    except ws.WorkspaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        failure = wsapi.model_failure(exc)
        if failure.status_code != 503:
            raise failure from exc
        written = work.offline_verdict(found, body.files, _result(tests), body.chat)
        model = work.OFFLINE_MODEL
    finally:
        g.flush()
    return VerdictResponse(verdict=written, model=model, tests=tests)
