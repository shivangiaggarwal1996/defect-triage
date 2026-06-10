"""Intake node: load a defect (GitHub issue + repo instance) into pipeline state.

WHAT THIS NODE DOES
-------------------
Intake is the *first* node in the LangGraph and the only one that touches the
dataset and the filesystem to set things up. It is deliberately trivial — no LLM
call. Given just an ``instance_id`` in the incoming state, it:

  1. Looks up the full SWE-bench record (problem statement, repo, base_commit).
  2. Checks out that repo at ``base_commit`` onto disk (so the Localizer can grep it).
  3. Builds a fresh, fully-seeded ``DefectState`` and attaches the local repo path.

Everything downstream (Localizer, Patch-writer, …) reads the fields Intake writes.

HOW IT FITS THE GRAPH
---------------------
The CLI starts the graph with a minimal seed — ``{"instance_id": "..."}`` — and this
node fills in the rest. A LangGraph node receives the current state and returns the
fields it wants merged back in; here we return a complete starting state.
"""

from __future__ import annotations

from ..instances import checkout_repo, load_instance
from ..state import DefectState, init_state


def intake(state: DefectState) -> DefectState:
    """Turn an ``instance_id`` into a fully-seeded :class:`DefectState`.

    Reads ``state["instance_id"]`` and writes ``instance_id``, ``problem_statement``,
    ``base_commit``, ``repo`` (the *local* checkout path), plus the zeroed bookkeeping
    counters that :func:`init_state` seeds. Makes no LLM call.

    Args:
        state: incoming graph state; only ``instance_id`` is required.

    Returns:
        A new ``DefectState`` with all Intake-owned fields populated. LangGraph
        merges this into the running state.
    """
    instance_id = state["instance_id"]

    # 1. Pull the bug record from the (cached) SWE-bench Lite dataset.
    record = load_instance(instance_id)

    # 2. Materialise the repo on disk at the bug's base_commit. Returns fast if a
    #    working copy at that commit already exists (see instances.checkout_repo).
    repo_path = checkout_repo(record)

    # 3. Build the clean starting state from the record (copies problem_statement,
    #    base_commit, instance_id and zeroes the counters), then attach the local
    #    repo path — the one Intake-owned field init_state intentionally leaves unset.
    new_state = init_state(record)
    new_state["repo"] = str(repo_path)
    return new_state


# Command to validate this file (run from the repo root):
# ./bin/python -c "
# from src.defect_triage.nodes.intake import intake
# s = intake({'instance_id': 'pallets__flask-5063'})
# assert s['problem_statement'] and s['base_commit']
# assert s['repo'].endswith('pallets__flask-5063')
# assert s['candidates'] == [] and s['retry_count'] == 0
# print('intake.py OK — repo:', s['repo'])
# "
