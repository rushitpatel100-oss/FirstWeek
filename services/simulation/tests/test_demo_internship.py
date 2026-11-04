"""The scripted week must fit the project it belongs to and never give a fix away."""

import re
import uuid
from pathlib import Path

from firstweek_simulation import demo_internship as demo
from firstweek_simulation import demo_project
from firstweek_simulation import internship as work


def test_every_ticket_is_assigned_once_by_a_real_colleague_no_later_than_its_due_day() -> None:
    script = demo.internship()
    people = {c.key for c in script.colleagues}
    due = {t.key: t.due_day for t in demo_project.tickets()}
    assigned = [e for e in script.events if e.ticket]
    assert sorted(e.ticket or "" for e in assigned) == sorted(due)
    assert all(e.sender in people for e in script.events)
    assert all(e.day <= due[e.ticket or ""] for e in assigned)
    assert {e.day for e in script.events} == {1, 2, 3, 4, 5}


def test_no_message_names_a_file_function_or_fix() -> None:
    planted = ["metrics.py", "evalset.py", "load_rows", "citation_accuracy", "startswith"]
    for event in demo.internship().events:
        assert not any(word in event.text for word in planted), event.text
        assert not re.search(r"`|\.py\b", event.text)


def test_the_public_view_leaves_out_personas_and_the_script_round_trips(tmp_path: Path) -> None:
    script = demo.internship()
    shown = work.public_view(script)
    assert "persona" not in str(shown) and script.colleagues[0].persona not in str(shown)
    blueprint_id = uuid.uuid4()
    work.write_internship(tmp_path, blueprint_id, script)
    assert work.load_internship(tmp_path, blueprint_id) == script
    assert work.load_internship(tmp_path, uuid.uuid4()) is None
