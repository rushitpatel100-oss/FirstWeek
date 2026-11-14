"""A hand-written practice project for the Computer Vision Engineer role (ADR 0029).

Needs no model call and no library beyond the standard one: the detector's outputs are recorded
in a file, and the project is the code that scores them. The story: a helmet detector at a
fictional construction-safety firm. The dashboard says precision and recall are both around 90%
or better, but site managers say it misses people without helmets and flags the same
helmet twice. Two realistic mistakes explain it: a duplicate detection of one helmet is
counted as another correct find, and images where the detector found nothing are left out of
the scoring entirely."""

import json
import random
from typing import Any

from firstweek_core.contracts import Criterion, Internship, Ticket
from firstweek_simulation import demo_kit as kit

SEED = 8
IMAGES = 30
SILENT = 7  # images where the detector outputs nothing
THRESHOLD = 0.5

BOXES = '''"""Boxes are [x1, y1, x2, y2]."""


def iou(a, b):
    """Overlap divided by combined area: 1 for identical boxes, 0 for boxes that do not touch."""
    width = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = width * height
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0
'''
MATCH_BUGGY = '''"""Matching a detector's boxes to the true boxes in one image."""

from src.boxes import iou


def match(detections, truth, threshold=0.5):
    """Returns (true positives, false positives, missed)."""
    tp = fp = 0
    for d in detections:
        if any(iou(d["box"], t) >= threshold for t in truth):
            tp += 1
        else:
            fp += 1
    missed = sum(not any(iou(d["box"], t) >= threshold for d in detections) for t in truth)
    return tp, fp, missed
'''
MATCH_FIXED = '''"""Matching a detector's boxes to the true boxes in one image."""

from src.boxes import iou


def match(detections, truth, threshold=0.5):
    """Returns (true positives, false positives, missed). A true box can be found only once."""
    free = list(truth)
    tp = fp = 0
    for d in sorted(detections, key=lambda d: -d["score"]):
        hit = next((t for t in free if iou(d["box"], t) >= threshold), None)
        if hit is None:
            fp += 1
        else:
            free.remove(hit)
            tp += 1
    return tp, fp, len(free)
'''
METRICS_BUGGY = '''"""Precision and recall over all images."""

from src.match import match


def evaluate(images, threshold=0.5):
    tp = fp = missed = 0
    for image in images:
        if not image["detections"]:
            continue
        a, b, c = match(image["detections"], image["truth"], threshold)
        tp, fp, missed = tp + a, fp + b, missed + c
    return {
        "precision": round(tp / (tp + fp), 3) if tp + fp else 0.0,
        "recall": round(tp / (tp + missed), 3) if tp + missed else 0.0,
    }
'''
METRICS_FIXED = '''"""Precision and recall over all images."""

from src.match import match


def evaluate(images, threshold=0.5):
    tp = fp = missed = 0
    for image in images:
        a, b, c = match(image["detections"], image["truth"], threshold)
        tp, fp, missed = tp + a, fp + b, missed + c
    return {
        "precision": round(tp / (tp + fp), 3) if tp + fp else 0.0,
        "recall": round(tp / (tp + missed), 3) if tp + missed else 0.0,
    }
'''
REPORT = '''"""What the weekly detector dashboard shows."""

import json

from src.metrics import evaluate


def scores(path="data/images.json"):
    return evaluate(json.load(open(path)))


if __name__ == "__main__":
    print(scores())
'''
README = """# Helmet detector scoring

`data/images.json` has one entry per site photo: the true helmet boxes (`truth`) and what the
detector found (`detections`, each with a `box` as [x1, y1, x2, y2] and a `score`). `src/match.py`
matches detections to true boxes in one image, `src/metrics.py` turns that into precision and
recall, and `python -m src.report` prints the numbers on the weekly dashboard.

Run the tests with `python -m pytest`.
"""
TESTS = """from src.boxes import iou
from src.match import match
from src.metrics import evaluate

HELMET = [10, 10, 30, 30]
NEARLY = [11, 11, 31, 31]


def test_overlap_is_measured_correctly():
    assert iou(HELMET, HELMET) == 1.0
    assert iou(HELMET, [100, 100, 120, 120]) == 0.0
    assert round(iou([0, 0, 10, 10], [5, 0, 15, 10]), 3) == 0.333


def test_a_helmet_found_twice_is_one_find_and_one_false_alarm():
    detections = [{"box": HELMET, "score": 0.9}, {"box": NEARLY, "score": 0.8}]
    assert match(detections, [HELMET]) == (1, 1, 0)


def test_a_photo_where_nothing_was_found_still_counts_its_missed_helmets():
    images = [
        {"truth": [HELMET], "detections": []},
        {"truth": [HELMET], "detections": [{"box": HELMET, "score": 0.9}]},
    ]
    assert evaluate(images)["recall"] == 0.5
"""
SCENARIO = (
    "Brightline Safety sells a camera system that spots workers without hard hats on "
    "construction sites. The weekly detector dashboard says precision and recall are both above "
    "90%, but site managers say the system misses people and sometimes raises two alarms for "
    "one person. Your first week is about finding out what the dashboard really measures."
)
CONTEXT = (
    "Brightline has about 150 staff and a vision team of five. Customers get an alert on their "
    "phone for every detection, so false alarms train them to ignore the system and misses are "
    "a safety risk."
)


def _box(rng: random.Random) -> list[int]:
    x, y = rng.randint(0, 70), rng.randint(0, 70)
    return [x, y, x + rng.randint(15, 25), y + rng.randint(15, 25)]


def _near(rng: random.Random, box: list[int], jitter: int) -> list[int]:
    return [v + rng.randint(-jitter, jitter) for v in box]


def images() -> list[dict[str, Any]]:
    rng = random.Random(SEED)
    silent = set(rng.sample(range(IMAGES), SILENT))
    rows: list[dict[str, Any]] = []
    for i in range(IMAGES):
        truth = [_box(rng) for _ in range(rng.randint(1, 3))]
        found: list[dict[str, Any]] = []
        if i not in silent:
            for t in truth:
                if rng.random() < 0.8:
                    found.append(
                        {"box": _near(rng, t, 1), "score": round(rng.uniform(0.7, 0.99), 2)}
                    )
                    if rng.random() < 0.6:  # the same helmet found again
                        found.append(
                            {"box": _near(rng, t, 2), "score": round(rng.uniform(0.5, 0.7), 2)}
                        )
            if rng.random() < 0.2:
                found.append({"box": _box(rng), "score": round(rng.uniform(0.5, 0.6), 2)})
        rows.append({"image": i, "truth": truth, "detections": found})
    return rows


def _iou(a: list[int], b: list[int]) -> float:
    w = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = w * h
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def _scores(honest: bool) -> dict[str, float]:
    tp = fp = missed = 0
    for img in images():
        dets, truth = img["detections"], img["truth"]
        if not honest and not dets:
            continue
        if honest:
            free = list(truth)
            for d in sorted(dets, key=lambda d: -d["score"]):
                hit = next((t for t in free if _iou(d["box"], t) >= THRESHOLD), None)
                if hit is None:
                    fp += 1
                else:
                    free.remove(hit)
                    tp += 1
            missed += len(free)
        else:
            for d in dets:
                if any(_iou(d["box"], t) >= THRESHOLD for t in truth):
                    tp += 1
                else:
                    fp += 1
            missed += sum(not any(_iou(d["box"], t) >= THRESHOLD for d in dets) for t in truth)
    return {
        "precision": round(tp / (tp + fp), 3),
        "recall": round(tp / (tp + missed), 3),
    }


def files() -> tuple[dict[str, str], dict[str, str]]:
    shared = {
        "README.md": README,
        "src/__init__.py": "",
        "src/boxes.py": BOXES,
        "src/report.py": REPORT,
        "tests/test_scoring.py": TESTS,
        "data/images.json": json.dumps(images(), indent=0),
    }
    starter = {**shared, "src/match.py": MATCH_BUGGY, "src/metrics.py": METRICS_BUGGY}
    reference = {**shared, "src/match.py": MATCH_FIXED, "src/metrics.py": METRICS_FIXED}
    return starter, reference


def tickets() -> list[Ticket]:
    return kit.tickets(
        "BS",
        [
            kit.TicketSpec(
                "One helmet, two alarms: how is that scored?",
                "Customers get two alerts for one person, yet the dashboard calls both correct. "
                "Work out how detections are matched to true boxes and make each true box "
                "findable only once; the second detection is a false alarm.",
                (
                    "A helmet found twice counts as one find and one false alarm",
                    "Precision is recomputed from the corrected counts",
                ),
                ("computer-vision", "machine-learning"),
            ),
            kit.TicketSpec(
                "Photos where nothing was found",
                "Site managers say people are missed entirely, but the recall number does not "
                "move. Work out which photos the scoring leaves out and make sure missed "
                "helmets in photos with no detections count against recall.",
                (
                    "Photos with no detections are scored",
                    "Every true box in them counts as missed",
                ),
                ("computer-vision", "statistics"),
            ),
            kit.REGRESSION,
        ],
    )


def rubric() -> list[Criterion]:
    return kit.rubric(
        [
            kit.CriterionSpec(
                "computer-vision",
                0.30,
                "Raises the overlap threshold until the numbers look right.",
                "Fixes duplicates but cannot explain how matching works.",
                "Matches one detection per true box and explains what a duplicate costs users.",
                ("a helmet found twice is one find and one false alarm",),
            ),
            kit.CriterionSpec(
                "machine-learning",
                0.30,
                "Trusts the dashboard.",
                "Fixes one of the two causes.",
                "Finds both ways the numbers were too good and says which matters more.",
                ("recall includes photos with no detections",),
            ),
            kit.CriterionSpec(
                "statistics",
                0.15,
                "Edits that break the metrics.",
                "Fixes the code without checking a number by hand.",
                "Checks precision and recall by hand on a small example.",
                ("tests/test_scoring.py passes",),
            ),
            kit.testing_criterion(0.25),
        ]
    )


PLANTED = [
    "match.match counts every detection that overlaps a true box as correct, so duplicates inflate "
    "precision",
    "metrics.evaluate skips photos with no detections, so their missed helmets never lower recall",
]


def metrics() -> dict[str, float]:
    seen, fair = _scores(honest=False), _scores(honest=True)
    return {
        "dashboard_precision": seen["precision"],
        "dashboard_recall": seen["recall"],
        "precision": fair["precision"],
        "recall": fair["recall"],
    }


def internship() -> Internship:
    people = [
        kit.Person(
            "hana",
            "Hana Kowalczyk",
            "Head of Vision",
            "Warm, direct, busy. Cares what the intern can tell the Friday customer review and "
            "about small, safe changes. Asks 'what do we know, and how sure are we?'. Does not "
            "read code.",
        ),
        kit.Person(
            "diego", "Diego Salvatierra", "Senior Computer Vision Engineer", kit.REVIEWER_PERSONA
        ),
        kit.Person(
            "ruth",
            "Ruth Mbeki",
            "Customer Success Manager",
            "Not technical. Site managers phone her about double alarms and about workers "
            "nobody flagged. Gives specific site stories and counts, not causes.",
        ),
    ]
    return kit.week(
        people,
        ["BS-101", "BS-102", "BS-103"],
        welcome=(
            "Welcome to Brightline! The thing on my mind this week: the dashboard says the "
            "detector is around 90% or better on both measures, and Ruth keeps hearing "
            "otherwise from sites. Diego is your point of contact for the code. Say hi to both."
        ),
        stakeholder=(
            "Hi, Ruth from customer success. A site manager told me she gets two alerts for "
            "the same person, and last week a worker without a helmet was never flagged at "
            "all. Meanwhile the dashboard says we are around 90% or better. Which is right?"
        ),
        nudge=kit.NUDGE,
        summary=(
            "I present to the customer review tomorrow. In a few plain sentences, can you "
            "write to me: can we trust the dashboard, what was wrong, and how sure are you? "
            "Send it as a message in this chat."
        ),
        retro=kit.RETRO,
    )
