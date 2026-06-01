# Day 1 — Mon 2 Jun — Setup + SWE-bench harness sanity check

**Time budget:** 3 hours.
**Today's prime directive:** prove the SWE-bench Docker harness can run **one** Flask instance end-to-end on this machine. If that fails, nothing downstream works. Spend the full 3 hours on it if you must.

## Goal

Project skeleton in place, dependencies installed, environment configured, and one SWE-bench Lite Flask instance runs to completion through the official harness, producing a valid report JSON.

## Prerequisites

- macOS, Docker Desktop running (`docker info` works).
- Python 3.11 available.
- Anthropic API key in hand.
- Langfuse account created (free cloud account at langfuse.com), public + secret key in hand.

## Step-by-step

1. **Initialize the Python environment.**
   - Create `.venv` in the project root using Python 3.11. Activate it.
   - Confirm the `pyproject.toml` in the repo lists the milestone dependencies. Run `pip install -e .`.

2. **Create the package skeleton.** Create empty `__init__.py` and stub files under `src/defect_triage/` matching the layout in `CLAUDE.md` section 5. Stubs should import cleanly. `nodes/*.py` can be `pass` for now.

3. **Wire `.env`.** Copy `.env.example` to `.env`. Fill in `ANTHROPIC_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`.

4. **Pick the eval slice.** Browse the SWE-bench Lite dataset on Hugging Face (princeton-nlp/SWE-bench_Lite) and filter for Flask. Pick 10 instance IDs that look tractable (short problem statements, not too many files touched). Write them to `eval/instances.txt`, one per line. Pick a single one (e.g., `flask__flask-5014`) as today's smoke-test target.

5. **Prove the harness works on that one instance.** Build a minimal predictions JSONL with a no-op patch (empty string for `model_patch`) and run:
   ```
   python -m swebench.harness.run_evaluation \
     --dataset_name princeton-nlp/SWE-bench_Lite \
     --predictions_path eval/smoke_predictions.jsonl \
     --max_workers 1 \
     --run_id smoke-test-day1
   ```
   The harness should pull the Docker image (this can take 5–10 minutes the first time), attempt the patch (which will fail because the patch is empty — that's fine), and emit a report JSON. **You are checking that the harness runs without crashing, not that the patch succeeds.**

6. **Locate the report file.** Find the harness output JSON for that instance and confirm you can parse it. Make a note of its path schema in `src/defect_triage/harness.py` (or in a comment for now) — Day 3 needs it.

7. **Sanity-check Langfuse.** Send one test trace from a small Python script (`langfuse.client.event(...)` or similar from their quickstart). Confirm it appears in the Langfuse UI.

## Definition of Done

- `pip install -e .` succeeds without errors.
- `defect-triage --help` runs (even if it only shows a placeholder).
- The harness completes one instance and writes a parseable report JSON.
- One test event appears in your Langfuse cloud dashboard.
- `eval/instances.txt` exists with 10 Flask instance IDs.

## Resources for today

- SWE-bench harness "Evaluation" section: https://github.com/princeton-nlp/SWE-bench (README, scroll to Evaluation).
- SWE-bench Lite on Hugging Face: https://huggingface.co/datasets/princeton-nlp/SWE-bench_Lite (use the dataset preview to browse Flask instances).
- Langfuse Python quickstart: https://langfuse.com/docs (the "Get Started → Python" page).

## Common pitfalls

- **Docker image pull is slow** on the first instance — that's normal, ~5–10 min per repo. Don't kill it.
- **Apple Silicon (M-series)**: SWE-bench images are linux/amd64. Docker Desktop handles this via emulation but it's slower. Live with it for the milestone.
- **`pip install swebench` is the package, but the harness module is invoked as `python -m swebench.harness.run_evaluation`** — make sure both work.
- **Free Langfuse cloud rate limits exist** but won't matter at our trace volume.

## What NOT to do today

- Don't start LangGraph. Don't write any node logic. Don't touch Claude. The single thing today produces is "the harness runs."
- Don't optimize anything. Get to working, not pretty.
- Don't expand the instance slice past 10.
