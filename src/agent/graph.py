"""Wires the fraud-investigation nodes into a runnable `langgraph.graph.StateGraph`.

Flow (PLAN.md's 8 steps):

    trigger -> open_case -> gather_evidence -> assess -> decide_action
                    ^                                          |
                    |                              check_sufficiency (conditional edge)
                    |                                 /                \\
                    |                    request_evidence              explain -> update_memory -> END
                    |________________________________/
                    (loop back through gather_evidence)

`decide_action` runs after every `assess`, so it sets `initial_actions` the first time
(before any evidence has been requested) and `final_actions` the second time (once
`request_evidence` has run) — the pair the README's Answer Format calls
`next_best_actions.initial` / `.final`, and the clearest demonstration of the
"revises its recommendation" behavior (Fraud Policy §3b).
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from . import nodes
from .state import CaseState


def build_graph():
    graph = StateGraph(CaseState)

    graph.add_node("trigger", nodes.trigger)
    graph.add_node("open_case", nodes.open_case)
    graph.add_node("gather_evidence", nodes.gather_evidence)
    graph.add_node("assess", nodes.assess)
    graph.add_node("request_evidence", nodes.request_evidence)
    graph.add_node("decide_action", nodes.decide_action)
    graph.add_node("explain", nodes.explain)
    graph.add_node("update_memory", nodes.update_memory)

    graph.set_entry_point("trigger")
    graph.add_edge("trigger", "open_case")
    graph.add_edge("open_case", "gather_evidence")
    graph.add_edge("gather_evidence", "assess")
    graph.add_edge("assess", "decide_action")

    graph.add_conditional_edges(
        "decide_action",
        nodes.check_sufficiency,
        {"sufficient": "explain", "insufficient": "request_evidence"},
    )

    graph.add_edge("request_evidence", "gather_evidence")
    graph.add_edge("explain", "update_memory")
    graph.add_edge("update_memory", END)

    return graph.compile()


def run_case(entity_id: str, trigger_type: str = "risk_score", description: str = "") -> CaseState:
    app = build_graph()
    initial: CaseState = {
        "trigger": {
            "trigger_type": trigger_type,  # type: ignore[typeddict-item]
            "entity_id": entity_id,
            "raw_risk_score": None,
            "description": description,
        },
        "max_rounds": 2,
    }
    return app.invoke(initial)


def _print_case(state: CaseState) -> None:
    print("=" * 70)
    print(f"case_id={state.get('case_id')} status={state.get('status')}")
    assessment = state.get("risk_assessment")
    if assessment:
        print(f"risk_assessment: {assessment.model_dump()}")
    print(f"rounds_used={state.get('round_count')} evidence_items={len(state.get('case_evidence', []))} "
          f"exposure_usd={state.get('exposure_usd')}")
    initial = state.get("initial_actions", [])
    final = state.get("final_actions", [])
    print(f"initial_actions: {[a.model_dump() for a in initial]}")
    print(f"final_actions:   {[a.model_dump() for a in final]}")
    if [a.action for a in initial] != [a.action for a in final]:
        print(f"revised recommendation: True — {state.get('what_changed')}")
    print(f"stop_reason: {state.get('stop_reason')}")
    print(f"explanation: {state.get('explanation')}")
    print("--- scratchpad ---")
    for m in state.get("messages", []):
        print(f"  {m}")


if __name__ == "__main__":
    scenarios = [
        ("card-clean-001", "risk_score", "Low routine risk score flagged for review."),
        ("card-ring-777", "risk_score", "High velocity risk score on a new account."),
        ("card-ambig-042", "analyst_request", "Analyst flagged an unusual large purchase."),
    ]
    for entity_id, trigger_type, description in scenarios:
        final_state = run_case(entity_id, trigger_type, description)
        _print_case(final_state)
