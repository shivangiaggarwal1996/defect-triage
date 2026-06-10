"""Critic node: analyse a test failure and guide the next patch attempt.

Read docs/agents/critic.md before changing this.

WHERE THIS SITS IN THE PIPELINE
-------------------------------
    ... -> Test-runner --(passed?)--> END
                 |
                 | no
                 v
            [ Critic ] --(retry_count < 2?)--> Patch-writer  (retry)
                 |
                 | no
                 v
                END (exhausted_retries)

The Test-runner just reported a FAILURE. This node's only job is to turn that failure
signal into short, actionable feedback the Patch-writer can use on its next attempt —
a specific hypothesis ("the off-by-one is on line X because Y"), not "the patch didn't
work". It produces ``critic_feedback`` text and nothing else.

WHAT THIS NODE MUST NOT DO (spec)
---------------------------------
- It does NOT generate a new diff (that's the Patch-writer's job).
- It does NOT send the whole test log to the model — only the last ~80 lines, where
  the assertions and tracebacks live. The rest is setup noise that burns tokens.
- It does NOT enforce the retry cap — the GRAPH's conditional edge decides whether to
  loop. The Critic only writes feedback (and, as a convenience, flips ``final_status``
  to ``exhausted_retries`` when it can see the budget is spent, so the END state is
  labelled correctly).
"""

from __future__ import annotations

from pathlib import Path

from ..llm import complete
from ..state import DefectState

# How many lines of the harness log to feed the model. The failing assertions and
# tracebacks live at the very end; everything before is environment/setup noise.
LOG_TAIL_LINES = 80

# The retry cap, mirrored from graph.py's route_after_critic. The Critic does not
# *enforce* it (the edge does) — it only uses it to label the terminal state.
RETRY_CAP = 2


def _read_log_tail(raw_log_path: str, n: int = LOG_TAIL_LINES) -> str:
    """Return the last ``n`` lines of the harness log, or a marker if unavailable.

    Defensive on purpose: a missing path or unreadable file must not crash the run —
    the Critic should still produce *some* feedback from the category alone, so we
    return a short marker string instead of raising.

    Args:
        raw_log_path: path to the harness log from ``test_outcome["raw_log_path"]``.
        n: how many trailing lines to keep.

    Returns:
        The log tail as text, or ``"<no log available>"`` if it can't be read.
    """
    if not raw_log_path:
        return "<no log available>"
    path = Path(raw_log_path)
    if not path.exists():
        return "<no log available>"
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError as exc:
        return f"<could not read log: {exc}>"
    return "\n".join(lines[-n:])


def _categorize(test_outcome: dict) -> str:
    """Classify the failure from the harness signal, before the LLM call.

    This cheap heuristic gives the model a strong hint about *what kind* of failure it
    is looking at (spec step 2):
      - fail-to-pass tests still failing  -> the fix did not actually fix the bug
      - pass-to-pass tests now failing     -> the fix introduced a regression
      - neither, yet ``passed`` is False   -> the diff didn't apply / harness error

    Args:
        test_outcome: the ``TestOutcome`` dict from the Test-runner.

    Returns:
        A short human-readable category string for the prompt.
    """
    if test_outcome.get("fail_to_pass_failed"):
        return "fix_did_not_work (the target failing tests are still failing)"
    if test_outcome.get("pass_to_pass_failed"):
        return "regression (the fix broke previously passing tests)"
    return "harness_or_apply_error (the patch likely failed to apply or the harness errored)"


def _build_messages(state: DefectState, category: str, log_tail: str) -> list[dict]:
    """Assemble the single chat message for the Critic, per docs/agents/critic.md.

    Sends the bug report, the diff that just failed, the failure category, and the log
    tail — and asks for exactly two things: one sentence on the likely cause and one
    concrete next step. Kept under 200 words by instruction.
    """
    prompt = (
        "A patch attempt failed. Read the bug report, the patch, and the test failure "
        "log, then explain in under 200 words what likely went wrong and what to try "
        "next.\n\n"
        f"Bug report:\n{state['problem_statement']}\n\n"
        "The patch that just failed:\n"
        f"```\n{state.get('diff', '')}\n```\n\n"
        f"Failure category: {category}\n\n"
        f"Last {LOG_TAIL_LINES} lines of the test log:\n"
        f"```\n{log_tail}\n```\n\n"
        "Write:\n"
        "1. ONE sentence: the most likely cause of the failure.\n"
        "2. ONE concrete next step: which line(s) to change and how.\n\n"
        "Do not restate the bug report. Do not apologize. Be specific."
    )
    return [{"role": "user", "content": prompt}]


def _write_feedback(state: DefectState, attempt_no: int, feedback: str) -> None:
    """Write ``critic/<n>.txt`` under the run artefact dir (no-op if no run_dir).

    ``<n>`` is the number of the patch attempt that just failed, so the feedback file
    sits alongside the matching ``patch_attempts/<n>.diff`` and ``<n>.test.log``.
    """
    run_dir = state.get("run_dir")
    if not run_dir:
        return
    critic_dir = Path(run_dir) / "critic"
    critic_dir.mkdir(parents=True, exist_ok=True)
    (critic_dir / f"{attempt_no}.txt").write_text(feedback)


def critic(state: DefectState) -> dict:
    """Turn a failed ``test_outcome`` into actionable ``critic_feedback``.

    Reads ``problem_statement``, ``diff``, ``test_outcome`` (and the tail of its log)
    and ``retry_count``. Writes ``critic_feedback`` back into the state and archives it
    to ``critic/<n>.txt``. When the retry budget is already spent it also sets
    ``final_status="exhausted_retries"`` so the END state is labelled correctly (the
    graph's conditional edge is what actually stops the loop).

    Args:
        state: shared pipeline state; only routed here when ``test_outcome.passed`` is
            False, so a failure signal is guaranteed to be present.

    Returns:
        ``{"critic_feedback": <str>}``, plus ``{"final_status": "exhausted_retries"}``
        when this is the terminal attempt.
    """
    test_outcome = state.get("test_outcome", {})
    attempt_no = state.get("patch_attempts", 1)  # the attempt that just failed
    retry_count = state.get("retry_count", 0)

    category = _categorize(test_outcome)
    log_tail = _read_log_tail(test_outcome.get("raw_log_path", ""))

    messages = _build_messages(state, category, log_tail)
    feedback = complete(
        messages,
        node="critic",                 # Langfuse span name
        instance_id=state["instance_id"],
        retry_count=retry_count,        # labels which retry round this feedback is for
        max_tokens=400,                 # < 200 words; keep it tight
    ).strip()

    _write_feedback(state, attempt_no, feedback)

    out: dict = {"critic_feedback": feedback}
    # If the budget is already spent, the edge after us routes to END — mark the
    # terminal status now so the recorded state reads "exhausted_retries", not unset.
    if retry_count >= RETRY_CAP:
        out["final_status"] = "exhausted_retries"
    return out


# Command to validate this file (no LLM/Docker — stubs the model and writes to a tmp dir):
# ./bin/python -c "
# import src.defect_triage.nodes.critic as C
# C.complete = lambda *a, **k: '1. Off-by-one on line 5.\n2. Change range(n) to range(n+1).'
# st = {'problem_statement': 'bug', 'diff': 'd', 'instance_id': 'x', 'patch_attempts': 1,
#       'retry_count': 0, 'test_outcome': {'fail_to_pass_failed': ['t'], 'pass_to_pass_failed': [], 'raw_log_path': ''}}
# out = C.critic(st)
# assert out['critic_feedback'].startswith('1.'), out
# assert 'final_status' not in out                       # budget not spent yet
# st['retry_count'] = 2
# assert C.critic(st).get('final_status') == 'exhausted_retries'   # budget spent
# print('critic.py OK')
# "
