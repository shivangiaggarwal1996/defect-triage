"""Prioritizer node: severity/priority ranking for a defect.

WHERE THIS SITS IN THE PIPELINE
-------------------------------
    Intake -> Localizer -> [Prioritizer] -> Patch-writer -> Test-runner -> ...

The Localizer has just figured out *where* the bug probably is. Before we spend an
LLM call drafting a patch, a real triage system would ask "*how important* is this
defect, and in what order should we tackle it?" — that ranking job is the
Prioritizer's.

WHY IT IS A PASSTHROUGH FOR THE MILESTONE
-----------------------------------------
The full Prioritizer is designed to rank a *cluster of many defects* by cross-repo
"blast radius" — i.e. how many downstream call sites / repositories a given fix would
ripple into. That work is explicitly DEFERRED for this milestone (see CLAUDE.md
section 2 "deferred: cross-repo blast-radius prioritization" and docs/milestone-plan.md).

For the milestone we run the pipeline on ONE instance at a time. With a single defect
in flight there is nothing to compare it against, so its priority is trivially the
top of the queue. Rather than delete the node — which would hide a real part of the
architecture — we keep it as a deliberate no-op. That keeps the graph's shape
(Localizer -> Prioritizer -> Patch-writer) matching docs/architecture.md, and gives
the future blast-radius logic an obvious home to grow into.

WHAT THE NODE READS / WRITES
----------------------------
- Reads:  nothing it needs to act on (the single candidate set is already ranked by
          the Localizer, so there is no ordering decision to make here yet).
- Writes: ``priority_rank = 0`` — "rank 0" = highest priority / first in line. We write
          it explicitly (instead of skipping) so the saved ``state.json`` records that
          prioritization actually ran, and so downstream code can always rely on the
          field existing.
"""

from __future__ import annotations

from ..state import DefectState


def prioritizer(state: DefectState) -> dict:
    """Assign a priority rank to the current defect (milestone: always 0).

    A LangGraph node receives the whole shared :class:`DefectState` and returns only
    the field(s) it wants merged back into that state. Here we contribute a single
    field, ``priority_rank``.

    Milestone behaviour: with exactly one defect in the pipeline there is nothing to
    sort, so we hard-code rank 0 (highest priority). The full cross-repo blast-radius
    scoring that would make this rank meaningful across many defects is Phase 2 work
    (see this module's docstring and docs/milestone-plan.md).

    Args:
        state: the shared pipeline state. Unused in the milestone passthrough, but kept
            in the signature because every LangGraph node is called with the state and
            the real Prioritizer will read ``candidates`` from it.

    Returns:
        ``{"priority_rank": 0}`` — LangGraph merges this into the running state, so
        after this node ``state["priority_rank"] == 0``.
    """
    return {"priority_rank": 0}


# Command to validate this file (no LLM/Docker/keys needed — pure function):
# ./bin/python -c "
# from src.defect_triage.nodes.prioritizer import prioritizer
# out = prioritizer({'instance_id': 'pallets__flask-5063'})
# assert out == {'priority_rank': 0}, out
# print('prioritizer.py OK —', out)
# "
