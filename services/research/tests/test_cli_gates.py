"""The command-line gates that decide whether money is spent and whether a report is stored.

No database and no model: the report, verifier and settings are replaced by stand-ins."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from firstweek_research import __main__ as cli
from firstweek_research import report as report_mod
from firstweek_research import static_reports, verify
from firstweek_research.review import ReviewError


def settings(**keys: str | None) -> SimpleNamespace:
    base: dict[str, SecretStr | None] = {
        "anthropic_api_key": SecretStr("a"),
        "openai_api_key": None,
        "gemini_api_key": None,
    }
    base.update({k: SecretStr(v) if v else None for k, v in keys.items()})
    return SimpleNamespace(**base)


# judge_problem: the verifier must come from another family than the writer


def test_a_claude_verifier_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings())
    problem = cli.judge_problem("anthropic/claude-haiku")
    assert problem is not None and "another model family" in problem


def test_a_gemini_verifier_needs_its_key_and_points_at_the_free_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings())
    problem = cli.judge_problem("gemini/gemini-flash")
    assert problem is not None and "GEMINI_API_KEY" in problem and "aistudio" in problem
    monkeypatch.setattr(cli, "get_settings", lambda: settings(gemini_api_key="g"))
    assert cli.judge_problem("gemini/gemini-flash") is None


def test_an_openai_verifier_needs_its_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings())
    problem = cli.judge_problem("openai/gpt")
    assert problem is not None and "OPENAI_API_KEY" in problem and "aistudio" not in problem
    monkeypatch.setattr(cli, "get_settings", lambda: settings(openai_api_key="o"))
    assert cli.judge_problem("openai/gpt") is None


def test_a_local_model_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings())
    assert cli.judge_problem("ollama/llama3") is None


# _report: nothing is stored unless the verifier finished


class Gateway:
    flushed = 0

    def model_for(self, _tier: str) -> str:
        return "gemini/judge"

    def flush(self) -> None:
        Gateway.flushed += 1


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A report pipeline that records what was stored."""
    state: dict[str, Any] = {"stored": [], "verify_error": None, "preflight_calls": 0}
    draft = SimpleNamespace(verifier_model=None)
    verified = SimpleNamespace(verifier_model="gemini/judge")

    async def fake_draft(*_a: Any, **_k: Any) -> SimpleNamespace:
        return draft

    async def fake_verify(_g: Any, _d: Any) -> SimpleNamespace:
        if state["verify_error"]:
            raise state["verify_error"]
        return verified

    def fake_preflight(_g: Any) -> None:
        state["preflight_calls"] += 1

    monkeypatch.setattr(cli, "get_settings", lambda: settings(gemini_api_key="g"))
    monkeypatch.setattr(cli, "_gateway", lambda: Gateway())
    monkeypatch.setattr(cli, "preflight_judge", fake_preflight)
    monkeypatch.setattr(report_mod, "draft_report", fake_draft)
    monkeypatch.setattr(report_mod, "to_markdown", lambda _d: "# the report")
    monkeypatch.setattr(verify, "verify_report", fake_verify)
    monkeypatch.setattr(verify, "store_report", lambda d: state["stored"].append(d) or "r-1")
    return state


def test_a_verified_report_is_stored(
    pipeline: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    cli._report("genai-engineer", 1.0, None)
    assert len(pipeline["stored"]) == 1 and pipeline["preflight_calls"] == 1
    assert "Stored as report r-1" in capsys.readouterr().out


def test_no_verify_prints_a_draft_and_stores_nothing(
    pipeline: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    cli._report("genai-engineer", 1.0, None, verify=False)
    assert pipeline["stored"] == [] and pipeline["preflight_calls"] == 0
    assert "# the report" in capsys.readouterr().out


def test_a_failed_verifier_keeps_the_draft_file_but_stores_nothing(
    pipeline: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pipeline["verify_error"] = RuntimeError("quota exhausted")
    out = tmp_path / "reports" / "r.md"
    with pytest.raises(SystemExit) as stopped:
        cli._report("genai-engineer", 1.0, str(out))
    assert stopped.value.code == 1
    assert pipeline["stored"] == [] and out.read_text(encoding="utf-8") == "# the report"
    assert "nothing was stored: quota exhausted" in capsys.readouterr().out


def test_a_report_with_no_statistics_exits_cleanly_and_flushes(
    pipeline: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def none(*_a: Any, **_k: Any) -> None:
        raise report_mod.NoStatisticsError("No statistics yet. Run make research first.")

    monkeypatch.setattr(report_mod, "draft_report", none)
    before = Gateway.flushed
    with pytest.raises(SystemExit) as stopped:
        cli._report("genai-engineer", 1.0, None)
    assert stopped.value.code == 1 and Gateway.flushed == before + 1
    assert "No statistics yet" in capsys.readouterr().out


def test_no_writer_key_stops_before_anything_is_built(
    pipeline: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings(anthropic_api_key=None))
    with pytest.raises(SystemExit):
        cli._report("genai-engineer", 1.0, None)
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().out and pipeline["stored"] == []


def test_a_bad_verifier_key_stops_before_the_paid_draft(
    pipeline: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings())  # no Gemini key

    async def must_not_run(*_a: Any, **_k: Any) -> None:
        raise AssertionError("the draft was paid for")

    monkeypatch.setattr(report_mod, "draft_report", must_not_run)
    with pytest.raises(SystemExit) as stopped:
        cli._report("genai-engineer", 1.0, None)
    assert stopped.value.code == 1 and "GEMINI_API_KEY" in capsys.readouterr().out


# _check_reports: a quote that left its page fails the command


def _checks(monkeypatch: pytest.MonkeyPatch, statuses: list[str]) -> None:
    rows = [
        SimpleNamespace(status=s, url=f"https://x/{i}", quote="q") for i, s in enumerate(statuses)
    ]
    monkeypatch.setattr(static_reports, "check_all", lambda: {"genai-engineer": rows})


def test_missing_quotes_fail_the_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _checks(monkeypatch, ["found", "missing", "missing"])
    with pytest.raises(SystemExit) as stopped:
        cli._check_reports()
    out = capsys.readouterr().out
    assert stopped.value.code == 1 and "2 quotes are no longer on their page" in out
    assert "1 found, 2 missing" in out


def test_an_unreachable_page_is_shown_but_does_not_fail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _checks(monkeypatch, ["found", "unreachable"])
    cli._check_reports()  # no exit
    assert "unreachable: https://x/1" in capsys.readouterr().out


# _human_review: a refusal is one line and exit 1; a stopped session keeps its decisions


def test_a_review_error_is_one_line_and_exit_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from firstweek_research import review as rv

    def boom(_slug: str) -> str:
        raise ReviewError("Every claim needs a decision first.")

    monkeypatch.setattr(rv, "latest_report_id", boom)
    with pytest.raises(SystemExit) as stopped:
        cli._human_review("publish-report", "genai-engineer")
    assert stopped.value.code == 1
    assert capsys.readouterr().out.strip() == "Every claim needs a decision first."


def test_ctrl_c_while_reviewing_says_decisions_are_saved(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from firstweek_research import review as rv
    from firstweek_research import review_cli

    def interrupted(*_a: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(rv, "latest_report_id", lambda _s: "r-1")
    monkeypatch.setattr(review_cli, "review_report", interrupted)
    cli._human_review("review-report", "genai-engineer")  # returns normally
    assert "Decisions so far are saved" in capsys.readouterr().out
