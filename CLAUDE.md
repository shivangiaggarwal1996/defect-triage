# Defect Triage & Repair Assistant — Claude Code briefing

This file is loaded automatically by Claude Code on every session. Read it once at the start of every task. It is the source of truth for what we are building and how. Anything not specified here lives in `docs/`.

## 1. Mission (one sentence)

A multi-agent pipeline that takes a real software defect (a GitHub issue), locates the buggy file in a Python repository, drafts a patch, runs the repository's tests, and self-corrects on failure — all inside a LangGraph state machine, with full traces in Langfuse.

## 2. Submission status — read this before anything else

- **Submission deadline:** Saturday 7 June 2026.
- **Today's reference date:** the day this session is running. Always read `tasks/day-N-*.md` matching the current calendar day. Day 1 = Mon 2 Jun, Day 6 = Sat 7 Jun.
- **What we are shipping:** a single-repo Flask core loop on ~10 SWE-bench Lite instances. This is a Phase 1 milestone, **not** the full project.
- **What is deferred (do not implement, even if it seems natural to add):**
  - Multi-repo / cross-repo cluster work
  - Cross-repo blast-radius prioritization (use a simple severity heuristic only)
  - Fine-tuning a model (Qwen2.5-Coder + Unsloth) — deferred
  - PR-opener (PyGithub) — deferred
  - Streamlit / web UI — CLI only for the milestone
  - Red-team eval case — deferred
  - Qdrant / vector DB / embeddings / BGE reranker — **deferred for the milestone** (see Localizer note below)
- If you are tempted to implement anything in the deferred list, stop and tell the user. Do not silently expand scope.

## 3. Architecture in one screen

```
                 Intake
                   |
                Localizer  (grep + Claude file-ranker — NOT vector search this week)
                   |
                Prioritizer  (severity heuristic for milestone; trivial)
                   |
                Patch-writer
                   |
                Test-runner  (SWE-bench Docker harness — NOT a hand-rolled sandbox)
                   |
            tests pass? -- yes --> END (record result)
                   |
                  no
                   |
                Critic
                   |
            retries < 2? -- no --> END (record "needs human")
                   |
                  yes
                   |
            back to Patch-writer
```

Solid arrows are deterministic. The pass/fail and retry-count edges are conditional, decided by rules (not by an LLM). Full detail and the state schema live in `docs/architecture.md`.

## 4. Tech stack (with roles)

- **Python 3.11**
- **LangGraph** — orchestration. The pipeline IS a LangGraph.
- **langchain-anthropic** — Claude API wrapper used inside nodes.
- **Anthropic Claude Sonnet 4.6** — the LLM behind Localizer, Patch-writer, Critic.
- **Langfuse** — agent tracing. Every LangGraph node must be observable.
- **SWE-bench Lite + official Docker harness** — eval data and the test executor. **Do not write a custom sandbox.**
- **unidiff** — parse/apply unified diffs.
- **typer + rich** — CLI and pretty output.
- **python-dotenv** — env loading.

Exact versions are pinned in `pyproject.toml`. Tools and study links: `docs/stack.md`.

## 5. Repo layout — keep code here

```
defect-triage/
├── CLAUDE.md                  ← this file
├── README.md                  ← human onboarding
├── pyproject.toml             ← deps pinned
├── .env.example               ← API keys template
├── docs/                      ← specifications (read these for design)
│   ├── milestone-plan.md
│   ├── architecture.md
│   ├── stack.md
│   ├── conventions.md
│   └── agents/                ← per-node specs (read before implementing a node)
│       ├── localizer.md
│       ├── patch-writer.md
│       ├── test-runner.md
│       └── critic.md
├── tasks/                     ← one file per day, read the matching one
├── src/
│   └── defect_triage/         ← Python package (you create the files inside)
│       ├── __init__.py
│       ├── cli.py             ← typer CLI entry point
│       ├── state.py           ← the LangGraph state TypedDict
│       ├── graph.py           ← the LangGraph wiring
│       ├── nodes/             ← one file per node
│       │   ├── intake.py
│       │   ├── localizer.py
│       │   ├── prioritizer.py
│       │   ├── patch_writer.py
│       │   ├── test_runner.py
│       │   └── critic.py
│       ├── llm.py             ← Anthropic client + Langfuse-instrumented wrapper
│       ├── harness.py         ← thin wrapper around SWE-bench Docker harness
│       └── instances.py       ← loaders for the chosen SWE-bench Lite slice
└── eval/                      ← run outputs (gitignored except results.json)
    └── instances.txt          ← the 10 chosen instance IDs
```

## 6. Always-do / never-do (hard rules)

**Always:**
- Read `docs/agents/<node>.md` before implementing or modifying that node.
- Wire Langfuse on every Claude call — no anonymous LLM calls.
- Use type hints and docstrings on every public function.
- Use the SWE-bench harness for any test execution.
- Save run artefacts (state, prompts, completions, results) under `eval/runs/<timestamp>/`.
- Tell the user when a task is genuinely larger than its day-budget estimate, before starting work.

**Never:**
- Hand-roll a test sandbox or subprocess Python tests directly — go through the SWE-bench harness only.
- Add a vector DB, embeddings library, or reranker. This is deferred.
- Add Streamlit, Gradio, or any web UI. CLI only.
- Add PyGithub or PR-opening code. Deferred.
- Add fine-tuning code (Unsloth, PEFT, TRL, datasets-for-training). Deferred.
- Edit files in `docs/` without being asked. Treat docs as the spec; if a spec seems wrong, raise it with the user first.
- Use any LLM provider other than Anthropic Claude for the milestone.

## 7. Running things — known commands

The CLI should expose these (the user runs them; you build them):

```bash
# Run the pipeline on one instance
defect-triage run --instance <instance_id>

# Run the pipeline on the chosen 10-instance slice and write results
defect-triage eval --instances eval/instances.txt --out eval/results.json

# Inspect the latest trace locally
defect-triage trace --last
```

## 8. Daily workflow

1. Open the matching `tasks/day-N-*.md` for today's date.
2. Read its **Goal** and **Definition of Done**.
3. Before writing code in a node, read its `docs/agents/<node>.md` spec.
4. Work in small commits. After each meaningful change, run a quick check (lint or one test instance).
5. If a step is unclear, ask the user — do not invent a design choice the spec doesn't cover.

## 9. Where to go for more

- Full milestone plan and what is in/out of scope: `docs/milestone-plan.md`
- Pipeline and state schema in detail: `docs/architecture.md`
- Code conventions: `docs/conventions.md`
- Per-node specs: `docs/agents/*.md`
- Tools and learning links: `docs/stack.md`
