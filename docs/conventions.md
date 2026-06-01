# Conventions

Short list. Follow exactly.

## Python style
- Python 3.11 syntax. Use modern type hints (`list[str]`, `dict[str, int]`, `X | None`).
- Type-hint every public function. Add a one-line docstring describing inputs/outputs.
- Use `from __future__ import annotations` at the top of every file in `src/defect_triage/`.
- Format with `ruff format` (line length 100). Lint with `ruff check`.
- Use `pathlib.Path` for all paths. Never raw `os.path` strings.

## File layout
- One concept per file. Nodes live in `src/defect_triage/nodes/`, one file per node.
- The LangGraph wiring lives in exactly one place: `src/defect_triage/graph.py`.
- The Claude wrapper lives in exactly one place: `src/defect_triage/llm.py`. **No file may call the Anthropic SDK directly.** If you need a Claude call, go through `llm.py` so Langfuse instrumentation is guaranteed.

## State
- The only mutable shared structure between nodes is the `DefectState` TypedDict in `state.py`.
- Nodes are pure functions: `node(state) -> dict` returning the keys to merge. No global state, no module-level caches that survive between runs.

## Logging
- Use the standard library `logging` module via `logging.getLogger(__name__)`.
- All logs go to stderr; the CLI's `--verbose` flag flips to DEBUG.
- Don't `print()` for diagnostics — `print` is for user-facing CLI output only.

## Errors
- Wrap external calls (Claude, harness) in narrow try/except blocks that capture the failure into the state's `final_status="errored"` rather than crashing the run. The eval loop must survive any single instance failing.
- For unimplemented Phase 2 slots, `raise NotImplementedError("Phase 2 — see docs/milestone-plan.md")`. Do not stub silent passes.

## Testing
- This milestone is light on unit tests — protect the loop, not test coverage. Write a unit test only when you need it to debug a node.
- Sanity smoke test: `defect-triage run --instance <id>` on one known instance must succeed end-to-end. Run this after every meaningful change.

## Commits
- Conventional-commit prefix: `feat:`, `fix:`, `chore:`, `docs:`.
- Small, focused commits — one node or one concern per commit.

## What never goes in this repo
- Real API keys (use `.env`, which is gitignored; `.env.example` is the template).
- Cached SWE-bench data files (gitignore them).
- Run artefacts under `eval/runs/` (gitignored except `results.json`).
- Notebook (`.ipynb`) files in the milestone — keep everything in proper `.py` modules.
