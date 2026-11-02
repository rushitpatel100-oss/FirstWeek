"""The scripted week at Northwind Claims for the demo project (ADR 0023).

Hand-written like the project itself, so the internship works with no model call to build it.
Nothing here gives away a fix: messages say what people noticed and want, never where the bug is."""

from firstweek_core.contracts import Colleague, Internship, InternshipEvent


def internship() -> Internship:
    colleagues = [
        Colleague(
            key="maya",
            name="Maya Okafor",
            role="Engineering Manager",
            persona=(
                "Warm but busy. Cares about what the intern will be able to tell the leadership "
                "team on Friday and about small, safe changes. Asks 'what do we know, and how "
                "sure are we?'. Does not read code."
            ),
        ),
        Colleague(
            key="dev",
            name="Dev Rao",
            role="Tech Lead",
            persona=(
                "Direct and kind. Reads the intern's code carefully, likes small pull requests and "
                "tests that fail for the right reason. Answers with a hint or a question, never "
                "the fix."
            ),
        ),
        Colleague(
            key="sam",
            name="Sam Whitfield",
            role="Customer Support Lead",
            persona=(
                "Not technical. Talks about real customers and the cases the team keeps seeing. "
                "Frustrated that the dashboard says all is well. Gives examples of what customers "
                "experience, not causes."
            ),
        ),
    ]
    events = [
        InternshipEvent(
            day=1,
            kind="message",
            sender="maya",
            text=(
                "Welcome to Northwind! Glad you are here. The one thing on my mind this week: the "
                "dashboard says our assistant cites the right policy clause about 90% of the "
                "time, but Sam's team does not believe it. Dev is your point of contact for the "
                "code. Say hi to both."
            ),
        ),
        InternshipEvent(
            day=1,
            kind="ticket",
            sender="maya",
            ticket="NW-101",
            text="I put NW-101 on your board. Start there. Shout if anything is unclear.",
        ),
        InternshipEvent(
            day=2,
            kind="message",
            sender="sam",
            text=(
                "Hi, I am Sam from support. Yesterday three customers were told they were covered "
                "and the clause the assistant pointed at said nothing of the sort. And lots of "
                "answers come with no clause at all, but I never see those in the numbers. Could "
                "that be it?"
            ),
        ),
        InternshipEvent(
            day=2,
            kind="ticket",
            sender="maya",
            ticket="NW-102",
            text="Sam's point deserves its own ticket: NW-102 is yours.",
        ),
        InternshipEvent(
            day=3,
            kind="message",
            sender="dev",
            text=(
                "Nice progress. Before you finish NW-103: tests are how we make sure this does "
                "not quietly come back. Keep your change small enough that I can review it over "
                "coffee."
            ),
        ),
        InternshipEvent(
            day=3, kind="ticket", sender="dev", ticket="NW-103", text="NW-103 is on your board."
        ),
        InternshipEvent(
            day=4,
            kind="message",
            sender="maya",
            text=(
                "I present to leadership tomorrow. In a few plain sentences, can you write to me: "
                "can we trust the dashboard number, what was wrong, and how sure are you? Send it "
                "as a message in this chat."
            ),
        ),
        InternshipEvent(
            day=5,
            kind="meeting",
            sender="maya",
            text=(
                "Friday retro: what went well, what you would do differently, and what you still "
                "do not know. Then I will write up how the week went."
            ),
        ),
    ]
    return Internship(colleagues=colleagues, events=events)
