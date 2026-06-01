# Stack reference — tools, roles, study links

Each entry: what it is, what role it plays in our code, and the one or two links worth reading the day you touch it. **Don't study upfront** — read each entry on the day you reach it.

## LangGraph
- **Role:** the pipeline IS a LangGraph. Nodes are agents, conditional edges are pass/fail and retry-count rules.
- **Where used:** `src/defect_triage/graph.py` (wiring), every file in `src/defect_triage/nodes/`.
- **Study:**
  - LangChain Academy course (free, official): https://academy.langchain.com/courses/intro-to-langgraph — Modules 1 and 2 first (state, nodes, edges); Module 3 conditional-edges material on Day 4.
  - Reference: https://langchain.com/langgraph

## Anthropic Claude Sonnet 4.6 + langchain-anthropic
- **Role:** the LLM reasoning behind Localizer, Patch-writer, Critic. Test-runner uses no LLM.
- **Where used:** `src/defect_triage/llm.py` (wrapper); called from each LLM-driven node.
- **Study:**
  - API quickstart: https://docs.anthropic.com (Messages API page)
  - Design philosophy that matches our spine: "Building Effective Agents" on anthropic.com

## Langfuse
- **Role:** trace every LLM call and every LangGraph step. The traces are the glass-box evidence in the submission.
- **Where used:** `src/defect_triage/llm.py` (the wrapper instruments calls), and a top-level handler in `src/defect_triage/graph.py`.
- **Study:**
  - Python quickstart: https://langfuse.com/docs (the "Get Started" tutorial only — skip the rest)
  - LangGraph integration: search "Langfuse LangGraph" in the docs

## SWE-bench Lite + Docker harness
- **Role:** the only legitimate test executor for the milestone. Do not write a custom sandbox.
- **Where used:** `src/defect_triage/harness.py` (thin wrapper that calls the harness CLI); `src/defect_triage/instances.py` (loader).
- **Study:**
  - Read the "Evaluation" section of the README at https://github.com/princeton-nlp/SWE-bench
  - Site: https://swebench.com — skim the leaderboard for context (do not read the paper this week; you'll cite it in the report)

## unidiff
- **Role:** parse and validate the unified diffs Claude emits, before handing them to the harness.
- **Where used:** `src/defect_triage/nodes/patch_writer.py`.
- **Study:** README on https://github.com/matiasb/python-unidiff (10 min).

## typer + rich
- **Role:** CLI entry point and pretty terminal output.
- **Where used:** `src/defect_triage/cli.py`.
- **Study:** https://typer.tiangolo.com (first-steps tutorial only). Rich is auto-installed with Typer and used for tables.

## python-dotenv
- **Role:** load `.env` for API keys.
- **Where used:** top of `cli.py`.

## Python `ast`
- **Role:** parse Python source to map line ranges to functions/classes — used by the Localizer to attach function names to file matches.
- **Where used:** `src/defect_triage/nodes/localizer.py`.
- **Study:** https://docs.python.org/3/library/ast.html (only `ast.parse`, `ast.FunctionDef`, `ast.walk`).

## Deliberately not in this milestone

| Tool | Why deferred | When it would land (Phase 2) |
|---|---|---|
| Qdrant + Qodo-Embed + BGE-reranker | Full retrieval stack — too big to set up in 6 days; grep-based Localizer closes the loop faster | When we move from single-repo to cluster work |
| Qwen2.5-Coder + Unsloth (QLoRA) | Fine-tune ablation — 15+ hrs by itself; not the moat anyway | Phase 2, after the loop is solid |
| PyGithub | PR-opener — deferred to keep this week focused on the loop | Phase 2 |
| Streamlit | UI — would steal hours from the core loop | Phase 2 |
| Qdrant hybrid + reranker | See first row | Phase 2 |
