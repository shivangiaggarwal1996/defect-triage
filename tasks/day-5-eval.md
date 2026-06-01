# Day 5 — Fri 6 Jun — Eval run + code freeze

**Time budget:** 3 hours.
**Today's prime directive:** run the full pipeline across all 10 instances, compute a baseline resolution rate, and **stop coding by end of day**. Tomorrow is report and submission only.

## Goal

- `defect-triage eval --instances eval/instances.txt --out eval/results.json` runs the pipeline over all chosen instances.
- `eval/results.json` contains per-instance outcomes and aggregate metrics.
- Langfuse traces for all 10 runs are captured.
- **Code freeze tonight** — no more feature work after the eval finishes.

## Prerequisites from Day 4

- One instance runs end-to-end with the retry edge.
- All four nodes (Localizer, Patch-writer, Test-runner, Critic) work.

## Step-by-step

1. **Implement `defect-triage eval`** in `src/defect_triage/cli.py`:
   - Reads `eval/instances.txt`.
   - For each instance: load, run the graph, capture the final state, on any exception record `final_status="errored"` and continue.
   - Writes a single `eval/results.json` with:
     ```json
     {
       "summary": {
         "total": 10,
         "resolved": <n>,
         "exhausted_retries": <n>,
         "errored": <n>,
         "resolution_rate": 0.xx
       },
       "instances": [ {"instance_id": ..., "final_status": ..., "attempts": ..., "top_candidate_file": ..., ...}, ... ]
     }
     ```

2. **Run the slice.** Kick it off. This takes time — the harness needs to apply diffs and run tests in Docker for each instance, plus Claude calls per node per attempt. Budget ~10–20 min per instance worst case, so 2–4 hours wall-clock; you can do other things while it runs.

3. **Sanity-check the results.** Open `eval/results.json` and a few `eval/runs/.../state.json` by eye. Look for:
   - Any instance that resolved — confirm it actually flipped fail→pass tests in the harness log.
   - Any "errored" instances — diagnose if it's a quick fix; otherwise leave it and document in the report.
   - Localizer hit-rate by eye: in how many instances was the true buggy file in the top 5? You can compute this against the SWE-bench gold patch — extract the files modified in the gold patch and check overlap with `candidates`.

4. **Add a basic Hit@1 / Hit@5 calculation** (only if time allows) — small script that compares `candidates` against the gold patch's modified files.

5. **CODE FREEZE.** Once the eval run is done and results.json is written, **stop editing source code.** Anything not working tonight is a "Phase 2 / known limitation" line in tomorrow's report.

## Definition of Done

- `eval/results.json` exists with the full summary.
- Per-instance artefact directories are populated.
- You can name the resolution rate out loud (it will probably be low — that's honest and fine).
- Code is in a clean state — commit and push.

## Resources for today

- The SWE-bench paper (arXiv:2310.06770) — read sections 3 and 4 only, for how "resolved" is defined. You'll cite this tomorrow.

## Common pitfalls

- **Long Docker pulls when the harness encounters a new repo** — Flask only is fine, but if any of your 10 instances accidentally include another repo, that's a fresh image. Re-check `eval/instances.txt` is all Flask.
- **Token cost** — 10 instances × up to 3 attempts × multiple LLM calls per attempt can hit ~$10–20 in Claude usage. Acceptable.
- **Instance timeouts** — the harness has its own timeout per instance. Don't fight it; let timeouts mark the instance errored and move on.

## What NOT to do today

- Don't add features. Don't refactor. Don't tune prompts mid-eval.
- Don't expand the slice past 10.
- Don't start the report — that's tomorrow's job. You'll write better with a night's sleep on the results.

## End-of-day check

Before you stop:

- [ ] `eval/results.json` exists and is parseable.
- [ ] `git status` is clean (committed).
- [ ] You know your resolution rate, even if it's 1/10.
- [ ] Tomorrow's deliverables are clear: report, slides, demo recording, package, submit.
