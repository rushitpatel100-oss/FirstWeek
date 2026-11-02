// Everything the demo says on behalf of the AI colleagues is written here, ahead of time.
// The live app answers with a model; this static demo has no server, so it replays samples and
// says so on screen. Nothing below names the fix: like the live colleagues, they only point.

export const LINES: Record<string, string[]> = {
  maya: [
    "Thanks for asking. What I need by Thursday is a plain answer: can we trust the dashboard number, and how sure are you?",
    "Start with NW-101 and tell me what you find, even if it is only part of the picture.",
    "I would rather hear 'I found one cause and I am still checking the other' than a confident guess.",
    "Good. Keep changes small and say what you would check next. Dev can review the code.",
  ],
  dev: [
    "Run the tests first and read the one that fails. What do you think it is checking?",
    "Look at how the dashboard decides two clauses are the same. Is that the same as being equal?",
    "Have a look at what happens to rows where the assistant cited nothing, before they reach the metric.",
    "A test that fails on the old code and passes on your fix is worth more than a long explanation.",
  ],
  sam: [
    "The cases I keep seeing are customers told they are covered when the clause says nothing like that.",
    "Lots of answers come back with no clause at all. I never see those reflected in the numbers.",
    "If the assistant stopped citing altogether, would anyone on your side notice?",
    "Anything you can tell me in plain words helps. I do not need the code, just whether to trust the number.",
  ],
};

export function reply(colleague: string, count: number): string {
  const lines = LINES[colleague] ?? ["Let me get back to you on that."];
  return lines[count % lines.length];
}

export function techLeadReview(passed: boolean, hasNewTest: boolean): string {
  if (!passed) {
    return (
      "The tests are failing, so this is not ready yet. Start from the first failure and read what it " +
      "expects against what you get. Two separate things are wrong in the starter, so check that you " +
      "have not fixed only one. Keep each change small enough that I can review it quickly.\n\n" +
      "One question: if the assistant stopped citing anything at all, what would this dashboard say, " +
      "and would anyone notice?"
    );
  }
  const test = hasNewTest
    ? "I can see you added a test of your own, which is exactly what stops this coming back."
    : "NW-103 asks for a regression test of your own under tests/ and I do not see one yet: add one that fails on the original code.";
  return (
    "Nice work: the tests pass, so the dashboard now agrees with a hand count. Matching on equality " +
    "removes the prefix problem, and keeping uncited rows in the count means a silent assistant can " +
    "no longer look good.\n\n" +
    test +
    "\n\nOne question: what should happen if a row is missing its expected clause? Right now nothing " +
    "would tell us."
  );
}

export type Verdict = {
  summary: string;
  skills: { skill: string; score: number; evidence: string }[];
  wentWell: string[];
  toWorkOn: string[];
  nextStep: string;
};

export function verdict(passed: boolean, hasNewTest: boolean, messages: number): Verdict {
  const talked = messages > 0;
  return {
    summary: passed
      ? "A steady week. The dashboard number now agrees with a hand count and the given tests pass."
      : "An unfinished week. The tests still fail, so the dashboard number cannot be trusted yet.",
    skills: [
      {
        skill: "LLM evaluation",
        score: passed ? 4 : 2,
        evidence: passed
          ? "The final test run passes, so both causes of the inflated number were dealt with."
          : "The final test run still fails, so at least one cause of the inflated number remains.",
      },
      {
        skill: "Python",
        score: passed ? 4 : 3,
        evidence: passed ? "Small changes with no test regressions." : "The code runs, but the tests do not pass.",
      },
      {
        skill: "Hallucination mitigation",
        score: passed ? 3 : 2,
        evidence: passed
          ? "Uncited answers now count as wrong; the reasoning was not written down."
          : "Uncited answers are still being left out of the count.",
      },
      {
        skill: "Testing",
        score: hasNewTest ? 4 : 2,
        evidence: hasNewTest
          ? "A new test file was added under tests/."
          : "No regression test of your own was added under tests/.",
      },
    ],
    wentWell: [passed ? "The given tests pass" : "You ran the tests early", talked ? "You asked colleagues for context" : "You kept changes small"],
    toWorkOn: [hasNewTest ? "Explain the findings in plain words" : "Add a test that fails on the old code", talked ? "Say how sure you are" : "Talk to colleagues sooner"],
    nextStep: "Write a short plain-English update for Maya: can we trust the number, what was wrong, and how sure are you?",
  };
}
