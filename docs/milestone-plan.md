# Milestone plan — 7 June 2026 submission

## Framing

The 7 June submission is a deliberate **Phase 1 milestone** of a larger capstone. It demonstrates the architecture, the orchestration, the agent contracts, and a measured end-to-end loop on a real benchmark — and it names the Phase 2 work explicitly. This framing is the point. Opening the submission with "this is a milestone; here is what ships and what is roadmap" reads as planning maturity, not retreat.

## What ships on 7 June

1. **The six Phase documents (already produced):** Phases 0 to 5 covering scope, the Phase 1 verdict, research with primary sources, PMF, resource estimation, and the tech stack.
2. **A working core loop** — Localize → Patch → Test → Critic — in LangGraph, against Anthropic Claude Sonnet 4.6.
3. **A small evaluation slice** — ~10 SWE-bench Lite instances from Flask, executed via the official SWE-bench Docker harness, producing a baseline resolution rate.
4. **Langfuse traces** captured for every run as glass-box evidence.
5. **A milestone report** (2–3 pages): what ships, what is deferred, results table, honest limitations, Phase 2 roadmap.
6. **6–8 demo slides** plus a short screen recording of one defect going through the pipeline.

## What is deferred — name these in the submission as roadmap, not gaps

- Multi-repo cross-cluster localization
- Cross-repo blast-radius prioritization (a simple severity heuristic ships instead)
- Fine-tuning ablation (Qwen2.5-Coder-7B + Unsloth)
- PR-opener (PyGithub)
- Vector DB + embeddings + reranker (Qdrant, Qodo-Embed, BGE-reranker)
- Red-team evaluation case
- Streamlit / web UI

Each appears in `docs/architecture.md` as a slot that exists in the design but is unimplemented this milestone.

## Day-by-day plan

Today's reference: **Mon 2 Jun 2026.** Detailed steps for each day live in `tasks/day-N-*.md`. The shape:

| Day | Date | Hrs | Focus | Definition of done |
|---|---|---|---|---|
| 1 | Mon 2 Jun | 3 | Setup + harness | Project skeleton in place. One SWE-bench Lite instance runs end-to-end via the Docker harness. |
| 2 | Tue 3 Jun | 3 | LangGraph + Localizer | 3-node graph (Intake → Localizer → end) runs against Claude with Langfuse on. Localizer returns ranked `file:function` for one instance. |
| 3 | Wed 4 Jun | 3 | Patch-writer + Test-runner | One instance goes locate → patch → test on the harness, green or red. The loop is closed. |
| 4 | Thu 5 Jun | 3 | Critic + retry loop | Critic node + conditional retry edge wired. Full LangGraph runs end-to-end on one instance. |
| 5 | Fri 6 Jun | 3 | Eval run | Pipeline loops over all ~10 instances. Baseline resolution rate computed. **Code freeze tonight.** |
| 6 | Sat 7 Jun | 6 | Report + slides + submit | Milestone report, slides, demo recording, package, submit. |

## Hard checkpoints

- **End of Mon:** the SWE-bench harness must run one instance successfully. If not, everything downstream slips.
- **End of Wed:** one defect must go locate → patch → test end-to-end, even if the patch is wrong. The loop being closed matters more than quality.
- **If either checkpoint slips by a full day:** drop instance count from 10 to 5 and protect Saturday's report time.

## How to defend the scoping choice to your director

Three sentences:

> "I scoped this submission as a Phase 1 milestone — single-repo Flask, no fine-tune, ten instances — to demonstrate the architecture and a working measurable loop within the deadline. The full vision (multi-repo, fine-tune, blast-radius prioritization) is intact in the architecture and is the Phase 2 roadmap. I wanted to show I can ship a defensible deliverable inside a constraint, not over-promise and under-deliver."

That sentence — said calmly — converts a constrained scope into a planning credential.
