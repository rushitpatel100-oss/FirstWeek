"""The terminal side of the review: show a claim, read a keypress, record the answer.

The loops take `ask` and `say` so tests can drive them without a keyboard."""

import textwrap
import uuid
from collections.abc import Callable

from firstweek_research import review as rv

Ask = Callable[[str], str]
Say = Callable[[str], None]


def _wrap(text: str, indent: str = "   ") -> str:
    return textwrap.fill(text, 96, initial_indent=indent, subsequent_indent=indent)


def show_claim(claim: rv.ReviewClaim, say: Say, *, with_verdict: bool = True) -> None:
    say(f"\n[{claim.section}] confidence {claim.confidence:.2f}")
    say(_wrap(claim.text))
    if with_verdict:
        say(f"   verifier: {claim.verification}")
    for q in claim.quotes:
        say(_wrap(f'[{q.tier}] {q.publisher}: "{q.text}"', "   > "))


def review_report(report_id: uuid.UUID, ask: Ask, say: Say) -> None:
    """Walk through the claims with no decision. a = accept, r = reject (with a reason),
    s = skip for now, q = stop. Decisions are saved as you go."""
    claims = rv.load_claims(report_id)
    todo = [c for c in claims if c.review == "pending"]
    say(f"{len(claims)} claims, {len(todo)} waiting for a decision.")
    for i, claim in enumerate(todo, start=1):
        show_claim(claim, say)
        while True:
            answer = ask(f"({i}/{len(todo)}) [a]ccept  [r]eject  [s]kip  [q]uit > ").strip().lower()
            if answer in {"a", "accept"}:
                rv.decide(claim.id, "accepted")
            elif answer in {"r", "reject"}:
                note = ask("   Why? (one line) > ")
                try:
                    rv.decide(claim.id, "rejected", note)
                except rv.ReviewError as exc:
                    say(f"   {exc}")
                    continue
            elif answer in {"s", "skip"}:
                pass
            elif answer in {"q", "quit"}:
                say(_summary(report_id))
                return
            else:
                continue
            break
    say(_summary(report_id))


def _summary(report_id: uuid.UUID) -> str:
    claims = rv.load_claims(report_id)
    counts = {k: sum(c.review == k for c in claims) for k in ("accepted", "rejected", "pending")}
    problems = rv.publish_problems(report_id)
    tail = "Ready to publish: `make publish-report`." if not problems else "\n".join(problems)
    return (
        f"\nAccepted {counts['accepted']}, rejected {counts['rejected']}, "
        f"waiting {counts['pending']}.\n{tail}"
    )


def spot_check(count: int, ask: Ask, say: Say, *, seed: int | None = None) -> None:
    """Judge the verifier by hand: do the quotes really back the claim? The verifier's own
    verdict is hidden so it can't sway the answer."""
    sample = rv.spot_check_sample(count, seed=seed)
    if not sample:
        say("Every claim has been spot-checked already.")
    for i, claim in enumerate(sample, start=1):
        show_claim(claim, say, with_verdict=False)
        while True:
            answer = ask(
                f"({i}/{len(sample)}) Do the quotes back the whole claim? [y]es [n]o [q]uit > "
            )
            answer = answer.strip().lower()
            if answer in {"y", "yes", "n", "no"}:
                rv.record_spot_check(claim.id, answer.startswith("y"))
                break
            if answer in {"q", "quit"}:
                say(_spot_summary())
                return
    say(_spot_summary())


def _spot_summary() -> str:
    s = rv.spot_check_status()
    verdict = "passed" if s.passed else "not passed yet"
    return (
        f"\nSpot-check: {s.checked} of {s.target} done, {s.wrong} judged wrong "
        f"({s.wrong_share:.0%}); gate {verdict}."
    )
