# Test-runner — specification

## Purpose
Apply the proposed diff to the SWE-bench instance and run its tests through the **official SWE-bench Docker harness**. Return a structured outcome. **This node does not call an LLM.**

## Inputs (from `DefectState`)
- `instance_id: str`
- `diff: str`

## Outputs (merged into state)
- `test_outcome: TestOutcome` — see schema in `docs/architecture.md`

## Implementation

A thin wrapper around the SWE-bench harness in `src/defect_triage/harness.py`:

1. **Write a predictions file** in the format SWE-bench expects:
```python
{"instance_id": "...", "model_patch": "<diff>", "model_name_or_path": "defect-triage"}
```
One JSONL line per prediction.

2. **Invoke the harness.** Use the `swebench.harness.run_evaluation` Python entrypoint (preferred) or the CLI:
```
python -m swebench.harness.run_evaluation \
  --dataset_name princeton-nlp/SWE-bench_Lite \
  --predictions_path <predictions.jsonl> \
  --max_workers 1 \
  --run_id <run_id>
```
The harness pulls/uses a pre-built Docker image per instance, applies the diff, runs the tests it cares about (`FAIL_TO_PASS` and `PASS_TO_PASS`), and emits a JSON report.

3. **Parse the report.** The harness writes per-run JSON. Read it and populate `TestOutcome`:
   - `passed`: true iff all `FAIL_TO_PASS` tests now pass AND no `PASS_TO_PASS` tests regressed
   - `fail_to_pass_passed`, `fail_to_pass_failed`, `pass_to_pass_failed`: lists from the report
   - `raw_log_path`: path to the per-instance log file the harness produces

4. **Copy artefacts** into `eval/runs/<timestamp>/patch_attempts/<n>.test.log` for the report.

## What this node MUST NOT do
- Run `pytest` (or any test framework) directly. Use the SWE-bench harness.
- Run any test outside Docker. Tests must run in the harness's container per the SWE-bench instance.
- Modify the diff before passing it to the harness — if it's malformed, the harness should fail the instance and we record that.
- Pull/build Docker images outside what the harness manages.

## Error handling
- Harness invocation failures (Docker not running, image pull failure, malformed diff, timeout) must populate `TestOutcome` with `passed=False` and detailed `pass_to_pass_failed` listing the error category. Do not raise — keep the LangGraph run alive so the Critic can route the retry.

## On Day 1
Day 1's checkpoint is "the harness runs one instance successfully." Before any LangGraph work, prove the harness command produces a valid report locally. If it doesn't, fix that first.
