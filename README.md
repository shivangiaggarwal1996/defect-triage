# Defect Triage & Repair Assistant

A LangGraph-orchestrated multi-agent pipeline that takes a real software defect, locates the buggy file in a Python repository, drafts a patch, runs the repo's tests, and self-corrects on failure.

**Status:** Phase 1 milestone — single-repo (Flask), ~10 SWE-bench Lite instances, no fine-tune, CLI only. Submission target: 7 June 2026. See [`docs/milestone-plan.md`](docs/milestone-plan.md) for what's in and out of scope.

**Capstone context:** AI Engineering cohort (Gaurav Sen / InterviewReady). This milestone demonstrates RAG-flavoured retrieval, multi-agent orchestration, and evaluation; the deferred work (multi-repo, fine-tune, blast-radius prioritization) is the Phase 2 roadmap.

## Quick start (macOS)

```bash
# 1. Clone and enter
git clone <this-repo> defect-triage && cd defect-triage

# 2. Python 3.11 (pyenv/asdf recommended)
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .

# 3. Docker Desktop must be running (it pulls SWE-bench eval containers)
docker info  # should print without error

# 4. API keys
cp .env.example .env  # then fill in ANTHROPIC_API_KEY and LANGFUSE_* keys

# 5. Sanity-check the harness on one instance
defect-triage run --instance flask__flask-5014
```

## Running with Claude Code in VS Code

This repo is structured for Claude Code. The flow:

1. Open the folder in VS Code, open an integrated terminal.
2. Start Claude Code in that terminal. It will automatically read [`CLAUDE.md`](CLAUDE.md).
3. For each day's work, give Claude Code the contents of the matching `tasks/day-N-*.md` as your prompt.
4. Use one Claude Code session per day's task file — do not mix days in one session.

## Repository layout

| Path | What it holds |
|---|---|
| `CLAUDE.md` | Master briefing — Claude Code reads this every session |
| `docs/` | All specs: milestone plan, architecture, per-node specs, conventions, tools |
| `tasks/` | One file per day with the day's goal, checklist, and resources |
| `src/defect_triage/` | The Python package — Claude Code writes the code here |
| `eval/` | Run artefacts and the final results JSON |

## Tech stack (short)

Python 3.11 · LangGraph · Anthropic Claude Sonnet 4.6 · Langfuse · SWE-bench Lite + official Docker harness · `unidiff` · `typer` + `rich`.

Detail and study links: [`docs/stack.md`](docs/stack.md).

## What this is **not** doing (yet)

Multi-repo localization, cross-repo blast-radius prioritization, fine-tuned Qwen2.5-Coder model, PR-opener, Streamlit UI, vector-DB / embeddings / reranker. All deferred to Phase 2. See [`docs/milestone-plan.md`](docs/milestone-plan.md).
