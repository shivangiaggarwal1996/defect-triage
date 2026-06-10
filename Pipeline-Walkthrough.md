# Defect Triage & Repair Assistant — Pipeline Walkthrough

*A written, step-by-step substitute for the live demo. It traces one real Flask
defect (`pallets__flask-4992`) through every component, showing each component's
purpose, the command that exercises it, and its actual output.*

All command outputs below are captured from a real run; LLM-generated text
(localizer rankings, critic feedback) is representative — exact wording varies by run.
The model is configured via `.env` (`OPENAI_MODEL`); every call is traced in Langfuse.

---

## 1. What the system does

A multi-agent **LangGraph** pipeline takes a real GitHub defect, locates the buggy
file in a Python repo, drafts a patch, runs the repo's tests through the official
**SWE-bench Docker harness**, and self-corrects on failure — up to two retries.

### Full architecture (Phase 1 shipped + Phase 2 roadmap)

```
   Intake
     |
  Localizer     P1: grep + LLM file-ranker     [P2] + hybrid retrieval (Qdrant+embed+BGE), multi-repo
     |
  Prioritizer   P1: trivial severity (passthrough)   [P2] + cross-repo blast-radius
     |
  Patch-writer  P1: LLM + unidiff validation    [P2] + fine-tuned Qwen2.5-Coder
     |
  Test-runner   P1: SWE-bench Docker harness
     |
 tests pass? --yes--> END (resolved)            [P2] --> PR-opener (PyGithub)
     |
    no --> Critic --(retry_count < 2, + feedback)--> Patch-writer
              |
        retries exhausted --> END (needs human / exhausted_retries)

 Observability  P1: Langfuse traces every node       [P2] Streamlit UI ; red-team eval
```

Solid edges are deterministic. The two pass/fail and retry edges are **rule-based
routers** — no LLM decides routing.

---

## 2. The example defect: `pallets__flask-4992`

```text
$ ./bin/python -c "from src.defect_triage.instances import load_instance; \
    print(load_instance('pallets__flask-4992')['problem_statement'])" | head -14

Add a file mode parameter to flask.Config.from_file()

Python 3.11 introduced native TOML support with the `tomllib` package. This could
work nicely with flask.Config.from_file() as an easy way to load TOML config files:

    app.config.from_file("config.toml", tomllib.load)

However, tomllib.load() takes an object readable in binary mode, while
flask.Config.from_file() opens a file in text mode, resulting in:

    TypeError: File must be opened in binary mode, e.g. use `open('foo.toml', 'rb')`
```

**The ask:** let `from_file()` open the file in binary mode so TOML configs load.

---

## 3. Component-by-component

### 3.0 State — the shared contract

**What:** one typed dict (`DefectState`) that every node reads from and writes to.
The whole pipeline is just transformations of this object. Defined in
`src/defect_triage/state.py`.

```text
$ jq 'keys' eval/runs/<run>/state.json

[ "instance_id", "repo", "problem_statement", "base_commit",
  "candidates", "confidence", "deep_search_done", "priority_rank",
  "diff", "patch_attempts", "test_outcome", "critic_feedback",
  "retry_count", "final_status", "run_dir" ]
```

Intake fills the top fields; each node adds its own (localizer → `candidates`,
patch-writer → `diff`, test-runner → `test_outcome`, critic → `critic_feedback`).

---

### 3.1 Intake — record → state

**What:** the first node. Loads the SWE-bench record and seeds the state with
`instance_id`, `repo`, `problem_statement`, `base_commit`. Code: `nodes/intake.py`.

```text
$ ./bin/python -c "from src.defect_triage.instances import load_instance; \
    r=load_instance('pallets__flask-4992'); \
    print(r['repo'], r['base_commit'][:12]); print('FAIL_TO_PASS:', r['FAIL_TO_PASS'])"

pallets/flask 4c288bc97ea3
FAIL_TO_PASS: ["tests/test_config.py::test_config_from_file_toml"]
```

The repo is checked out at that exact commit so the localizer greps real source,
and the harness later tests against the same commit.

---

### 3.2 Localizer — find the buggy file (grep + ast + LLM)

**What:** (1) LLM extracts distinctive search terms → (2) `git grep` them →
(3) score files by distinct-term hits → (4) `ast` maps each hit to its enclosing
function → (5) LLM ranks the top files into candidates with a score and evidence.
No vector search this milestone. Code: `nodes/localizer.py`.

```text
$ jq -c '.candidates[] | {score, file_path, function}' eval/runs/<run>/localizer.json

{"score":0.92,"file_path":"src/flask/config.py","function":"Config.from_file"}
{"score":0.64,"file_path":"tests/test_config.py","function":"test_config_missing_file"}

$ jq '.confidence' eval/runs/<run>/localizer.json
0.92
```

**Result:** correct file (`config.py → Config.from_file`) ranked #1 at **0.92** —
the localizer did its job.

---

### 3.3 Prioritizer — severity (trivial this milestone)

**What:** a passthrough on single-instance runs; a deliberate slot where Phase 2's
cross-repo blast-radius scoring will go. Code: `nodes/prioritizer.py`.

```text
$ ./bin/python -c "from src.defect_triage.nodes.prioritizer import prioritizer; \
    print(prioritizer({'candidates':[{'file_path':'x'}]}))"

{'priority_rank': 0}
```

---

### 3.4 Patch-writer — draft the diff (LLM + unidiff validation)

**What:** reads the top candidate's file, prompts the LLM for **only a unified diff**,
strips code fences, then **validates with `unidiff`**: ≤3 files, nothing outside the
repo, and **no test files** (so it can't game the harness). Code: `nodes/patch_writer.py`.

```text
$ cat eval/runs/<run>/patch_attempts/1.diff

diff --git a/src/flask/config.py b/src/flask/config.py
--- a/src/flask/config.py
+++ b/src/flask/config.py
@@ -217,6 +217,7 @@ class Config(dict):
     def from_file(
         self,
         filename: str,
         load: t.Callable[[t.IO[t.Any]], t.Mapping],
+        mode: str = "r",
         silent: bool = False,
     ) -> bool:
         ...
-            with open(filename) as f:
+            with open(filename, mode=mode) as f:
                 obj = load(f)
```

**Result:** a clean, valid unified diff. The model's fix adds a **`mode`** parameter
and opens the file with it — a reasonable, working design.

---

### 3.5 Test-runner + Harness — run the tests in Docker

**What:** the test-runner node builds a per-attempt `run_id` and hands the diff to
`harness.run_instance`, which spins up the bug's Docker image, applies the diff, runs
the `FAIL_TO_PASS` + `PASS_TO_PASS` tests, and writes a report. The harness **never
raises** — every failure returns `passed=False` with a diagnostic. Code:
`nodes/test_runner.py`, `harness.py`.

```text
$ jq '.["pallets__flask-4992"] | {patch_successfully_applied, resolved}' report.json
{ "patch_successfully_applied": true,  "resolved": false }

$ grep -E "TypeError|1 failed" test_output.txt
E   TypeError: Config.from_file() got an unexpected keyword argument 'text'
tests/test_config.py:43: TypeError
========================= 1 failed, 18 passed in 0.06s =========================
```

**Result:** the patch **applied cleanly**, but the target test **failed** — see §4.

---

### 3.6 Critic — turn a failure into actionable feedback (LLM)

**What:** only runs on failure. Categorizes it (fix-didn't-work / regression /
didn't-apply), feeds the LLM the **last 80 log lines** + the failed diff, and returns
one likely cause + one concrete next step that re-enters the patch-writer. Labels
`exhausted_retries` once the budget is spent. Code: `nodes/critic.py`.

```text
$ cat eval/runs/<run>/critic/1.txt

1) Likely cause: the patch added a `mode` parameter and used it in open(), but the
   target test tests/test_config.py::test_config_from_file_toml doesn't pass `mode` —
   the signature it calls doesn't match, so the new parameter isn't exercised.
2) Next step: in src/flask/config.py, make Config.from_file() accept the parameter the
   test actually passes and open the file in binary accordingly; align the signature
   and docstring with the TOML example.
```

The feedback is injected into the next patch attempt — this is the self-correction loop.

---

### 3.7 LLM wrapper — one traced entry point

**What:** every LLM call in the project goes through one function, wrapped in a
Langfuse span tagged with node + instance + retry. One place to change model/provider.
Code: `llm.py`.

```text
$ ./bin/python -c "from src.defect_triage.llm import complete, DEFAULT_MODEL; \
    import inspect; print('model:', DEFAULT_MODEL); \
    print('params:', list(inspect.signature(complete).parameters))"

model: gpt-5.4-nano
params: ['messages', 'node', 'instance_id', 'retry_count', 'model', 'temperature', 'kwargs']
```

No node calls an LLM directly — so every call is traced and the model is swappable in
one line (Phase 2 switches to Claude Sonnet 4.6).

---

### 3.8 Graph — the wiring (the centerpiece)

**What:** registers the six nodes, the deterministic spine, and the two conditional
edges. Routers are pure functions that read state and return the next node name.
Code: `graph.py`.

```text
$ ./bin/python -c "from src.defect_triage.graph import graph; g=graph.get_graph(); ..."

NODES: ['intake', 'localizer', 'prioritizer', 'patch_writer', 'test_runner', 'critic']
  __start__    -> intake
  intake       -> localizer
  localizer    -> prioritizer
  prioritizer  -> patch_writer
  patch_writer -> test_runner
  test_runner  -> __end__      [conditional]   (passed  -> END)
  test_runner  -> critic       [conditional]   (failed  -> critic)
  critic       -> patch_writer [conditional]   (retry_count < 2 -> retry)
  critic       -> __end__      [conditional]   (budget spent -> END)
```

---

### 3.9 Observability — the real Langfuse trace

Every node's LLM call is captured as a span under one trace per run. Below is the
**actual exported trace** for `run:pallets__flask-4992`
(trace id `8a39a235…`, model `gpt-5.4-nano`), in execution order. This is the
glass-box evidence: model, token usage, cost, and latency for every call.

| # | Span (node) | retry | Tokens in→out | Cost (USD) | Latency |
|---|---|---|---|---|---|
| 1 | `extract_terms` | 0 | 341 → 61 | $0.00014 | 2.4s |
| 2 | `rank_candidates` | 0 | 633 → 300 | $0.00050 | 4.0s |
| 3 | `patch_writer` | 0 | 3137 → 487 | $0.00124 | 4.5s |
| 4 | `patch_writer_retry` | 0 | 3175 → 441 | $0.00119 | 4.3s |
| 5 | `critic` | 0 | 2268 → 152 | $0.00064 | 2.4s |
| 6 | `patch_writer` | 1 | 3291 → 478 | $0.00126 | 3.4s |
| 7 | `patch_writer_retry` | 1 | 3329 → 351 | $0.00110 | 3.8s |
| 8 | `critic` | 1 | 2173 → 131 | $0.00060 | 1.4s |
| 9 | `patch_writer` | 2 | 3270 → 2852 | $0.00422 | 18.6s |
| 10 | `patch_writer_retry` | 2 | 3296 → 471 | $0.00125 | 4.3s |
| 11 | `critic` | 2 | 2295 → 211 | $0.00072 | 2.4s |
| | **Total (11 calls)** | | **~33,100 tokens** | **~$0.0129** | **~144s (trace)** |

**What the trace reveals:**

- **The full loop is visible end-to-end:** localize (`extract_terms` →
  `rank_candidates`), then three repair rounds (`patch_writer` → `critic`),
  matching `patch_attempts=3`, `retry_count=2`.
- **A `patch_writer_retry` fires on every attempt** — the model's first diff each
  round failed `unidiff` validation ("Unexpected hunk found"), so the node's one
  internal retry kicked in before sending to the harness. The nano model struggles
  with exact diff-hunk formatting, not just the fix itself.
- **Cost is tiny:** a complete triage attempt — localize, patch ×3, critique ×3 —
  costs **~1.3 cents** and ~33k tokens. Cheap enough to run the whole loop freely.
- **Every span is tagged** with `node`, `instance_id`, and `retry_count`, so the
  trace reads as a labelled timeline rather than anonymous API calls.

*(Raw export: `eval/langfuse/trace-pallets__flask-4992.csv`.)*

---

## 4. Why no patch resolved `flask-4992`

The same root cause defeated all three attempts.

- **The maintainers' real fix** added a parameter named **`text: bool = True`**, and
  the hidden test calls it by that exact name:
  `from_file("config.toml", tomllib.load, text=False)`.
- **The model's fix** added a parameter named **`mode: str = "r"`** instead — a
  functionally correct, arguably cleaner design.
- **The test passes `text=False`.** The model's function has no `text` parameter, so
  Python raises **before any logic runs**:

```text
E   TypeError: Config.from_file() got an unexpected keyword argument 'text'
========================= 1 failed, 18 passed in 0.06s =========================
```

All 3 attempts: **applied cleanly, 18 PASS_TO_PASS held (no regression), the 1
FAIL_TO_PASS could never pass** — it is pinned to a parameter name the model had no way
to guess from the issue text. The Critic retried twice but kept converging on `mode`.

**The lesson:** the pipeline got the *where* right (config.py, 0.92) and wrote a working
fix — but SWE-bench requires reproducing the maintainers' **exact API**, not just a
correct one. That exact-match gap is precisely what Phase 2's hybrid retrieval and
stronger/fine-tuned patch-writer target.

---

## 5. Results (full slice)

```text
$ jq '.summary' eval/results.json

{ "total": 3, "resolved": 0, "exhausted_retries": 3, "errored": 0,
  "resolution_rate": 0.0 }
```

| Metric | Value |
|---|---|
| Total instances (all Flask in SWE-bench Lite) | 3 |
| Resolved | 0 |
| Exhausted retries | 3 |
| Errored | 0 |
| **Resolution rate** | **0.0%** |
| Localization Hit@1 / Hit@2 | 2/3 / 3/3 |
| Patch applied to container | 3/3 |

**Reading it:** the loop runs end-to-end and localizes well; 0% reflects the
difficulty of exact-match repair on three hand-picked instances with a grep-only
localizer and a small model — an honest baseline, with every failure mapped to a named
Phase 2 fix. (Frontier agents reach ~20–30% on full Lite for context.)

---

## 6. How to reproduce

```bash
# one instance, end-to-end (writes eval/runs/<ts>__<instance>/)
defect-triage run --instance pallets__flask-4992

# the whole slice -> eval/results.json
defect-triage eval --instances eval/instances.txt --out eval/results.json

# inspect the most recent run
defect-triage trace --last
```

Each run records `state.json`, `localizer.json`, every `patch_attempts/<n>.diff` and
`<n>.test.log`, and every `critic/<n>.txt` — fully reproducible, and traced in Langfuse.
