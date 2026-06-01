# Day 2 — Tue 3 Jun — LangGraph skeleton + Localizer

**Time budget:** 3 hours.
**Today's prime directive:** a 3-node LangGraph (Intake → Localizer → END) runs on one instance with Langfuse traces visible, and the Localizer returns a ranked list of file candidates.

## Goal

- LangGraph state, graph wiring, and Langfuse-instrumented Claude wrapper in place.
- Localizer node implemented per `docs/agents/localizer.md` (grep + Claude file-ranker, no vector search).
- Running `defect-triage run --instance <id>` produces a `state.json` artefact with `candidates` filled in, and a trace appears in Langfuse.

## Prerequisites from Day 1

- Harness runs one instance to completion.
- Langfuse smoke trace works.
- `eval/instances.txt` exists.

## Step-by-step

1. **Implement `src/defect_triage/state.py`.** Copy the `TypedDict` from `docs/architecture.md` section 2 exactly. Add a small helper `init_state(instance: dict) -> DefectState` that creates a fresh state from a SWE-bench instance dict.

2. **Implement `src/defect_triage/llm.py`** — the single Claude entry point.
   - One function `claude(messages: list[dict], *, node: str, instance_id: str, retry_count: int = 0, **kwargs) -> str` that wraps the Anthropic SDK.
   - Use the Langfuse `@observe` decorator (or the manual span API) so every call becomes a Langfuse span tagged with `node`, `instance_id`, `retry_count`.
   - Default model: `claude-sonnet-4-6` (or current Sonnet 4.6 identifier — confirm in Anthropic docs).

3. **Implement `src/defect_triage/instances.py`** — loader that, given an instance ID, returns the SWE-bench Lite record (problem_statement, base_commit, repo, etc.) and checks out the repo at `base_commit` into a working directory.

4. **Implement `src/defect_triage/nodes/intake.py`** — trivial node that copies fields from the loaded instance into the state shape. No LLM call. Just a clean state initialization step in the graph.

5. **Implement `src/defect_triage/nodes/localizer.py`** — follow `docs/agents/localizer.md` precisely. Both LLM calls (extract terms, rank candidates) go through `llm.py`. Use `git grep` via `subprocess` from inside the checked-out repo. Use `ast` to attach function names.

6. **Implement `src/defect_triage/graph.py`** with three nodes wired: `intake → localizer → END`. Don't add the patch/test/critic nodes yet (Day 3–4). Compile the graph; expose it from the module.

7. **Implement `src/defect_triage/cli.py`** with a `run` command (using `typer`). For now `run --instance <id>` should: load instance, run the graph, write `state.json` and `localizer.json` artefacts to `eval/runs/<timestamp>__<instance_id>/`.

8. **End-to-end check.** Run on one instance. Open the trace in Langfuse. Confirm:
   - `candidates` is a non-empty list in `state.json`.
   - You can see two spans in Langfuse (`extract_terms`, `rank_candidates`).
   - The top candidate's file path is something plausible (a `.py` file inside `src/flask/`).

## Definition of Done

- `defect-triage run --instance flask__flask-5014` (or your chosen ID) finishes without errors.
- `state.json` contains a `candidates` list with at least 1 entry.
- Langfuse shows a single trace with two named spans.
- The implementation matches the contracts in `docs/agents/localizer.md`.

## Resources for today

- LangChain Academy "Introduction to LangGraph" — Modules 1 and 2 only (state, nodes, edges): https://academy.langchain.com/courses/intro-to-langgraph
- Anthropic Messages API: https://docs.anthropic.com (Messages page).
- Langfuse + Python: https://langfuse.com/docs (read the `@observe` decorator section).

## Common pitfalls

- **`git grep` requires you to be inside the repo directory** — set `cwd=` when subprocess-ing.
- **Claude returns Markdown-fenced JSON sometimes** even when asked not to. Strip ```json fences before parsing.
- **Don't read full files into the rank prompt** — only matched lines plus a few of context. Token budget matters.

## What NOT to do today

- Don't implement Patch-writer, Test-runner, or Critic. Tomorrow.
- Don't add any retrieval beyond grep. No vector stores. No reranker.
- Don't add multiple LLM providers.
