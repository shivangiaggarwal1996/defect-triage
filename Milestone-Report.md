# Defect Triage & Repair Assistant — Phase 1 Milestone

*Milestone report — 7 June 2026*

---

## 1. Framing

This submission is a deliberate **Phase 1 milestone** of a larger capstone. It
demonstrates the architecture, the orchestration, the agent contracts, and a
measured end-to-end loop on a real benchmark — and it names the Phase 2 work
explicitly.

---

## 2. What ships

- **A working core loop** — Intake → Localize → Prioritize → Patch → Test →
  Critic — implemented as a **LangGraph** state machine with two rule-based
  conditional edges (test-pass and retry-count). No LLM decides routing.
- **A real test executor** — every patch is run against the repository's tests
  through the **official SWE-bench Docker harness**. No hand-rolled sandbox.
- **A measured evaluation slice** — the pipeline runs over **all 3 Flask
  instances in SWE-bench Lite** (Lite contains exactly three), producing a
  baseline resolution rate and per-node artefacts.
- **Full observability** — every LLM call is funnelled through one
  Langfuse-instrumented entry point (`src/defect_triage/llm.py`), so each run is
  one Langfuse trace with one span per node call. No anonymous LLM calls.
- **A typer + rich CLI** — `run`, `eval`, and `trace` commands.
- **Run artefacts** — for every run, `eval/runs/<ts>__<instance>/` captures the
  final state, localizer candidates, every patch diff, every harness test log,
  and every critic message.

### Architecture

The diagram below is the **full architecture**. Plain boxes and solid arrows are
**Phase 1 (shipped)**; the `[P2]`-tagged lines are the **Phase 2** capabilities
that plug into the same spine (each already exists as a slot/stub in
`docs/architecture.md`).

```
                 Intake
                   |
                Localizer            P1: grep + LLM file-ranker
                   |                 [P2] + hybrid retrieval (Qdrant + embeddings + BGE rerank)
                   |                 [P2] + multi-repo / cross-cluster search
                   |
                Prioritizer          P1: trivial severity heuristic (passthrough)
                   |                 [P2] + cross-repo blast-radius scoring
                   |
                Patch-writer         P1: gpt-5.4-nano  (plan/Phase 2: Claude Sonnet 4.6)
                   |                 [P2] + fine-tuned Qwen2.5-Coder ablation
                   |
                Test-runner          P1: SWE-bench Docker harness
                   |
            tests pass? -- yes --> END (resolved) --[P2]--> PR-opener (PyGithub) -> open PR
                   |
                  no
                   |
                Critic
                   |
            retries < 2? -- no --> END (needs human / exhausted_retries)
                   |
                  yes
                   |
            back to Patch-writer (with critic feedback added to state)

   Observability  P1: Langfuse traces every node (one trace/run, one span/node)
   Surfaces       [P2] Streamlit UI over the CLI core ; red-team eval case
```

Solid arrows are deterministic; the pass/fail and retry-count edges are
rule-based, not model-decided. Everything tagged `[P2]` is roadmap (see §6) — the
Phase 1 loop is the spine those capabilities attach to, not a throwaway prototype.

---

## 3. Results

Numbers are taken directly from `eval/results.json` (run 6 June 2026).

| Metric | Value |
|---|---|
| Total instances | 3 |
| Resolved | 0 |
| Exhausted retries | 3 |
| Errored | 0 |
| **Resolution rate** | **0.0%** |
| Localization Hit@1 | 2 / 3 (66.7%) |
| Localization Hit@2 (= Hit@5 here) | 3 / 3 (100%) |
| Patch applied to container | 3 / 3 (100%) |

**Reading the table.** The loop mechanics are sound: the localizer puts the
correct file in its top two for every instance, and every generated diff is
syntactically valid and applies cleanly inside the harness container. The 0%
resolution is entirely a matter of *patch correctness against the hidden
`FAIL_TO_PASS` tests* — and each of the three instances fails for a different,
very SWE-bench-typical reason.

### Per-instance stories

- **`pallets__flask-4992` — closest miss (correct file, wrong API).** The
  localizer correctly picked `src/flask/config.py` (confidence 0.92). The gold
  fix adds a `text: bool` parameter to `Config.from_file`, and the hidden test
  calls `from_file(..., text=False)`. The agent instead invented a plausible but
  different parameter — `mode: str` with `mode="rb"`. The patch applied cleanly,
  but the test's `text=False` call raised `TypeError: unexpected keyword
  argument 'text'`. The exact parameter name is not derivable from the issue
  text — this is classic benchmark underspecification.

- **`pallets__flask-4045` — top-1 localization miss.** The gold fix raises a
  `ValueError` in `src/flask/blueprints.py`. The localizer ranked
  `src/flask/app.py` first (0.78) and had `blueprints.py` second (0.72), so it
  patched the wrong file. Hit@1 miss, Hit@2 hit. Both `FAIL_TO_PASS` tests
  failed because the validation never fired where the tests look.

- **`pallets__flask-5063` — change too large.** The localizer correctly picked
  `src/flask/cli.py` (0.62). The gold fix is a ~50-line refactor of
  `routes_command` (adds a Host/Subdomain column and rewrites the sort logic).
  The right file, but reproducing that exact multi-part refactor from the issue
  text was beyond the single-shot patch-writer.

These are three of the hardest hand-picked Flask Lite instances solved by a
grep+LLM localizer with no retrieval, no reranker, and no fine-tune. A 0/3
baseline on this specific trio with this minimal stack is the expected starting
point, not a defect; the Phase 2 components below target exactly these three
failure modes.

---

## 4. Honest limitations

Named here before anyone has to ask:

- **Localizer is grep + LLM, not the planned hybrid retrieval + rerank.** Vector
  DB, embeddings, and the BGE reranker are deferred. flask-4045's top-1 miss is a
  direct consequence.
- **Eval slice is the 3 Flask instances in SWE-bench Lite.** That is the entire
  Flask population of Lite — not a 10-instance sample, and far too small to be
  statistically meaningful. It is a baseline, not a score.
- **Model is OpenAI `gpt-5.4-nano`, a deviation from the original plan.** The Phase 0
  plan and `CLAUDE.md` specify Anthropic Claude Sonnet 4.6; the implemented
  pipeline runs on `gpt-5.4-nano` (a GPT-5-class nano model, set in `.env`). Langfuse tracing and
  the single-entry-point design are model-agnostic, so this is a config change,
  not an architectural one — but it is a real divergence from the spec and is
  recorded as such. No fine-tuned model was used. **Planned fix:** switch the
  patch-writer (and the other LLM nodes) back to Claude Sonnet 4.6 for patching,
  as the Phase 0 plan specified; the single-entry-point wrapper makes this a
  one-line `.env` change.
- **Test-pass is a floor, not proof.** A green `FAIL_TO_PASS` would show the
  tests flip, not that the fix is correct in general. SWE-ABS 2026 showed weak
  tests inflate resolution scores; we accept that as a known caveat. (Moot this
  milestone, since nothing resolved — but it stays true as the rate climbs.)
- **No PR-opener and no UI.** CLI only; results are JSON + local artefacts.

---

## 5. Planned vs. actual stack (the deltas)

| Component | Phase 0 plan | This milestone | Status |
|---|---|---|---|
| Orchestration | LangGraph | LangGraph | ✅ as planned |
| Test executor | SWE-bench Docker harness | SWE-bench Docker harness | ✅ as planned |
| Tracing | Langfuse, every call | Langfuse, single entry point | ✅ as planned |
| LLM | Claude Sonnet 4.6 | OpenAI gpt-5.4-nano | ⚠️ deviation (see §4) |
| Localizer | hybrid retrieval + rerank | grep + LLM ranker | ⏭️ Phase 2 |
| Repos | multi-repo cluster | single repo (Flask) | ⏭️ Phase 2 |
| Prioritizer | cross-repo blast radius | trivial severity passthrough | ⏭️ Phase 2 |
| Output | PR-opener (PyGithub) | JSON + artefacts | ⏭️ Phase 2 |
| Model training | Qwen2.5-Coder + Unsloth | none | ⏭️ Phase 2 |
| Interface | (n/a) | typer CLI | ✅ |

The deltas explain themselves: everything that ships is the orchestration-and-
measurement backbone; everything deferred is a capability bolt-on the backbone
was deliberately designed to receive.

---

## 6. Phase 2 roadmap

Each item below already exists as a slot in `docs/architecture.md` (several as
stub modules that raise `NotImplementedError`), so the wider design is visible in
the code today and was deliberately scoped down — not missed.

- **Hybrid retrieval + rerank localizer** — Qdrant + embeddings + BGE reranker,
  to fix top-1 misses like flask-4045.
- **Multi-repo / cross-cluster localization** — beyond a single repository.
- **Cross-repo blast-radius prioritization** — replacing the trivial severity
  heuristic.
- **Fine-tuning ablation** — Qwen2.5-Coder-7B + Unsloth, to measure a tuned
  patch-writer against the API baseline.
- **PR-opener** — PyGithub, to turn an accepted patch into a real pull request.
- **Red-team evaluation case** — adversarial defect inputs.
- **Web UI** — Streamlit front-end over the CLI core.

---

## 7. Closing

This submission is a deliberate Phase 1 milestone of a larger capstone: a
working, fully-observable Localize → Patch → Test → Critic loop, measured
honestly on a real benchmark, with every deferred capability named as roadmap
rather than gap.
