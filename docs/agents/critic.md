# Critic — specification

## Purpose
When the Test-runner reports failure, read the failure signal and produce short, actionable feedback that the Patch-writer can use on its next attempt. Feedback should name a specific hypothesis ("the off-by-one is on line X because Y"), not a vague observation ("the patch didn't work").

## Inputs (from `DefectState`)
- `problem_statement: str`
- `diff: str` — the patch that just failed
- `test_outcome: TestOutcome` — the failure signal
- The tail of the test log (read from `test_outcome["raw_log_path"]`, last ~80 lines)

## Outputs (merged into state)
- `critic_feedback: str` — plain-text, < 200 words, actionable

## Algorithm

1. **Read the log tail.** Last ~80 lines of the harness log — that's where the actual test failures live (assertions, tracebacks). Don't send the whole log to Claude; it's noisy and burns tokens.

2. **Categorize failure if possible** (heuristic, before the LLM call):
   - `fail_to_pass_failed` non-empty → fix didn't actually fix the bug
   - `pass_to_pass_failed` non-empty → fix introduced a regression
   - Both empty but `passed == False` → harness/diff-application error
   This category goes into the prompt as a hint.

3. **Ask Claude for a hypothesis.** Send: the problem statement, the diff, the failure category, the log tail. Ask for:
   - One sentence stating what likely went wrong.
   - One concrete suggestion for the next attempt (which line, what change).
   - Constraint: < 200 words, no fluff.

4. **Write to state and to `eval/runs/.../critic/<n>.txt`.**

## Prompt sketch

```
A patch attempt failed. Read the bug report, the patch, and the test failure log,
then explain in under 200 words what likely went wrong and what to try next.

Bug report:
{problem_statement}

The patch that just failed:
```
{diff}
```

Failure category: {category}

Last 80 lines of the test log:
```
{log_tail}
```

Write:
1. ONE sentence: the most likely cause of the failure.
2. ONE concrete next step: which line(s) to change and how.

Do not restate the bug report. Do not apologize. Be specific.
```

## What this node MUST NOT do
- Generate a new diff. That's the Patch-writer's job. The Critic outputs only feedback text.
- Send the full test log to Claude.
- Speculate beyond what the log supports.
- Fire if `test_outcome["passed"] == True` — the conditional edge should not route here on success.

## Bounded retries
The Critic does not enforce the retry cap — the **graph** does, in the conditional edge after Critic. The Critic just produces feedback; the graph decides whether to loop.
