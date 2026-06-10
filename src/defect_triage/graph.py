"""LangGraph wiring: nodes, deterministic edges, and the conditional pass/fail + retry
routing.

See docs/architecture.md for the full pipeline diagram.

DAY 4 SCOPE
-----------
The loop is now closed. After the harness runs, two CONDITIONAL edges decide what
happens next:

    START -> intake -> localizer -> prioritizer -> patch_writer -> test_runner
                                          ^                            |
                                          |                     passed? --> END (resolved)
                                          |                            | no
                                          |                            v
                                          +------ retry_count<2? ---- critic
                                                                       |
                                                              no (cap) v
                                                                      END (exhausted_retries)

- Solid (``add_edge``) arrows are deterministic: always A then B.
- The two ``add_conditional_edges`` arrows are decided by a pure ROUTER function that
  reads the state and returns the *name* of the next node. Routers cannot mutate state
  (that's why ``retry_count`` is incremented inside ``patch_writer``, not here).

HOW LANGGRAPH WORKS HERE
------------------------
- ``StateGraph(DefectState)`` declares that every node receives and returns our shared
  state dict (see state.py).
- ``add_node(name, fn)`` registers a node; the function takes the state and returns the
  fields to merge back in.
- ``add_edge(A, B)`` is a deterministic "after A, go to B" transition.
- ``add_conditional_edges(A, router, mapping)`` calls ``router(state)`` after A and
  jumps to ``mapping[router(state)]``. The router returns a routing key, not state.
- ``compile()`` produces a runnable graph object with ``.invoke(initial_state)``.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes.critic import critic
from .nodes.intake import intake
from .nodes.localizer import localizer
from .nodes.patch_writer import patch_writer
from .nodes.prioritizer import prioritizer
from .nodes.test_runner import test_runner
from .state import DefectState

# Retry cap: up to 2 retries => at most 3 patch attempts total. Mirrored in critic.py
# (for labelling) and defended against in patch_writer.py (hard stop).
RETRY_CAP = 2


def route_after_test(state: DefectState) -> str:
    """Pass/fail edge: stop on green, send a red result to the Critic.

    Args:
        state: shared pipeline state; ``test_outcome`` is set by the Test-runner.

    Returns:
        ``"END"`` if the harness passed (``final_status`` was set to ``"resolved"`` by
        the Test-runner), else ``"critic"`` to start a repair round.
    """
    if state.get("test_outcome", {}).get("passed"):
        return "END"
    return "critic"


def route_after_critic(state: DefectState) -> str:
    """Retry-budget edge: loop back to the Patch-writer until the cap is hit.

    Reads ``retry_count`` (the number of retries *already taken*, incremented on entry
    to ``patch_writer``). While it is below the cap we go back for another attempt;
    once it reaches the cap we stop with ``final_status="exhausted_retries"`` (set by
    the Critic).

    Args:
        state: shared pipeline state.

    Returns:
        ``"patch_writer"`` to retry, or ``"END"`` once the retry budget is spent.
    """
    if state.get("retry_count", 0) < RETRY_CAP:
        return "patch_writer"
    return "END"


def build_graph():
    """Build and compile the Day 4 graph (the full repair loop).

    Deterministic spine: ``intake -> localizer -> prioritizer -> patch_writer ->
    test_runner``. Then two conditional edges close the loop:
      - after ``test_runner``: END if the tests passed, else ``critic``;
      - after ``critic``: back to ``patch_writer`` while under the retry cap, else END.

    Returns:
        A compiled LangGraph app. Call ``app.invoke({"instance_id": "..."})`` to run
        it; the result is the final :class:`DefectState`.
    """
    builder = StateGraph(DefectState)

    # Register the six nodes. The string names are how edges refer to them.
    builder.add_node("intake", intake)
    builder.add_node("localizer", localizer)
    builder.add_node("prioritizer", prioritizer)
    builder.add_node("patch_writer", patch_writer)
    builder.add_node("test_runner", test_runner)
    builder.add_node("critic", critic)

    # Deterministic spine: straight through to the first harness run.
    builder.add_edge(START, "intake")
    builder.add_edge("intake", "localizer")
    builder.add_edge("localizer", "prioritizer")
    builder.add_edge("prioritizer", "patch_writer")
    builder.add_edge("patch_writer", "test_runner")

    # Conditional edge 1 — pass/fail. The mapping translates the router's return value
    # into a real destination (END is LangGraph's sentinel for "stop").
    builder.add_conditional_edges(
        "test_runner",
        route_after_test,
        {"critic": "critic", "END": END},
    )

    # Conditional edge 2 — retry budget. Loop back to patch_writer, or stop.
    builder.add_conditional_edges(
        "critic",
        route_after_critic,
        {"patch_writer": "patch_writer", "END": END},
    )

    return builder.compile()


# A module-level compiled graph for convenience (CLI imports this).
graph = build_graph()


# Command to validate this file (no LLM/keys needed — just checks it compiles/wires):
# ./bin/python -c "
# from src.defect_triage.graph import graph, build_graph
# g = build_graph()
# nodes = set(g.get_graph().nodes)
# assert {'intake', 'localizer', 'prioritizer', 'patch_writer', 'test_runner'} <= nodes, nodes
# print('graph.py OK — nodes:', sorted(nodes))
# "
