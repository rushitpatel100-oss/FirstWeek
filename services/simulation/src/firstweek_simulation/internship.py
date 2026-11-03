"""The virtual internship around a project: a scripted week, colleagues who chat in character,
and an end-of-week supervisor review (ADR 0023).

The script is data next to the project (`internship.json`), not code, so generated projects can
bring their own later. Colleagues are built from the public blueprint only: they never see the
answer key, so they cannot leak what they do not have. Chat and review are one model call each."""

import json
import uuid
from pathlib import Path
from typing import Any

from firstweek_core.contracts import Colleague, Internship, SkillEvidence, SupervisorVerdict
from firstweek_core.llm import LLMGateway
from firstweek_core.llm import Tier as ModelTier
from firstweek_core.sandbox import JobResult
from firstweek_simulation.blueprint import load_prompt
from firstweek_simulation.workspace import Project, WorkspaceError, with_edits

SCRIPT_FILE = "internship.json"
CHAT_VERSION = "colleague-chat.v1"
VERDICT_VERSION = "supervisor-review.v1"
MAX_MESSAGE_CHARS = 1_500
MAX_HISTORY = 12  # turns the colleague remembers
VERDICT_FILE_CHARS = 24_000
VERDICT_TEST_CHARS = 4_000
VERDICT_CHAT_CHARS = 6_000


def load_internship(root: Path, blueprint_id: uuid.UUID) -> Internship | None:
    path = root / str(blueprint_id) / SCRIPT_FILE
    if not path.is_file():
        return None
    return Internship.model_validate_json(path.read_text("utf-8"))


def write_internship(root: Path, blueprint_id: uuid.UUID, script: Internship) -> None:
    folder = root / str(blueprint_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / SCRIPT_FILE).write_text(json.dumps(script.model_dump(), indent=2))


def public_view(script: Internship) -> dict[str, Any]:
    """What the learner may see: names, roles and what happens. Never the personas."""
    return {
        "colleagues": [{"key": c.key, "name": c.name, "role": c.role} for c in script.colleagues],
        "events": [e.model_dump() for e in script.events],
    }


def colleague_of(script: Internship, key: str) -> Colleague:
    for colleague in script.colleagues:
        if colleague.key == key:
            return colleague
    raise WorkspaceError(f"There is no colleague {key} here.")


def _events_so_far(script: Internship, day: int) -> str:
    names = {c.key: c.name for c in script.colleagues}
    lines = [
        f"- Day {e.day}, {names.get(e.sender, e.sender)} ({e.kind}): {e.text}"
        for e in script.events
        if e.day <= day
    ]
    return "\n".join(lines) or "(nothing yet)"


def _tickets(project: Project) -> str:
    return "\n".join(
        f"- {t['key']} (day {t['due_day']}): {t['title']}. {t['description']}"
        for t in project.blueprint["tickets"]
    )


async def chat(
    gateway: LLMGateway,
    project: Project,
    script: Internship,
    colleague_key: str,
    day: int,
    history: list[tuple[str, str]],
    message: str,
    *,
    tier: ModelTier = "judge",
    budget_usd: float = 0.02,
) -> tuple[str, str]:
    """One colleague's reply. `history` is (speaker, text) with speaker 'you' or 'them'."""
    person = colleague_of(script, colleague_key)
    shown = "\n".join(
        f"{'Intern' if who == 'you' else person.name}: {text[:MAX_MESSAGE_CHARS]}"
        for who, text in history[-MAX_HISTORY:]
    )
    system, template = load_prompt(CHAT_VERSION)
    user = template.format(
        name=person.name,
        role=person.role,
        persona=person.persona,
        company=project.blueprint["company_context"],
        scenario=project.blueprint["scenario"],
        tickets=_tickets(project),
        day=day,
        events=_events_so_far(script, day),
        history=shown or "(this is the first message)",
        message=message[:MAX_MESSAGE_CHARS],
    )
    result = await gateway.complete(
        purpose="colleague-chat",
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        tier=tier,
        budget_scope=f"chat:{project.blueprint_id}",
        budget_usd=budget_usd,
        max_tokens=1200,
        prompt_version=CHAT_VERSION,
    )
    return result.content.strip(), result.model


async def verdict(
    gateway: LLMGateway,
    project: Project,
    edits: dict[str, str],
    tests: JobResult | None,
    chat_messages: list[str],
    *,
    tier: ModelTier = "judge",
    budget_usd: float = 0.05,
) -> tuple[SupervisorVerdict, str]:
    """The supervisor's end-of-week review, validated against the SupervisorVerdict contract."""
    files = with_edits(project, edits)
    shown = "\n\n".join(f"--- {p} ---\n{t}" for p, t in files.items() if p.split("/")[0] != "data")
    if tests is None:
        output, code = "(the intern did not run the tests)", "n/a"
    else:
        output, code = (tests.stdout + tests.stderr)[-VERDICT_TEST_CHARS:], str(tests.exit_code)
    rubric = "\n".join(
        f"- {c['skill_id']} (weight {c['weight']}): "
        + "; ".join(f"{score}={text}" for score, text in sorted(c["anchors"].items()))
        for c in project.blueprint["rubric"]
    )
    chat_text = "\n".join(f"- {m[:MAX_MESSAGE_CHARS]}" for m in chat_messages)
    system, template = load_prompt(VERDICT_VERSION)
    user = template.format(
        scenario=project.blueprint["scenario"],
        tickets=_tickets(project),
        rubric=rubric,
        exit_code=code,
        tests=output,
        chat=chat_text[-VERDICT_CHAT_CHARS:] or "(the intern did not write to anyone)",
        files=shown[:VERDICT_FILE_CHARS],
    )
    result = await gateway.structured(
        purpose="supervisor-review",
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_model=SupervisorVerdict,
        tier=tier,
        budget_scope=f"verdict:{project.blueprint_id}",
        budget_usd=budget_usd,
        max_tokens=3000,
        prompt_version=VERDICT_VERSION,
    )
    if result.parsed is None:
        raise WorkspaceError("The review could not be written. Please try again.")
    return result.parsed, result.model


OFFLINE_MODEL = "offline"
OFFLINE_NOTE = "(The AI team is out of free quota right now, so this is a stock reply.)"
_OFFLINE_LINES = [
    "Thanks for the message. Can you tell me what you have tried so far and what you think is "
    "happening? I would rather hear a half-finished idea than nothing.",
    "Good question. Run the tests, read the first failure and tell me what it expects against "
    "what it gets. That usually points somewhere.",
    "I would keep the change small and say how sure you are. What would you check next?",
    "Understood. Write down what you know, what you do not know yet, and what you will do "
    "about it. That is most of the job.",
]


def offline_reply(history: list[tuple[str, str]]) -> str:
    """A stock answer for when no free model has quota left. Says so, and points nowhere."""
    turn = sum(1 for who, _ in history if who == "you")
    return f"{_OFFLINE_LINES[turn % len(_OFFLINE_LINES)]}\n\n{OFFLINE_NOTE}"


def offline_verdict(
    project: Project, edits: dict[str, str], tests: JobResult | None, chat_messages: list[str]
) -> SupervisorVerdict:
    """A review computed from the evidence alone (test result, a new test, chat), no model."""
    passed = tests is not None and tests.exit_code == 0 and not tests.timed_out
    added_test = any(
        p.startswith("tests/") and p.endswith(".py") and p not in project.files and t.strip()
        for p, t in edits.items()
    )
    talked = bool(chat_messages)
    skills = []
    for c in project.blueprint["rubric"]:
        skill = c["skill_id"]
        if skill == "testing":
            score = 4 if passed and added_test else 3 if added_test else 2 if passed else 1
            why = (
                "A new test of your own was added under tests/."
                if added_test
                else "No test of your own was added under tests/."
            )
        else:
            score = 4 if passed else 2
            why = (
                "The final test run passes."
                if passed
                else "The final test run still fails, so part of the problem remains."
            )
        skills.append(SkillEvidence(skill_id=skill, score=score, evidence=why))
    state = "the given tests pass" if passed else "the given tests still fail"
    return SupervisorVerdict(
        summary=f"Automatic review (the AI supervisor is out of free quota): {state}.",
        skills=skills,
        went_well=[
            "The given tests pass" if passed else "You ran the tests",
            "You asked colleagues for context" if talked else "You kept your changes small",
        ],
        to_work_on=[
            "Explain the findings in plain words"
            if added_test
            else "Add a test that fails on the old code",
            "Say how sure you are" if talked else "Talk to colleagues sooner",
        ],
        next_step="Write three plain sentences for your manager: what was wrong, what you "
        "changed, and how sure you are.",
    )
