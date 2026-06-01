# Day 3 — Wed 4 Jun — Patch-writer + Test-runner — close the loop

**Time budget:** 3 hours.
**Today's prime directive:** one defect goes locate → patch → test on the SWE-bench harness, end to end. Green or red doesn't matter — the loop must be closed.

## Goal

- Patch-writer node implemented per `docs/agents/patch-writer.md`.
- Test-runner node implemented per `docs/agents/test-runner.md`.
- The graph is now: `Intake → Localizer → (Prioritizer passthrough) → Patch-writer → Test-runner → END`.
- A run produces `state.json` with `diff` and `test_outcome` populated.

## Prerequisites from Day 2

- Localizer returns sensible candidates on one instance.
- LLM wrapper traces via Langfuse.

## Step-by-step

1. **Implement `src/defect_triage/nodes/prioritizer.py`** as a milestone passthrough:
   - Set `priority_rank = 0`.
   - Add a TODO docstring referencing `docs/milestone-plan.md` and the deferred blast-radius work.
   - That's it.

2. **Implement `src/defect_triage/nodes/patch_writer.py`** per the spec:
   - Read the top candidate's file from the checked-out repo.
   - Build the prompt (include `critic_feedback` if present in state).
   - Call Claude via `llm.py`.
   - Validate with `unidiff.PatchSet`. On invalid, one internal retry with the validation error.
   - Write `patch_attempts/<n>.diff` to the run artefact dir.
   - Increment `patch_attempts`.

3. **Implement `src/defect_triage/harness.py`** — the thin wrapper:
   - One function `run_instance(instance_id: str, diff: str, run_id: str) -> TestOutcome`.
   - Writes a predictions JSONL, invokes the SWE-bench harness via the Python entrypoint (preferred) or subprocess, parses the resulting report JSON.
   - Returns a `TestOutcome` dict.
   - Catches harness invocation errors and returns a `passed=False` outcome with diagnostic info — never raises.

4. **Implement `src/defect_triage/nodes/test_runner.py`** — calls `harness.py`, populates `state["test_outcome"]`, copies the harness log into `eval/runs/.../patch_attempts/<n>.test.log`.

5. **Wire the graph** in `src/defect_triage/graph.py`:
   ```
   intake → localizer → prioritizer → patch_writer → test_runner → END
   ```
   Still no conditional edges today — Day 4 adds those.

6. **End-to-end check.** Run on one instance. The run should now produce:
   - `state.json` with `diff` and `test_outcome` populated.
   - `patch_attempts/1.diff`.
   - `patch_attempts/1.test.log`.
   - A Langfuse trace with four spans now visible.
   The harness will probably report `passed=False` on a first attempt — that is expected and fine. The win today is that the pipeline ran from input to harness output.

## Definition of Done

- `defect-triage run --instance <id>` runs the four nodes without error.
- `state.json` has `diff` (a non-empty string) and `test_outcome` (a dict with `passed: bool`).
- The harness log is on disk in the artefact directory.
- Langfuse trace shows the four-node run.

## Resources for today

- `unidiff` README: https://github.com/matiasb/python-unidiff (10 min).
- SWE-bench Python harness entrypoint: scan the source of `swebench/harness/run_evaluation.py` in the repo, look at how it's called programmatically.
- Refresher on LangGraph: LangChain Academy Module 2 if anything from Day 2 is shaky.

## Common pitfalls

- **Diffs from Claude often miss the trailing newline** — `unidiff` is picky. Append `\n` if missing.
- **Claude wraps diffs in ```diff fences** — strip them.
- **Harness JSON report path** depends on `run_id` — be deterministic about run IDs (`f"{instance_id}__attempt_{n}"` is a reasonable convention).
- **First harness run downloads the image** — budget time if you swap to a new instance.

## What NOT to do today

- Don't add the Critic or the retry edge. Tomorrow.
- Don't write a custom sandbox. Harness only.
- Don't open a PR. Phase 2.
- Don't run on more than one instance today — Friday is for the slice.
