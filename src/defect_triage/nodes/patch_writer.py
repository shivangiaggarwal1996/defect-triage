"""Patch-writer node: draft a unified-diff patch with the LLM.

Read docs/agents/patch-writer.md before changing this.

WHERE THIS SITS IN THE PIPELINE
-------------------------------
    Intake -> Localizer -> Prioritizer -> [Patch-writer] -> Test-runner -> ...

The Localizer told us *where* the bug probably is (a ranked list of candidates). This
node's job is to actually *write the fix* for the top candidate, as a unified diff that
the Test-runner can hand straight to the SWE-bench harness.

THE ALGORITHM (per the spec)
----------------------------
  1. Read the top candidate's file from the checked-out repo (window it if it is huge,
     so we don't blow the token budget on a 3000-line file).
  2. Build a prompt: the bug report + the candidate location + the file content, plus
     the Critic's feedback verbatim if this is a retry (Day 4 wires that path; we read
     ``critic_feedback`` from state already so the code is ready for it).
  3. Ask the model for ONLY a unified diff, then CLEAN the reply: strip ```fences```
     the model loves to add, and guarantee the trailing newline that ``unidiff`` insists on.
  4. VALIDATE with ``unidiff.PatchSet``: at most 3 files, nothing outside the repo, and
     no test files (we want a real fix, not a patch that games the harness by editing
     the tests). On rejection, retry the model ONCE with the exact reason as feedback,
     then accept whatever we get — the Test-runner will record the failure if it's still
     bad. We never loop forever (spec: one internal retry).
  5. Write ``patch_attempts/<n>.diff`` into the run artefact dir, and increment the
     ``patch_attempts`` counter.

This node does NOT run tests and does NOT decide routing — it only produces a diff.
"""

from __future__ import annotations

import re
from pathlib import Path

import unidiff

from ..llm import complete
from ..state import DefectState, LocalizationCandidate

# --- Tuning knobs ----------------------------------------------------------------
# Files bigger than this are "windowed": we show only the lines around the candidate
# instead of the whole file, to keep the prompt within the token budget.
LARGE_FILE_LINES = 800
WINDOW = 100        # lines of context above/below the candidate range when windowing
MAX_FILES = 3       # scope guard: reject diffs that touch more than this many files
# Retry cap mirrored from graph.py (kept local to avoid a circular import with graph).
# Used only by the defensive hard-stop below; the graph edge is the real enforcer.
RETRY_CAP = 2


# --------------------------------------------------------------------------------
# Step 1 — read the candidate file (whole, or a window if it is large)
# --------------------------------------------------------------------------------

def _read_candidate(repo: str, candidate: LocalizationCandidate) -> tuple[str, bool]:
    """Return ``(content, windowed)`` for the candidate's file.

    Small files are returned in full. Files over ``LARGE_FILE_LINES`` are trimmed to a
    +/-``WINDOW``-line window around the candidate's reported line range, and we set
    ``windowed=True`` so the prompt can tell the model it is only seeing a slice.

    Args:
        repo: path to the checked-out repository on disk (from Intake).
        candidate: the top localization candidate (has ``file_path`` and line range).

    Returns:
        ``(content, windowed)`` — the text to show the model, and whether it was trimmed.
        If the file can't be read we return an error marker string and ``False`` so the
        model at least sees *something* and the node doesn't crash.
    """
    path = Path(repo) / candidate["file_path"]
    try:
        source = path.read_text(errors="replace")
    except OSError as exc:
        return f"<could not read {candidate['file_path']}: {exc}>", False

    lines = source.splitlines()
    if len(lines) <= LARGE_FILE_LINES:
        return source, False  # small enough — show the whole thing

    # Large file: show only the neighbourhood of the candidate lines. We number the
    # window so the model can anchor its hunk headers to real line numbers.
    start = candidate.get("line_start") or 1
    end = candidate.get("line_end") or start
    lo = max(1, start - WINDOW)
    hi = min(len(lines), end + WINDOW)
    body = "\n".join(f"{i}| {lines[i - 1]}" for i in range(lo, hi + 1))
    return f"# (file windowed to lines {lo}-{hi} of {len(lines)})\n{body}", True


# --------------------------------------------------------------------------------
# Step 2 — build the prompt
# --------------------------------------------------------------------------------

def _build_messages(
    state: DefectState,
    candidate: LocalizationCandidate,
    file_content: str,
    windowed: bool,
    extra_feedback: str | None = None,
) -> list[dict]:
    """Assemble the chat messages for one patch request.

    There are TWO kinds of "previous failure" feedback we may inject, and both go near
    the top where the model will weight them heavily:
      - ``state['critic_feedback']`` — CROSS-attempt feedback from a previous failed
        *test run* (added by the Critic on Day 4). The spec says to place this
        prominently because it is the best signal the model has.
      - ``extra_feedback`` — the INTERNAL validation error from our own one-shot retry
        within this same node (e.g. "you edited a test file").

    Args:
        state: shared pipeline state (read for ``problem_statement`` and ``critic_feedback``).
        candidate: the top candidate we are trying to fix.
        file_content: the file text (full or windowed) from :func:`_read_candidate`.
        windowed: whether ``file_content`` is only a slice (so we can say so).
        extra_feedback: validation reason to feed back on the internal retry, else None.

    Returns:
        OpenAI-style ``[{"role": "user", "content": ...}]`` messages for ``complete``.
    """
    previous = ""
    critic_feedback = state.get("critic_feedback")
    if critic_feedback:
        previous += f"\nPrevious attempt failed because:\n{critic_feedback}\n"
    if extra_feedback:
        previous += f"\nYour last diff was rejected:\n{extra_feedback}\nFix it.\n"

    window_note = " (only a window around the suspect lines is shown)" if windowed else ""

    # The prompt mirrors the "Prompt sketch" in docs/agents/patch-writer.md.
    prompt = (
        "You are fixing a bug in a Python repository. Output ONLY a unified diff that "
        "applies from the repository root. No explanation, no markdown fences, just "
        "the diff.\n\n"
        f"Bug report:\n{state['problem_statement']}\n\n"
        "Most likely buggy location:\n"
        f"- File: {candidate['file_path']}\n"
        f"- Function: {candidate.get('function')}\n"
        f"- Lines: {candidate.get('line_start')}-{candidate.get('line_end')}\n"
        f"- Why: {candidate.get('evidence')}\n\n"
        f"Current content of {candidate['file_path']}{window_note}:\n"
        f"```\n{file_content}\n```\n"
        f"{previous}\n"
        "Constraints:\n"
        "- Modify only source files, never test files.\n"
        "- Modify at most 3 files; keep the change as small as possible.\n"
        "- Output a single unified diff. Start with `diff --git` or `--- a/`.\n"
        "- Use correct a/ and b/ path prefixes relative to the repository root.\n"
    )
    return [{"role": "user", "content": prompt}]


# --------------------------------------------------------------------------------
# Step 3 — clean the model's reply into a parseable diff
# --------------------------------------------------------------------------------

def _clean_diff(text: str) -> str:
    """Strip Markdown fences and guarantee the trailing newline ``unidiff`` needs.

    Two extremely common failure modes (called out in the Day 3 pitfalls):
      - the model wraps the diff in ```diff ... ``` fences,
      - the model omits the final newline, which makes ``unidiff`` choke.
    We fix both here so validation downstream sees a clean diff.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)  # drop opening fence
        stripped = re.sub(r"\n?```$", "", stripped).strip()   # drop closing fence
    if not stripped.endswith("\n"):
        stripped += "\n"
    return stripped


# --------------------------------------------------------------------------------
# Step 4 — validate the diff (scope + safety rules from the spec)
# --------------------------------------------------------------------------------

def _strip_prefix(path: str) -> str:
    """Drop a leading ``a/`` or ``b/`` from a diff path to get the repo-relative path."""
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _is_test_file(path: str) -> bool:
    """Heuristic: does this path look like a test file we must NOT patch?

    We refuse to patch tests because the harness judges us by FAIL_TO_PASS /
    PASS_TO_PASS — editing the tests themselves would game that signal instead of
    fixing the real bug (spec: "we want real fixes, not eval gaming").
    """
    name = Path(path).name
    parts = Path(path).parts
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "tests" in parts
        or "test" in parts
        or name == "conftest.py"
    )


def _validate(diff: str, repo: str) -> str | None:
    """Return ``None`` if the diff is acceptable, else a one-line rejection reason.

    Checks, in order:
      - it parses as a unified diff at all,
      - it changes at least one and at most ``MAX_FILES`` files (keep scope tight),
      - every path stays inside the repo root (no absolute paths or ``..`` traversal),
      - no file it touches looks like a test file.

    The returned string (when not None) is fed straight back to the model as the retry
    instruction, so it is phrased as an actionable reason.
    """
    try:
        patch = unidiff.PatchSet(diff)
    except Exception as exc:  # noqa: BLE001 — any parse error is itself a rejection reason
        return f"diff did not parse as a valid unified diff: {exc}"

    if len(patch) == 0:
        return "diff contained no file changes"
    if len(patch) > MAX_FILES:
        return f"diff modifies {len(patch)} files; modify at most {MAX_FILES}"

    repo_root = Path(repo).resolve()
    for patched in patch:
        # Reject anything that escapes the repo root (path traversal / absolute path).
        for raw in (patched.source_file, patched.target_file):
            rel = _strip_prefix(raw)
            if rel in ("/dev/null", "dev/null"):
                continue  # /dev/null is how diffs denote a created/deleted file
            resolved = (repo_root / rel).resolve()
            if repo_root != resolved and repo_root not in resolved.parents:
                return f"diff touches a path outside the repo: {raw}"
        if _is_test_file(patched.path):
            return f"diff modifies a test file ({patched.path}); fix source, not tests"
    return None  # all checks passed


# --------------------------------------------------------------------------------
# Step 5 — persist the attempt to the run artefact directory
# --------------------------------------------------------------------------------

def _write_attempt(state: DefectState, attempt_no: int, diff: str) -> None:
    """Write ``patch_attempts/<n>.diff`` under the run's artefact directory.

    ``run_dir`` is seeded into the state by the CLI. If it is absent (e.g. a unit test
    that calls the node directly), we silently skip writing — the node still returns the
    diff in-memory, so behaviour is unchanged, we just don't archive it.
    """
    run_dir = state.get("run_dir")
    if not run_dir:
        return
    attempts_dir = Path(run_dir) / "patch_attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)
    (attempts_dir / f"{attempt_no}.diff").write_text(diff)


# --------------------------------------------------------------------------------
# The graph node
# --------------------------------------------------------------------------------

def patch_writer(state: DefectState) -> dict:
    """Draft a unified diff for the top candidate and archive it.

    Reads ``problem_statement``, ``candidates``, ``repo``, ``patch_attempts`` and (on a
    Day-4 retry) ``critic_feedback``. Writes the cleaned ``diff`` and the incremented
    ``patch_attempts`` counter back into the state.

    Args:
        state: the shared pipeline state; expected to contain at least one candidate.

    Returns:
        ``{"diff": <str>, "patch_attempts": <int>}`` for LangGraph to merge. ``diff`` may
        be empty (no candidates) or technically invalid (model failed twice) — in both
        cases the Test-runner will record the failure rather than this node raising.
    """
    candidates = state.get("candidates") or []
    prev_attempts = state.get("patch_attempts", 0)
    # This attempt's number = previous count + 1. Used for both the artefact filename
    # and (later) the harness run_id, so attempts never collide.
    attempt_no = prev_attempts + 1

    # --- Retry bookkeeping -------------------------------------------------------
    # This is the SINGLE place ``retry_count`` is incremented. The LangGraph router
    # after the Critic (route_after_critic) can only *read* state and return the next
    # node name — it cannot mutate state — so the increment for the Critic->Patch-writer
    # trip lives here instead (see graph.py for the routing).
    retry_count = state.get("retry_count", 0)
    # Defensive hard cap (spec pitfall: a mis-wired edge could loop forever, burning
    # tokens). With a correct graph this never trips — retry_count is at most 1 on entry.
    if retry_count > RETRY_CAP:
        raise RuntimeError(
            f"patch_writer entered with retry_count={retry_count} > cap {RETRY_CAP}; "
            "the retry edge is mis-wired (would loop forever)."
        )
    # We are on a retry iff we've already patched once: ``patch_attempts > 0`` means the
    # Critic routed us back here. The first attempt leaves retry_count at 0.
    is_retry = prev_attempts > 0
    if is_retry:
        retry_count += 1

    # Edge case: the Localizer found nothing. Record an empty diff so the Test-runner
    # fails cleanly (its empty-diff guard) instead of us crashing on candidates[0].
    if not candidates:
        _write_attempt(state, attempt_no, "")
        return {"diff": "", "patch_attempts": attempt_no, "retry_count": retry_count}

    candidate = candidates[0]  # the top-ranked suspect
    repo = state["repo"]
    file_content, windowed = _read_candidate(repo, candidate)

    # --- First attempt -----------------------------------------------------------
    messages = _build_messages(state, candidate, file_content, windowed)
    raw = complete(
        messages,
        node="patch_writer",                       # Langfuse span name
        instance_id=state["instance_id"],
        retry_count=retry_count,                   # so Langfuse labels the retry round
        max_tokens=4000,                           # diffs can be long; give headroom
    )
    diff = _clean_diff(raw)

    # --- One internal retry if invalid, feeding back the exact reason -------------
    reason = _validate(diff, repo)
    if reason is not None:
        retry_messages = _build_messages(
            state, candidate, file_content, windowed, extra_feedback=reason
        )
        raw = complete(
            retry_messages,
            node="patch_writer_retry",             # distinct span so we can see retries
            instance_id=state["instance_id"],
            retry_count=retry_count,
            max_tokens=4000,
        )
        diff = _clean_diff(raw)
        # If it is STILL invalid we keep it anyway and stop here — the spec forbids
        # looping forever; the Test-runner records the failure for the Critic.

    _write_attempt(state, attempt_no, diff)
    return {"diff": diff, "patch_attempts": attempt_no, "retry_count": retry_count}


# Command to validate this file (no LLM/Docker — monkeypatches the model, runs real unidiff):
# ./bin/python -c "
# import src.defect_triage.nodes.patch_writer as P
# DIFF = '--- a/src/flask/app.py\n+++ b/src/flask/app.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n'
# P.complete = lambda *a, **k: DIFF                       # stub out the LLM
# st = {'candidates': [{'file_path': 'src/flask/app.py', 'function': None, 'line_start': 1, 'line_end': 1, 'score': 0.9, 'evidence': 'e'}], 'repo': '/tmp', 'problem_statement': 'bug', 'instance_id': 'x', 'patch_attempts': 0}
# out = P.patch_writer(st)
# assert out['diff'].endswith('\n') and out['patch_attempts'] == 1
# assert P._validate(out['diff'], '/tmp') is None             # valid source-only diff
# assert P._is_test_file('flask/tests/test_app.py') is True   # test-file guard works
# print('patch_writer.py OK — attempt', out['patch_attempts'])
# "
