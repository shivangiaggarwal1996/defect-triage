"""Thin wrapper around the official SWE-bench Docker harness.

This is the ONLY place that executes tests. Do not hand-roll a sandbox (CLAUDE.md section 6).

----------------------------------------------------------------------------------
Harness output path schema (verified Day 1, swebench 4.1.0)
----------------------------------------------------------------------------------
Invocation:
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
