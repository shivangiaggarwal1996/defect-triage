"""Thin wrapper around the official SWE-bench Docker harness.

This is the ONLY place in the project that executes tests. We never hand-roll a
sandbox or call ``pytest`` ourselves (CLAUDE.md section 6) — every test run goes
through SWE-bench's official Docker harness so results are trustworthy and reproducible.

WHAT THE HARNESS ACTUALLY DOES (the 30-second version)
------------------------------------------------------
Given a patch (a unified diff) for one SWE-bench instance, the harness:
  1. spins up the pre-built Docker image for that exact bug/commit,
  2. applies our diff inside the container,
  3. runs the two test sets SWE-bench cares about —
        FAIL_TO_PASS  = tests that were broken by the bug and should now pass,
        PASS_TO_PASS  = tests that already passed and must NOT regress,
  4. writes a JSON report saying whether the bug is "resolved".
We read that report and translate it into our own ``TestOutcome`` dict.

----------------------------------------------------------------------------------
Harness output path schema (verified Day 1, swebench 4.1.0)
----------------------------------------------------------------------------------
Invocation (we call the Python entrypoint directly rather than the CLI):
    python -m swebench.harness.run_evaluation \
        --dataset_name princeton-nlp/SWE-bench_Lite \
        --predictions_path <preds.jsonl> \
        --max_workers 1 \
        --run_id <RUN_ID>

Predictions JSONL — one object per line, fields:
    {"instance_id": <id>, "model_name_or_path": <MODEL>, "model_patch": <unified diff str>}
    NOTE: an empty "model_patch" is SKIPPED, not run (reported under "empty_patch_ids").
          To exercise Docker end-to-end you must submit a non-empty patch.

Two artefacts are written (paths relative to the CWD the harness ran in):

1. Summary report (cwd root):
       <MODEL>.<RUN_ID>.json
   Top-level counts + id lists: resolved_ids / unresolved_ids / error_ids /
   empty_patch_ids / completed_ids, plus schema_version.

2. Per-instance detail (the one Day 3 reads for pass/fail):
       logs/run_evaluation/<RUN_ID>/<MODEL>/<INSTANCE_ID>/report.json
   Keyed by instance_id; fields:
       patch_successfully_applied: bool
       resolved: bool                       <-- the verdict that drives the graph edge
       tests_status: {FAIL_TO_PASS, PASS_TO_PASS, FAIL_TO_FAIL, PASS_TO_FAIL}
                     each -> {"success": [...], "failure": [...]}
   Sibling files in that dir: patch.diff, eval.sh, run_instance.log, test_output.txt
----------------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .state import TestOutcome

# --- Constants -------------------------------------------------------------------
# The dataset + split the milestone runs against. Must match what the harness expects.
DATASET_NAME = "princeton-nlp/SWE-bench_Lite"
DATASET_SPLIT = "test"

# The label we attach to every prediction. It is also used by the harness as a
# DIRECTORY NAME in the log tree (logs/run_evaluation/<RUN_ID>/<MODEL>/...), so it must
# be filesystem-safe — keep it as a simple slug, no slashes.
MODEL_NAME = "defect-triage"

# Where the harness writes its per-instance artefacts, relative to the CWD it runs in.
# This mirrors swebench.harness.constants.RUN_EVALUATION_LOG_DIR; we re-declare it here
# so we can compute the report path without importing the harness just to read a string.
LOG_ROOT = Path("logs/run_evaluation")


# --- Helpers ---------------------------------------------------------------------

def _error_outcome(message: str, raw_log_path: str = "") -> TestOutcome:
    """Build a ``passed=False`` outcome that carries a diagnostic instead of raising.

    The test-runner spec is strict: harness problems (Docker down, image pull failed,
    malformed diff, timeout, no report) must NOT raise — that would kill the LangGraph
    run and prevent the Critic from retrying. Instead we return a normal ``TestOutcome``
    with ``passed=False`` and stash the *reason* in ``pass_to_pass_failed`` as a
    ``harness_error: ...`` string, so the failure cause is visible in the saved state
    and to the Critic later.

    Args:
        message: short machine-ish reason, e.g. "empty_diff" or "DockerException: ...".
        raw_log_path: path to the harness log if one exists, else "".

    Returns:
        A fully-formed ``TestOutcome`` dict describing the failure.
    """
    return TestOutcome(
        passed=False,
        fail_to_pass_passed=[],
        fail_to_pass_failed=[],
        pass_to_pass_failed=[f"harness_error: {message}"],
        raw_log_path=raw_log_path,
    )


def _report_dir(run_id: str, instance_id: str) -> Path:
    """Compute the harness's per-instance output directory for this run.

    Layout: ``logs/run_evaluation/<run_id>/<MODEL_NAME>/<instance_id>/`` — this is where
    the harness drops ``report.json``, ``run_instance.log``, ``test_output.txt``, etc.
    """
    return LOG_ROOT / run_id / MODEL_NAME / instance_id


def _parse_report(report_path: Path, instance_id: str, run_log: Path) -> TestOutcome:
    """Translate the harness's ``report.json`` into our :class:`TestOutcome`.

    The report is keyed by instance_id. We pull out the resolved verdict and the
    per-bucket test breakdown (each bucket is ``{"success": [...], "failure": [...]}``).

    One important special case: if the patch did not even apply
    (``patch_successfully_applied == False``), the test buckets are meaningless. We
    report that distinctly as a ``patch_did_not_apply`` harness error, because the
    Critic should react to "your diff was malformed" very differently from "your fix
    was wrong but applied cleanly".

    Args:
        report_path: path to the harness ``report.json`` (already known to exist).
        instance_id: the instance whose entry we read out of the report.
        run_log: path to ``run_instance.log`` (for ``raw_log_path``; may not exist).

    Returns:
        A ``TestOutcome``: ``passed`` is the harness's ``resolved`` verdict, plus the
        FAIL_TO_PASS / PASS_TO_PASS breakdowns and a pointer to the log.
    """
    report = json.loads(report_path.read_text())
    inst = report.get(instance_id, {})
    tests_status = inst.get("tests_status", {})
    fail_to_pass = tests_status.get("FAIL_TO_PASS", {})
    pass_to_pass = tests_status.get("PASS_TO_PASS", {})

    # If the diff didn't apply, the test results below are not trustworthy — surface
    # that as its own failure category rather than reporting empty test lists.
    if not inst.get("patch_successfully_applied", False):
        return _error_outcome(
            "patch_did_not_apply",
            str(run_log) if run_log.exists() else "",
        )

    return TestOutcome(
        # "resolved" == all FAIL_TO_PASS now pass AND no PASS_TO_PASS regressed.
        # This is the single boolean that will drive the Day-4 pass/fail graph edge.
        passed=bool(inst.get("resolved", False)),
        fail_to_pass_passed=list(fail_to_pass.get("success", [])),  # broken tests now fixed
        fail_to_pass_failed=list(fail_to_pass.get("failure", [])),  # still broken
        pass_to_pass_failed=list(pass_to_pass.get("failure", [])),  # regressions we caused
        raw_log_path=str(run_log) if run_log.exists() else str(report_path),
    )


# --- The one public function -----------------------------------------------------

def run_instance(instance_id: str, diff: str, run_id: str) -> TestOutcome:
    """Run one SWE-bench instance's tests against ``diff`` via the official harness.

    This is the entire public surface of the module. The flow is:
      1. Guard against an empty diff (the harness would silently SKIP it, which would
         masquerade as a pass — so we fail it explicitly here).
      2. Write a one-line predictions JSONL the harness can read.
      3. Call ``swebench.harness.run_evaluation.main(...)`` programmatically with a
         single worker, scoped to just this one instance.
      4. Read the per-instance ``report.json`` the harness emitted and map it to a
         ``TestOutcome`` via :func:`_parse_report`.

    CRUCIAL CONTRACT: this function NEVER raises. Docker not running, an image pull
    failure, a malformed diff, a timeout, or a missing report all come back as a
    ``passed=False`` outcome whose ``pass_to_pass_failed`` carries a ``harness_error:``
    diagnostic. Keeping the graph alive is the whole point — the Critic decides what to
    do with the failure (test-runner spec, "Error handling").

    Args:
        instance_id: SWE-bench Lite instance ID, e.g. "pallets__flask-5063".
        diff: the unified diff to apply, as a single string. Empty/whitespace-only is
            treated as a failure (see step 1 above).
        run_id: identifies this harness run; the harness also uses it as a log
            directory name. Convention from the spec: ``f"{instance_id}__attempt_{n}"``,
            so each patch attempt gets its own isolated log folder.

    Returns:
        A :class:`TestOutcome` dict — ``passed`` plus the FAIL_TO_PASS / PASS_TO_PASS
        breakdown and a filesystem path to the harness log for that run.
    """
    # 1. Empty-diff guard. The harness reports empty patches under "empty_patch_ids"
    #    and never runs Docker for them, which would look like a silent no-op. Fail fast.
    if not diff or not diff.strip():
        return _error_outcome("empty_diff")

    # Pre-compute where the harness will put this run's log + report so we can read
    # them afterwards (and reference the log even on the error paths below).
    run_log = _report_dir(run_id, instance_id) / "run_instance.log"
    report_path = _report_dir(run_id, instance_id) / "report.json"

    try:
        # Import lazily, INSIDE the function. Importing the harness is heavy and pulls
        # in Docker client code; deferring it means just importing this module (e.g. in
        # a unit test that monkeypatches run_instance) stays cheap and side-effect-free.
        from swebench.harness.run_evaluation import main as run_evaluation

        # 2. Write the single prediction the harness will read. We use a throwaway temp
        #    file because the harness only wants a path to a JSONL; we don't need to
        #    keep it (the diff itself is already archived under patch_attempts/<n>.diff).
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            json.dump(
                {
                    "instance_id": instance_id,
                    "model_name_or_path": MODEL_NAME,
                    "model_patch": diff,
                },
                f,
            )
            f.write("\n")  # JSONL = one JSON object per line
            predictions_path = f.name

        # 3. Invoke the harness. We pass the same defaults the CLI uses, but pinned to a
        #    single worker and just this one instance. namespace="swebench" tells the
        #    harness to pull the official PRE-BUILT images from Docker Hub instead of
        #    building them locally (much faster; confirmed working on Day 1).
        run_evaluation(
            dataset_name=DATASET_NAME,
            split=DATASET_SPLIT,
            instance_ids=[instance_id],   # only run this one bug
            predictions_path=predictions_path,
            max_workers=1,                # one at a time for the milestone
            force_rebuild=False,          # reuse cached images
            cache_level="env",            # keep env images, drop instance images after
            clean=False,
            open_file_limit=4096,
            run_id=run_id,                # also the log directory name
            timeout=1800,                 # 30 min per instance, the harness default
            namespace="swebench",         # use the official pre-built images
            rewrite_reports=False,
            modal=False,                  # local Docker, not Modal cloud
            instance_image_tag="latest",
            env_image_tag="latest",
            report_dir=".",
        )
    except Exception as exc:  # noqa: BLE001 — deliberate catch-all; never kill the graph
        # Any harness/Docker failure becomes a structured outcome, not a crash.
        return _error_outcome(
            f"{type(exc).__name__}: {exc}",
            str(run_log) if run_log.exists() else "",
        )

    # 4. The harness ran. If it still produced no report, it usually means a build/eval
    #    error it logged internally rather than raised. Treat that as a failure too.
    if not report_path.exists():
        return _error_outcome(
            "no_report_produced",
            str(run_log) if run_log.exists() else "",
        )

    # Happy path: parse the report into our TestOutcome.
    return _parse_report(report_path, instance_id, run_log)


# Command to validate this file (no Docker needed — exercises the import + empty-diff path):
# ./bin/python -c "
# from src.defect_triage.harness import run_instance
# out = run_instance('x__y-1', '', 'x__y-1__attempt_1')
# assert out['passed'] is False
# assert out['pass_to_pass_failed'][0].startswith('harness_error: empty_diff'), out
# print('harness.py OK — empty-diff path:', out['pass_to_pass_failed'][0])
# "
