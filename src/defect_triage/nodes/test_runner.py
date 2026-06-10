"""Test-runner node: run the candidate patch through the SWE-bench harness.

Read docs/agents/test-runner.md before implementing. Delegates to harness.py.

WHERE THIS SITS IN THE PIPELINE
-------------------------------
    ... -> Patch-writer -> [Test-runner] -> END   (Day 4 adds: -> Critic on failure)

The Patch-writer just produced a unified ``diff``. This node is the bridge between that
diff and the verdict: it hands the diff to the SWE-bench Docker harness, gets back a
pass/fail result, and records it. It is deliberately THIN — all the real work (Docker,
applying the patch, running tests, parsing the report) lives in harness.run_instance.

WHAT THIS NODE DOES
-------------------
  1. Build a deterministic ``run_id`` for this attempt so harness logs never collide.
  2. Call :func:`harness.run_instance` with the instance id + the diff.
  3. Copy the harness's per-instance log into the run artefact tree as
     ``patch_attempts/<n>.test.log`` (so it sits next to the matching ``<n>.diff``).
  4. Return ``test_outcome`` for LangGraph to merge into the state.

WHAT IT DOES NOT DO
-------------------
- It makes NO LLM call (no Langfuse generation here — it is pure orchestration).
- It NEVER raises: harness.run_instance already converts every failure into a
  ``passed=False`` outcome, so the graph stays alive for the Critic to route a retry.
- It does NOT run pytest or touch Docker directly — only through the harness.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..harness import run_instance
from ..state import DefectState


def _copy_log(state: DefectState, attempt_no: int, raw_log_path: str) -> None:
    """Copy the harness log into ``patch_attempts/<n>.test.log`` under the run dir.

    The harness writes its log deep inside ``logs/run_evaluation/<run_id>/...``. For the
    report and for easy debugging we want it sitting right next to the diff it belongs
    to (``<n>.diff`` and ``<n>.test.log`` side by side). This copies it there.

    It is defensive on purpose — any of these makes it a silent no-op rather than an
    error (we never want log bookkeeping to crash a run):
      - no ``run_dir`` in state (e.g. a unit test calling the node directly),
      - an empty ``raw_log_path`` (harness failed before writing a log),
      - the log file not actually existing on disk.

    Args:
        state: shared pipeline state (read for ``run_dir``).
        attempt_no: which patch attempt this is — names the copied file.
        raw_log_path: path to the harness log, as returned in the TestOutcome.
    """
    run_dir = state.get("run_dir")
    if not run_dir or not raw_log_path:
        return
    src = Path(raw_log_path)
    if not src.exists():
        return
    attempts_dir = Path(run_dir) / "patch_attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, attempts_dir / f"{attempt_no}.test.log")


def test_runner(state: DefectState) -> dict:
    """Run the current ``diff`` through the harness and record the outcome.

    Reads ``instance_id``, ``diff`` and ``patch_attempts`` (the attempt number, used to
    name the run and the copied log). Writes ``test_outcome``.

    Args:
        state: the shared pipeline state; ``diff`` is expected to be populated by the
            Patch-writer (it may be empty/invalid — the harness handles that).

    Returns:
        ``{"test_outcome": TestOutcome}`` for LangGraph to merge into the state. On
        Day 4 the conditional edge after this node reads
        ``test_outcome["passed"]`` to decide END vs. Critic.
    """
    instance_id = state["instance_id"]
    # patch_attempts was just incremented by the Patch-writer, so it is THIS attempt's
    # number. Default to 1 so the node is still callable in isolation.
    attempt_no = state.get("patch_attempts", 1)

    # A deterministic, attempt-scoped run id. The harness uses this as a log directory
    # name, so giving each attempt its own id keeps attempt 1's logs from clobbering
    # attempt 2's (spec convention: "<instance_id>__attempt_<n>").
    run_id = f"{instance_id}__attempt_{attempt_no}"

    # The one real call — everything Docker-related happens inside here, and it never
    # raises (failures come back as passed=False with a diagnostic).
    outcome = run_instance(instance_id, state.get("diff", ""), run_id)

    # Archive the harness log next to the diff for this attempt.
    _copy_log(state, attempt_no, outcome.get("raw_log_path", ""))

    result: dict = {"test_outcome": outcome}
    # Set the terminal status on success here, at the moment we route to END. (On
    # failure we leave final_status unset — the Critic sets "exhausted_retries" if the
    # retry budget runs out, otherwise the loop continues.)
    if outcome.get("passed"):
        result["final_status"] = "resolved"
    return result


# Command to validate this file (no Docker — monkeypatches the harness call):
# ./bin/python -c "
# import src.defect_triage.nodes.test_runner as T
# T.run_instance = lambda iid, diff, run_id: {'passed': True, 'fail_to_pass_passed': ['t'], 'fail_to_pass_failed': [], 'pass_to_pass_failed': [], 'raw_log_path': ''}
# out = T.test_runner({'instance_id': 'x', 'diff': 'd', 'patch_attempts': 1})
# assert out['test_outcome']['passed'] is True, out
# print('test_runner.py OK — passed:', out['test_outcome']['passed'])
# "
