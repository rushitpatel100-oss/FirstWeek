"""The research command line: errors a person can act on read as one line, not a traceback."""

import pytest
from sqlalchemy.exc import OperationalError

from firstweek_research import __main__ as cli

REFUSED = OperationalError(
    "SELECT 1",
    {},
    Exception('connection failed: connection to server at "127.0.0.1", port 5432 failed'),
)


def test_a_stopped_database_is_one_line_without_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(_argv: list[str] | None) -> None:
        raise REFUSED

    monkeypatch.setattr(cli, "_main", fail)
    with pytest.raises(SystemExit) as stopped:
        cli.main(["index-evidence"])
    assert stopped.value.code == 1
    message = capsys.readouterr().err.strip()
    assert message.startswith("Can't reach the database at ")
    assert message.endswith("Start it with: docker compose up -d")
    assert "\n" not in message and "password" not in message.lower()


def test_other_database_errors_still_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    other = OperationalError("SELECT 1", {}, Exception("canceling statement due to timeout"))

    def fail(_argv: list[str] | None) -> None:
        raise other

    monkeypatch.setattr(cli, "_main", fail)
    with pytest.raises(OperationalError):
        cli.main(["index-evidence"])
