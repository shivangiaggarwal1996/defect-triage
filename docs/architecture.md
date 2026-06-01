# Architecture — milestone

This document is the source of truth for the code structure. Anything Claude Code writes must match what is here.

## 1. The pipeline

```
                 Intake
                   |
                Localizer            ← grep + Claude file-ranker (no vector search this milestone)
                   |
                Prioritizer          ← trivial severity heuristic; for one-at-a-time runs it is a passthrough
                   |
                Patch-writer
                   |
                Test-runner          ← SWE-bench Docker harness, NOT a hand-rolled sandbox
                   |
            tests pass? -- yes --> END
                   |
                  no
                   |
                Critic
                   |
            retries < 2? -- no --> END ("needs human")
                   |
                  yes
                   |
            back to Patch-writer (with critic feedback added to state)
```

The pipeline runs on **one instance at a time** at the CLI. The `eval` command iterates the same graph over the chosen slice.

## 2. LangGraph state schema

Defined in `src/defect_triage/state.py` as a `TypedDict`. This is the only shared mutable structure between nodes:

```python
from typing import TypedDict, Optional, Literal

class LocalizationCandidate(TypedDict):
    file_path: str          # e.g. "src/flask/app.py"
    function: Optional[str] # e.g. "Flask.dispatch_request"
    line_start: Optional[int]
    line_end: Optional[int]
    score: float            # 0.0 to 1.0
    evidence: str           # short rationale from the Localizer

class TestOutcome(TypedDict):
    passed: bool
    fail_to_pass_passed: list[str]   # SWE-bench fail-to-pass tests that flipped
    fail_to_pass_failed: list[str]
    pass_to_pass_failed: list[str]   # regressions
    raw_log_path: str

class DefectState(TypedDict, total=False):
    # populated by Intake
    instance_id: str
    repo: str
    problem_statement: str
    base_commit: str

    # populated by Localizer
    candidates: list[LocalizationCandidate]
    confidence: float        # confidence in top candidate
    deep_search_done: bool   # if we already retried with a wider search

    # populated by Prioritizer (milestone: always passthrough on 1-instance runs)
    priority_rank: int

    # populated by Patch-writer
    diff: str                # unified diff text
    patch_attempts: int      # incremented each retry

    # populated by Test-runner
    test_outcome: TestOutcome

    # populated by Critic
    critic_feedback: str     # plain-text actionable feedback

    # bookkeeping
    retry_count: int
    final_status: Literal["resolved", "exhausted_retries", "errored"]
    run_dir: str             # eval/runs/<timestamp>/
```

## 3. Node contracts (summary — read the per-node spec for details)

| Node | Reads | Writes |
|---|---|---|
| Intake | the raw SWE-bench instance dict | `instance_id, repo, problem_statement, base_commit` |
| Localizer | `problem_statement, repo` | `candidates, confidence, deep_search_done` |
| Prioritizer | `candidates` (milestone: trivial) | `priority_rank` |
| Patch-writer | `problem_statement, candidates, critic_feedback?` | `diff, patch_attempts` |
| Test-runner | `instance_id, diff` | `test_outcome` |
| Critic | `problem_statement, diff, test_outcome` | `critic_feedback` |

Detailed specs: `docs/agents/<node>.md`.

## 4. Conditional edges

Only two conditional edges in the milestone graph, both rule-based (no LLM decides routing):

- **After Test-runner:**
  - `state["test_outcome"]["passed"] == True` → END (mark resolved)
  - else → Critic

- **After Critic:**
  - `state["retry_count"] < 2` → Patch-writer (increment retry_count, pass critic_feedback)
  - else → END (mark exhausted_retries)

Implement these as `add_conditional_edges` in `src/defect_triage/graph.py`.

## 5. Observability

- Every node must be wrapped so its Claude calls are traced by Langfuse.
- Use `src/defect_triage/llm.py` as the single Claude entry point — it owns the Langfuse client and tags each call with the node name, `instance_id`, and `retry_count`.
- The full LangGraph run should appear as one Langfuse trace per instance, with one span per node call.

## 6. Run artefacts

For each run, the CLI creates `eval/runs/<utc-timestamp>__<instance_id>/` and writes:

- `state.json` — final state
- `localizer.json` — candidates + raw Claude response
- `patch_attempts/<n>.diff` — each diff Claude proposed
- `patch_attempts/<n>.test.log` — harness output for that attempt
- `critic/<n>.txt` — critic feedback at each retry

This artefact tree is what the eval command summarizes into `eval/results.json` and what the report references.

## 7. Slots that exist but are unimplemented this milestone

Add stubs that raise `NotImplementedError("Phase 2 — see docs/milestone-plan.md")` for these, so the design is visible in the code:

- `src/defect_triage/retrieval/` — vector store + embeddings + reranker
- `src/defect_triage/blast_radius.py` — cross-repo blast-radius scoring
- `src/defect_triage/pr_opener.py` — PyGithub PR creation
- `src/defect_triage/fine_tune/` — Qwen2.5-Coder LoRA training

Their presence in the file tree (with a docstring referencing this milestone-plan.md) is part of telling the story that the wider architecture exists and was deliberately scoped down.
