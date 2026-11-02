"""Writes the static demo's data (public blueprint, starter files, the week) to JSON.

The demo page needs no server, so everything it shows is baked in here. The answer key and the
reference solution are never written: only what a learner may see.

    uv run python scripts/export_demo_data.py
"""

import json
from pathlib import Path

from firstweek_simulation import demo_internship, demo_project
from firstweek_simulation import internship as work

OUT = Path(__file__).resolve().parent.parent / "apps" / "demo" / "src" / "data.json"


def main() -> None:
    starter, _reference = demo_project.files()
    project = demo_project.blueprint("GenAI Engineer", Path("/unused"))
    data = {
        "blueprint": project.public_view(),
        "files": starter,
        "internship": work.public_view(demo_internship.internship()),
    }
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
