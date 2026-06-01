# Day 6 — Sat 7 Jun — Report, slides, demo, submit

**Time budget:** 6 hours. **Submission tonight.**
**Today's prime directive:** package and ship. No new code. If something doesn't work, it becomes a "known limitation" in the report.

## Goal

A complete submission containing:

1. The six Phase PDFs (Phases 0–5).
2. The repo (this folder), with a clean `git log`.
3. A milestone report (2–3 pages, PDF).
4. 6–8 demo slides.
5. A short screen recording (~3 minutes) of one defect going through the pipeline.

## Time allocation (rough)

- 1.0 h — Milestone report (writing)
- 0.5 h — Slides
- 0.5 h — Screen recording
- 1.0 h — Polish, final commit, package, submit
- 3.0 h — buffer (you will use most of it; don't kid yourself)

## Step-by-step

### 1. Milestone report (~1 hr)

Open a new doc. Structure exactly like this:

**Title:** "Defect Triage & Repair Assistant — Phase 1 Milestone"

**Sections:**

1. *Framing* (1 paragraph) — copy from `docs/milestone-plan.md`, the "Framing" section. The first sentence should be "This submission is a deliberate Phase 1 milestone of a larger capstone."

2. *What ships* (bullets) — list the working pipeline, the 10-instance eval, Langfuse traces. Show the architecture diagram from your Phase 0 PDF.

3. *Results table* — the actual numbers from `eval/results.json`:
   - Total instances, resolved, exhausted retries, errored.
   - Resolution rate.
   - (If you computed it) Localization Hit@1 / Hit@5.
   - 2–3 example instance ids: one resolved (if any), one exhausted, one errored, with a one-line story each.

4. *Honest limitations* — name them yourself before anyone asks:
   - Localizer is grep+LLM, not the planned hybrid+rerank.
   - Eval slice is 10 Flask instances — not statistically meaningful, just a baseline.
   - No fine-tune; agent runs on Claude Sonnet 4.6 only.
   - Test-pass is a floor, not proof — SWE-ABS 2026 showed weak tests inflate scores; we accept that as a known caveat.
   - No PR-opener, no UI.

5. *Phase 2 roadmap* — copy from `docs/milestone-plan.md`'s deferred list. This is where multi-repo, fine-tune, blast-radius, PR-opener, vector retrieval all sit. Frame them as planned, not missed.

Export to PDF. Name it `Milestone-Report.pdf`.

### 2. Slides (~0.5 hr, 6–8 slides)

Keep it short:

1. Title + framing sentence.
2. The problem (one bullet: "maintainers drowning in defect backlogs").
3. The architecture diagram (from Phase 0 PDF).
4. The agent contracts in one slide (Localize → Patch → Test → Critic, one line each).
5. Results table.
6. Honest limitations (3 bullets).
7. Phase 2 roadmap (3 bullets).
8. Closing — the framing sentence again.

### 3. Screen recording (~0.5 hr)

QuickTime → File → New Screen Recording. Record ~3 minutes:

1. Show the CLI: `defect-triage run --instance <one resolved or near-miss>` (20s).
2. Show the LangGraph state evolving (cat `state.json` at the end, highlight `final_status`) (30s).
3. Show the Langfuse trace UI for that run with the spans expanded (60s).
4. Show `eval/results.json` and read the resolution rate out loud (30s).
5. Show the artefact directory `eval/runs/.../` tree (20s).

Trim, no fancy editing. Export as MP4.

### 4. Polish + package + submit

- Run the full test path once more in a clean shell, just to be sure.
- `git status` clean. Final commit "feat: milestone 1 submission".
- Push to your fork/repo.
- Zip the repo (excluding `.venv`, `eval/runs/*`, `.env`).
- Submit per your cohort's instructions.

### 5. Final sanity check before submitting

- [ ] All 6 Phase PDFs included.
- [ ] Repo runs `pip install -e .` cleanly on a fresh environment (you can't test this in 10 min, but spot-check `pyproject.toml`).
- [ ] `Milestone-Report.pdf` reads as a milestone, not an apology.
- [ ] Slides match the report.
- [ ] Demo recording plays.
- [ ] Submission confirmation in hand.

## Resources for today

- Re-read your own Phase 0 PDF — lift the architecture diagram and scope language directly.
- Re-read your Phase 4 PDF — lift the cost / time discussion if useful for the limitations section.

## What NOT to do today

- Don't write new code. **Especially** don't write new code.
- Don't try to improve the resolution rate.
- Don't expand the slice.
- Don't get sucked into a long Notion / Docs format war — plain PDF from Markdown is fine.
- Don't skip the demo recording. A submitted video carries the whole story; people remember it more than the report.

## If you have leftover time

In order of value:

1. Add a section to the report comparing your actual stack to your planned Phase 0 stack — the deltas explain themselves.
2. Add one labeled trace screenshot to the report from Langfuse.
3. Run one extra instance with `--verbose` and include the prompt/completion as an appendix.

Submit. Then sleep.
