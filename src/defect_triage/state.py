"""The LangGraph state TypedDict shared across all nodes.

See docs/architecture.md section 2 for the full state schema. This module is the
single mutable structure that flows through the graph; every node reads and writes
fields here and nowhere else.
"""

from __future__ import annotations

from typing import Literal, Optional, TypedDict


class LocalizationCandidate(TypedDict):
    """One suspected bug site produced by the Localizer."""

    file_path: str            # e.g. "src/flask/app.py"
    function: Optional[str]    # e.g. "Flask.dispatch_request"
    line_start: Optional[int]
    line_end: Optional[int]
    score: float               # 0.0 to 1.0
    evidence: str              # short rationale from the Localizer


class TestOutcome(TypedDict):
    """Result of running the SWE-bench harness on a candidate patch (Day 3)."""

    passed: bool
    fail_to_pass_passed: list[str]   # SWE-bench fail-to-pass tests that flipped
    fail_to_pass_failed: list[str]
    pass_to_pass_failed: list[str]   # regressions
    raw_log_path: str


class DefectState(TypedDict, total=False):
    """Shared pipeline state. ``total=False`` so nodes fill fields incrementally."""

    # populated by Intake
    instance_id: str
    repo: str
    problem_statement: str
    base_commit: str

    # populated by Localizer
    candidates: list[LocalizationCandidate]
    confidence: float          # confidence in top candidate
    deep_search_done: bool     # if we already retried with a wider search

    # populated by Prioritizer (milestone: always passthrough on 1-instance runs)
    priority_rank: int

    # populated by Patch-writer
    diff: str                  # unified diff text
    patch_attempts: int        # incremented each retry

    # populated by Test-runner
    test_outcome: TestOutcome

    # populated by Critic
    critic_feedback: str       # plain-text actionable feedback

    # bookkeeping
    retry_count: int
    final_status: Literal["resolved", "exhausted_retries", "errored"]
    run_dir: str               # eval/runs/<timestamp>/


def init_state(instance: dict) -> DefectState:
    """Build a fresh ``DefectState`` from a raw SWE-bench Lite instance dict.

    Copies only the Intake-owned fields and seeds the bookkeeping counters so
    downstream nodes can rely on them existing. The ``repo`` path (the checked-out
    working copy) is attached later by the Intake node once the repo is on disk.

    Args:
        instance: A SWE-bench Lite record. Expected keys include ``instance_id``,
            ``problem_statement``, ``base_commit``, and ``repo`` (the upstream
            "owner/name", not yet a local path).

    Returns:
        A ``DefectState`` with Intake fields populated and counters zeroed.
    """
    return DefectState(
        instance_id=instance["instance_id"],
        problem_statement=instance["problem_statement"],
        base_commit=instance["base_commit"],
        candidates=[],
        confidence=0.0,
        deep_search_done=False,
        patch_attempts=0,
        retry_count=0,
    )
