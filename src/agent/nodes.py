"""Graph nodes for the fraud-investigation agent, one function per PLAN.md step.

Every node takes and returns a (partial) `CaseState` dict — LangGraph merges the
returned keys into the running state. `check_sufficiency` is exported separately
because it is a CONDITIONAL EDGE (routing function), not a node with side effects.

`decision_matrix` implements the README's Fraud Policy rules R1-R10 (`data/raw/
README.md`, "Fraud Policy" section) as code, not prompt text, since next-best-action
quality — including revising the recommendation as evidence arrives — is 25% of the
hackathon score.
"""

from __future__ import annotations

import uuid
from typing import Literal

from . import llm, tools
from .state import (
    ActionItem,
    CaseState,
    EvidenceItem,
    EvidenceRequestRecord,
    RiskAssessment,
    ToolEvidence,
    TriggerInfo,
)


def trigger(state: CaseState) -> CaseState:
    raw = dict(state.get("trigger") or {})
    if "entity_id" not in raw:
        raise ValueError("trigger requires an entity_id")
    normalized: TriggerInfo = {
        "trigger_type": raw.get("trigger_type", "risk_score"),
        "entity_id": raw["entity_id"],
        "raw_risk_score": raw.get("raw_risk_score"),
        "description": raw.get("description", ""),
    }
    return {
        "trigger": normalized,
        "tool_evidence": [],
        "case_evidence": [],
        "evidence_requests": [],
        "round_count": 0,
        "max_rounds": state.get("max_rounds", 2),
        "risk_assessment": None,
        "verdict": None,
        "fraud_probability": None,
        "pattern": None,
        "pattern_description": "",
        "affected_txn_ids": [],
        "first_suspicious_txn_id": "",
        "connected_card_ids": [],
        "connected_device_profiles": [],
        "exposure_usd": 0.0,
        "similar_prior_cases": [],
        "summary": "",
        "written_to_graph": False,
        "graph_case_id": "",
        "initial_actions": [],
        "final_actions": [],
        "what_changed": "",
        "stop_reason": "",
        "explanation": None,
        "finalized": False,
        "status": "open",
        "messages": [f"trigger: {normalized['trigger_type']} on {normalized['entity_id']}"],
    }


def open_case(state: CaseState) -> CaseState:
    entity_id = state["trigger"]["entity_id"]
    case_id = f"CASE-{entity_id}-{uuid.uuid4().hex[:6]}"
    return {
        "case_id": case_id,
        "status": "open",
        "messages": state.get("messages", []) + [f"open_case: assigned {case_id}"],
    }


def gather_evidence(state: CaseState) -> CaseState:
    """ReAct-style evidence pull. Calls every mock tool once per round; the tools
    module (not this node) decides what data comes back, so swapping in real
    TigerGraph MCP tool calls only changes `tools.py`.

    Populates two parallel lists: `tool_evidence` (raw, feeds `assess`'s reasoning)
    and `case_evidence` (claim-shaped, feeds the answer format's `case.evidence`
    directly — this is what a human or the benchmark scorer reads).
    """
    entity_id = state["trigger"]["entity_id"]
    round_num = state.get("round_count", 0)
    tool_collected: list[ToolEvidence] = []
    case_collected: list[EvidenceItem] = []

    def add_tool(source: str, data: dict, summary: str) -> None:
        tool_collected.append({"source": source, "round": round_num, "summary": summary, "data": data})

    def add_claim(claim: str, source: str, ref: str, entity_ids: list[str]) -> None:
        case_collected.append({"claim": claim, "source": source, "ref": ref, "entity_ids": entity_ids})  # type: ignore[typeddict-item]

    txn = tools.card_transaction_window(entity_id, round=round_num)
    add_tool("card_transaction_window", txn,
              f"{len(txn.get('transactions', []))} txns, velocity_flag={txn.get('velocity_flag')}")
    txn_ids = [t["id"] for t in txn.get("transactions", [])]
    add_claim(
        f"{len(txn.get('transactions', []))} transactions in the review window"
        + (", velocity flag raised" if txn.get("velocity_flag") else ""),
        "graph", f"query:card_transaction_window({entity_id})", txn_ids,
    )

    profile = tools.customer_profile(entity_id)
    add_tool("customer_profile", profile,
              f"account_age_days={profile.get('account_age_days')}, avg_spend={profile.get('avg_monthly_spend')}")

    device = tools.device_shared_accounts(entity_id)
    add_tool("device_shared_accounts", device,
              f"shared_account_count={device.get('shared_account_count')}")
    if device.get("shared_account_count", 1) >= 2:
        add_claim(
            f"Device profile linked to {device.get('shared_account_count')} customers: "
            + ", ".join(device.get("linked_customers", [])),
            "graph", f"query:device_shared_accounts({entity_id})", device.get("linked_customers", []),
        )

    ring = tools.fraud_ring_component(entity_id)
    add_tool("fraud_ring_component", ring,
              f"component_size={ring.get('component_size')}, known_fraud_members={ring.get('known_fraud_members')}")
    if ring.get("known_fraud_members", 0) > 0:
        add_claim(
            f"Connected component of size {ring.get('component_size')} includes "
            f"{ring.get('known_fraud_members')} known-fraud members",
            "graph", f"query:fraud_ring_component({entity_id})", [],
        )

    similar = tools.similar_closed_cases(entity_id)
    add_tool("similar_closed_cases", similar, f"{len(similar.get('cases', []))} similar cases")
    prior_ids = [c["case_id"] for c in similar.get("cases", []) if c.get("similarity", 0) >= 0.5]
    if prior_ids:
        add_claim(
            f"{len(prior_ids)} similar prior case(s) retrieved from case memory",
            "graph", f"query:similar_closed_cases({entity_id})", prior_ids,
        )

    policy = tools.policy_search(entity_id)
    add_tool("policy_search", policy, f"{len(policy.get('chunks', []))} policy chunks")

    return {
        "tool_evidence": state.get("tool_evidence", []) + tool_collected,
        "case_evidence": state.get("case_evidence", []) + case_collected,
        "similar_prior_cases": sorted(set(state.get("similar_prior_cases", []) + prior_ids)),
        "round_count": round_num + 1,
        "messages": state.get("messages", []) + [
            f"gather_evidence round {round_num}: collected {len(tool_collected)} tool results, "
            f"{len(case_collected)} case-evidence claims"
        ],
    }


def _evidence_narrative(tool_evidence: list[ToolEvidence]) -> str:
    lines = [f"- {e['source']} (round {e['round']}): {e['summary']}" for e in tool_evidence]
    return "Evidence gathered so far:\n" + "\n".join(lines) if lines else "No evidence gathered yet."


def assess(state: CaseState) -> CaseState:
    narrative = _evidence_narrative(state.get("tool_evidence", []))
    assessment: RiskAssessment = llm.assess_risk_from_evidence(narrative)
    return {
        "risk_assessment": assessment,
        "verdict": assessment.verdict,
        "fraud_probability": assessment.fraud_probability,
        "pattern": assessment.pattern,
        "pattern_description": assessment.pattern_description,
        "messages": state.get("messages", []) + [
            f"assess: verdict={assessment.verdict} p={assessment.fraud_probability:.2f} "
            f"pattern={assessment.pattern} gaps={assessment.evidence_gaps}"
        ],
    }


def _settled_by_verification(state: CaseState) -> bool:
    """A verification response (owner confirm/deny, step-up pass/fail) directly
    resolves the question regardless of the probability thresholds — README §6,
    second bullet: "a verification response settles the question"."""
    for e in state.get("tool_evidence", []):
        if e["source"] == "validate_transaction_with_owner":
            return True
        if e["source"] == "step_up_auth":
            return True
    return False


def check_sufficiency(state: CaseState) -> Literal["sufficient", "insufficient"]:
    """Conditional edge — no side effects. Implements the README's stopping rule
    (Fraud Policy §6): stop at p>=0.85 or p<=0.15 with 2+ independent evidence
    pieces, or when a verification response settles it, or at the round cap.
    """
    assessment: RiskAssessment = state["risk_assessment"]
    round_count = state.get("round_count", 0)
    max_rounds = state.get("max_rounds", 2)

    # Hard cap: never loop forever waiting for confidence that evidence isn't providing.
    # Further steps being "unlikely to change the decision" is the README's third
    # stopping condition; the cap is how that gets enforced mechanically.
    if round_count >= max_rounds:
        return "sufficient"

    if _settled_by_verification(state):
        return "sufficient"

    independent_evidence = len({e["ref"] for e in state.get("case_evidence", [])})
    extreme = assessment.fraud_probability >= 0.85 or assessment.fraud_probability <= 0.15
    if extreme and independent_evidence >= 2:
        return "sufficient"

    return "insufficient"


def request_evidence(state: CaseState) -> CaseState:
    """Simulates a controlled, policy-approved action to close an evidence gap
    (Fraud Policy §5 — customer/analyst replies are NOT provided by the exam; the
    agent must simulate them and record the assumption). Capping happens in
    `check_sufficiency`, not here — this node just performs one action per call.
    """
    entity_id = state["trigger"]["entity_id"]
    assessment: RiskAssessment = state["risk_assessment"]
    gaps = assessment.evidence_gaps
    round_num = state.get("round_count", 0)

    if any("owner confirmation" in g for g in gaps) or assessment.pattern in (
        "card_testing", "card_not_present_fraud", "card_not_present_new_device",
    ):
        txn_rounds = [e for e in state["tool_evidence"] if e["source"] == "card_transaction_window"]
        transactions = txn_rounds[-1]["data"].get("transactions", []) if txn_rounds else []
        txn_id = transactions[-1]["id"] if transactions else "unknown"
        result = tools.validate_transaction_with_owner(entity_id, txn_id)
        source = "validate_transaction_with_owner"
        req_type = "customer_validation"
        assumed = f"Customer {'confirmed' if result.get('confirmed') else 'denied'} making transaction {txn_id}"
    elif assessment.pattern == "account_takeover":
        result = tools.step_up_auth(entity_id)
        source = "step_up_auth"
        req_type = "step_up_auth"
        assumed = f"Step-up authentication {'passed' if result.get('passed') else 'failed'}"
    else:
        result = tools.ask_analyst(entity_id, "Ambiguous signal — please take a quick look.")
        source = "ask_analyst"
        req_type = "analyst_info"
        assumed = str(result.get("response"))

    new_tool_evidence: ToolEvidence = {
        "source": source, "round": round_num, "summary": str(result), "data": result,
    }
    new_case_evidence: EvidenceItem = {
        "claim": assumed, "source": "customer" if req_type == "customer_validation" else "external",
        "ref": f"evidence_request:{len(state.get('evidence_requests', [])) + 1}", "entity_ids": [],
    }
    new_request: EvidenceRequestRecord = {
        "type": req_type, "asked_after_step": round_num, "assumed_response": assumed,  # type: ignore[typeddict-item]
    }
    return {
        "tool_evidence": state.get("tool_evidence", []) + [new_tool_evidence],
        "case_evidence": state.get("case_evidence", []) + [new_case_evidence],
        "evidence_requests": state.get("evidence_requests", []) + [new_request],
        "messages": state.get("messages", []) + [f"request_evidence: {source} -> {result}"],
    }


def _derive_policy_context(state: CaseState) -> dict:
    """Pulls the situational facts `decision_matrix` needs out of the evidence
    collected so far. Kept separate from the matrix itself so the matrix reads as
    pure rule logic."""
    tool_evidence = state.get("tool_evidence", [])

    def latest(source: str) -> dict:
        matches = [e for e in tool_evidence if e["source"] == source]
        return matches[-1]["data"] if matches else {}

    validation = latest("validate_transaction_with_owner")
    step_up = latest("step_up_auth")
    device = latest("device_shared_accounts")
    ring = latest("fraud_ring_component")
    txn = latest("card_transaction_window")

    customer_response = "none"
    if validation:
        customer_response = "confirmed" if validation.get("confirmed") else "denied"
    elif step_up and not step_up.get("passed", True):
        customer_response = "denied"  # failed step-up treated as a denial-equivalent signal

    shared_origin = device.get("shared_account_count", 1) >= 2 or ring.get("known_fraud_members", 0) > 0
    shared_desc = ""
    if device.get("shared_account_count", 1) >= 2:
        shared_desc = f"device shared across {device.get('shared_account_count')} customers"
    elif ring.get("known_fraud_members", 0) > 0:
        shared_desc = f"{ring.get('known_fraud_members')} known-fraud members in the connected component"

    transactions = txn.get("transactions", [])
    exposure_usd = round(sum(abs(t.get("amount", 0)) for t in transactions), 2)
    already_cleared_large_purchase = any(t.get("amount", 0) > 100 for t in transactions)

    # Single-signal per R1: true unless a second independent signal (device fan-out
    # or ring membership) already corroborates the initial risk score / pattern hit.
    single_signal = not shared_origin

    return {
        "exposure_usd": exposure_usd,
        "customer_response": customer_response,
        "shared_origin": shared_origin,
        "shared_origin_desc": shared_desc,
        "already_cleared_large_purchase": already_cleared_large_purchase,
        "single_signal": single_signal,
        # Not modeled by the mock scenarios; real evidence would set these from
        # closed-case / customer-profile lookups (R7, R10).
        "recurring_pattern_dispute": False,
        "two_plus_cards_confirmed_fraud": False,
        "credentials_confirmed_compromised": False,
    }


_ACTION_ORDER = [
    "DECLINE_TRANSACTION", "STEP_UP_AUTH", "VERIFY_WITH_CUSTOMER", "BLOCK_CARD", "BLOCK_ALL_CARDS",
    "CLOSE_NO_FRAUD", "ALLOW_TRANSACTION",
    "CREATE_CASE", "FILE_REPORT", "GENERATE_REPORT",
    "MONITOR_CARD", "MONITOR_CONNECTED_CARDS", "WARN_CUSTOMER", "ESCALATE_TO_ANALYST",
]


def decision_matrix(assessment: RiskAssessment, ctx: dict) -> list[ActionItem]:
    """Implements Fraud Policy rules R1-R10 (`data/raw/README.md`) as code, since
    next-best-action quality is directly and heavily graded. Each action's `reason`
    cites the rule it came from, per policy §7 ("Explaining").
    """
    actions: dict[str, ActionItem] = {}

    def add(action: str, route: str, reason: str) -> None:
        if action not in actions:
            actions[action] = ActionItem(action=action, route=route, reason=reason)  # type: ignore[arg-type]

    block_route = "L1" if ctx["exposure_usd"] <= 2500 else "L2"

    # R3 — confirmation closes the question outright; nothing else applies.
    if ctx["customer_response"] == "confirmed":
        add("CLOSE_NO_FRAUD", "auto", "R3: customer confirmed the transaction")
        return [actions[a] for a in _ACTION_ORDER if a in actions]

    if ctx["customer_response"] == "denied":
        add("BLOCK_CARD", block_route, "R2: customer denied the transaction")
        add("CREATE_CASE", "auto", "R2: customer denied the transaction")
        if ctx["exposure_usd"] > 1000 or ctx["shared_origin"]:
            reason = (f"R2: exposure ${ctx['exposure_usd']:.2f} exceeds $1,000"
                      if ctx["exposure_usd"] > 1000 else f"R2: connects to {ctx['shared_origin_desc']}")
            add("FILE_REPORT", "L2", reason)
    elif ctx["customer_response"] == "no_reply":
        add("MONITOR_CARD", "auto", "R4: no reply within 24 hours")
        add("DECLINE_TRANSACTION", "L1", "R4: no reply, pending authorization")
        if ctx["exposure_usd"] > 500:
            add("ESCALATE_TO_ANALYST", "auto", "R4: exposure exceeds $500 with no reply")
    elif ctx["recurring_pattern_dispute"]:
        add("CREATE_CASE", "auto", "R7: dispute matches the customer's own recurring pattern")
        add("VERIFY_WITH_CUSTOMER", "auto", "R7: recurring pattern, confirm rather than block")
        add("WARN_CUSTOMER", "auto", "R7: informational note on the recurring charge")
    elif assessment.pattern == "card_testing":
        add("DECLINE_TRANSACTION", "L1", "R5: card testing sequence observed")
        add("STEP_UP_AUTH", "auto", "R5: card testing sequence observed")
        if ctx["already_cleared_large_purchase"]:
            add("BLOCK_CARD", block_route, "R5: a purchase over $100 already cleared")
    elif ctx["single_signal"] and assessment.fraud_probability < 0.70:
        add("VERIFY_WITH_CUSTOMER", "auto",
            f"R1: probability {assessment.fraud_probability:.2f} rests on a single signal, verify before blocking")
    elif assessment.fraud_probability >= 0.70:
        add("BLOCK_CARD", block_route,
            f"R1: probability {assessment.fraud_probability:.2f} clears the single-signal verification threshold")
    else:
        add("MONITOR_CARD", "auto", "Signal inconclusive; monitor while more evidence is gathered")

    # R6 — shared origin recommendations apply on top of whatever branch fired above.
    if ctx["shared_origin"]:
        add("MONITOR_CONNECTED_CARDS", "auto", f"R6: shared origin — {ctx['shared_origin_desc']}")
        add("CREATE_CASE", "auto", f"R6: shared origin — {ctx['shared_origin_desc']}")
        if ctx["customer_response"] != "confirmed":
            add("FILE_REPORT", "L2", f"R6: shared origin — {ctx['shared_origin_desc']}")

    # R9 — undocumented pattern with coordination across customers.
    if assessment.pattern == "undocumented" and ctx["shared_origin"]:
        add("CREATE_CASE", "auto", "R9: undocumented coordinated pattern")
        add("FILE_REPORT", "L2", "R9: undocumented coordinated pattern")
        add("ESCALATE_TO_ANALYST", "auto", "R9: undocumented coordinated pattern")

    # R8 — uncertainty plus exposure or conflicting evidence must escalate.
    if assessment.verdict == "uncertain" and (ctx["exposure_usd"] > 500 or assessment.evidence_gaps):
        add("ESCALATE_TO_ANALYST", "auto", "R8: uncertain verdict with exposure above $500 or open evidence gaps")

    # 3a — a case opens once fraud probability reaches 0.30, whatever else fired.
    if assessment.fraud_probability >= 0.30 and "CLOSE_NO_FRAUD" not in actions:
        add("CREATE_CASE", "auto", "3a: fraud probability reached the 0.30 case-opening threshold")

    # R10 — hard gate. No rule above adds BLOCK_ALL_CARDS; this only protects against
    # a future rule doing so without checking the precondition.
    if "BLOCK_ALL_CARDS" in actions and not (
        ctx["two_plus_cards_confirmed_fraud"] or ctx["credentials_confirmed_compromised"]
    ):
        del actions["BLOCK_ALL_CARDS"]

    return [actions[a] for a in _ACTION_ORDER if a in actions]


def decide_action(state: CaseState) -> CaseState:
    assessment: RiskAssessment = state["risk_assessment"]
    ctx = _derive_policy_context(state)
    actions = decision_matrix(assessment, ctx)

    update: CaseState = {
        "exposure_usd": ctx["exposure_usd"],
        "messages": state.get("messages", []) + [
            f"decide_action: {[a.action for a in actions]} "
            f"routes={[a.route for a in actions]}"
        ],
    }
    if not state.get("initial_actions"):
        update["initial_actions"] = actions
        update["final_actions"] = actions  # README: "If you requested nothing, final equals initial"
    else:
        update["final_actions"] = actions
        prior = [a.action for a in state["initial_actions"]]
        now = [a.action for a in actions]
        update["what_changed"] = (
            "nothing" if prior == now else
            f"Initial actions {prior} became {now} after evidence request "
            f"(customer_response={ctx['customer_response']})."
        )
    return update


def _explain_narrative(state: CaseState) -> str:
    assessment: RiskAssessment = state["risk_assessment"]
    initial = [a.action for a in state.get("initial_actions", [])]
    final = [a.action for a in state.get("final_actions", [])]
    parts = [
        f"Case {state.get('case_id')}. Verdict: {assessment.verdict}, "
        f"fraud_probability={assessment.fraud_probability:.2f}, pattern={assessment.pattern}.",
        f"Rationale: {assessment.rationale}",
        _evidence_narrative(state.get("tool_evidence", [])),
        f"Initial recommended actions: {initial}.",
        f"Final recommended actions: {final}.",
    ]
    if initial != final:
        parts.append(f"What changed: {state.get('what_changed', '')}")
    return "\n".join(parts)


def explain(state: CaseState) -> CaseState:
    explanation = llm.generate_explanation(_explain_narrative(state))
    stop_reason = state.get("stop_reason") or (
        "Round cap reached before a settling response arrived."
        if state.get("round_count", 0) >= state.get("max_rounds", 2)
        and not _settled_by_verification(state)
        else "Verification response settled the question."
        if _settled_by_verification(state)
        else f"Fraud probability {state['risk_assessment'].fraud_probability:.2f} "
             "reached the stopping threshold with independent corroborating evidence."
    )
    return {
        "explanation": explanation,
        "stop_reason": stop_reason,
        "messages": state.get("messages", []) + ["explain: explanation generated"],
    }


def update_memory(state: CaseState) -> CaseState:
    """STUB for writing the Case vertex + Case.emb embedding back to TigerGraph.
    No live Savanna connection exists yet, so this only logs the payload that would
    be written (`upsert_vectors` / `add_nodes` over the held MCP session, per PLAN.md).
    """
    assessment: RiskAssessment = state["risk_assessment"]
    status = "closed_fraud" if assessment.verdict == "fraud" else (
        "closed_legitimate" if assessment.verdict == "legitimate" else "escalated"
    )
    payload = {
        "case_id": state.get("case_id"),
        "status": status,
        "verdict": assessment.verdict,
        "fraud_probability": assessment.fraud_probability,
        "pattern": assessment.pattern,
        "initial_actions": [a.model_dump() for a in state.get("initial_actions", [])],
        "final_actions": [a.model_dump() for a in state.get("final_actions", [])],
        "what_changed": state.get("what_changed", "nothing"),
        "explanation": state.get("explanation"),
        "evidence_count": len(state.get("case_evidence", [])),
    }
    print(f"[update_memory] WOULD WRITE Case vertex + Case.emb to TigerGraph: {payload}")
    return {
        "status": status,
        "written_to_graph": True,
        "graph_case_id": state.get("case_id", ""),
        "finalized": True,
        "messages": state.get("messages", []) + ["update_memory: case finalized (mock write)"],
    }
