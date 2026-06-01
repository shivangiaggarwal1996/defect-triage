# Day 4 — Thu 5 Jun — Critic + retry loop — full pipeline

**Time budget:** 3 hours.
**Today's prime directive:** the full graph runs end-to-end, with the conditional retry edge active. On failure, the Critic produces feedback and the Patch-writer gets one more try.

## Goal

- Critic node implemented per `docs/agents/critic.md`.
- Two conditional edges wired (test pass/fail; retry budget).
- Retry cap of 2 (so up to 3 patch attempts total per instance).
- One instance runs to either `resolved` or `exhausted_retries` cleanly.

## Prerequisites from Day 3

- The 4-node linear graph runs to a `test_outcome`.

## Step-by-step

1. **Implement `src/defect_triage/nodes/critic.py`** per `docs/agents/critic.md`:
   - Read last ~80 lines of the harness log from `test_outcome["raw_log_path"]`.
   - Categorize the failure (fix didn't work / regression / harness error).
   - Call Claude through `llm.py` for the hypothesis + next-step.
   - Write `critic_feedback` to state and `critic/<n>.txt` to the artefact dir.

2. **Add the conditional edges** in `src/defect_triage/graph.py`:
   - After `test_runner`: route to END if `test_outcome["passed"]`, else to `critic`.
   - After `critic`: route to `patch_writer` if `retry_count < 2`, else END with `final_status="exhausted_retries"`.
   - On entering `patch_writer` via the retry path, the wrapping logic (in `patch_writer` or a small edge function) must increment `retry_count`.

3. **Ensure `retry_count` increments correctly.** Initialize to 0 in `init_state`. Increment exactly once per Critic→Patch-writer trip. Test by running an instance that you know will need at least one retry (Day 3 likely produced one).

4. **Set `final_status` consistently.** At the moment of routing to END, set:
   - `"resolved"` if `test_outcome["passed"]`
   - `"exhausted_retries"` if retries are up
   - `"errored"` if any node caught a fatal error (the wrapping you already added in nodes)

5. **End-to-end run.** Pick an instance that failed on Day 3. Run again. Observe:
   - First test fails → Critic fires → Patch-writer retries with `critic_feedback` in the prompt → tests again.
   - Whether the second/third attempt passes or not is not today's KPI — the routing is.

6. **Verify the Langfuse trace** shows the full multi-attempt run as one trace with multiple spans, including retry spans labeled by `retry_count`.

## Definition of Done

- A single `defect-triage run --instance <id>` produces a state with `final_status` in `{resolved, exhausted_retries, errored}`.
- On at least one instance, the trace shows ≥ 2 patch attempts (i.e., the retry edge fired).
- Critic feedback files appear under `eval/runs/.../critic/`.
- No node crashes the run — errored instances should produce a state file, not an exception.

## Resources for today

- LangGraph conditional edges: LangChain Academy Module 3 (re-watch only the conditional-edges section): https://academy.langchain.com/courses/intro-to-langgraph
- Langfuse trace nesting: https://langfuse.com/docs (search "nested spans" / "trace context").

## Common pitfalls

- **Double-increment of `retry_count`** if you bump it both in the edge function and in the Patch-writer. Pick one place. The edge function is cleaner.
- **Forgetting to pass `critic_feedback` into Patch-writer's prompt** on the retry path. Verify by inspecting the second attempt's prompt in Langfuse.
- **Infinite loops** — if the retry edge is wrong you can loop forever burning Claude tokens. Add a hard cap check at the start of `patch_writer` too (defensive): if `retry_count > 2`, raise.

## What NOT to do today

- Don't tune prompts for quality today. The point is routing correctness; tomorrow is the eval slice.
- Don't add new nodes.
- Don't optimize the LLM calls for token cost yet — Friday/Saturday if time allows.
