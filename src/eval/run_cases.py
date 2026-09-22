"""Runs the agent against all 20 cases in case_pack.csv and writes the graded
answer files to cases/<case_id>.json, exactly matching the README's
Answer Format section.

Reuses the building blocks already validated on mock scenarios rather than
retrofitting async MCP calls into the existing synchronous LangGraph
(src/agent/graph.py, kept as-is as the demonstration of the mechanism):
`decision_matrix` and `RiskAssessment`/`ActionItem` from the agent module,
the real `McpToolbox` for graph evidence, real Gemini for reasoning.

Evidence-response simulation (README §5: customer/analyst replies are not
provided by the exam): grounded in the case's own retrieved evidence rather
than an arbitrary coin flip. If a majority of the similar prior cases
retrieved for this card/pattern were confirmed_fraud, assume the customer
denies the transaction; if a majority were cleared, assume they confirm.
Ties fall back to the assessed fraud_probability. The exact reasoning is
recorded in `evidence_requests[].assumed_response` per the README's
instruction to state the assumption made.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pandas as pd

from src.agent import llm
from src.agent.mcp_tools import McpToolbox
from src.agent.nodes import decision_matrix
from src.agent.state import ActionItem, RiskAssessment
from src.rag.embed import embed_text
from src.tg.connection import get_connection

ROOT = Path(__file__).resolve().parents[2]
DERIVED = ROOT / "data" / "derived"
# README: "Submit ... in a folder called cases/ in your repository" -- this
# is the literal graded output path, not a build artifact under out/.
OUT_DIR = ROOT / "cases"
MAX_ROUNDS = 2


def _load_transaction_index() -> dict[str, dict]:
    """Local lookup for the flagged transaction's own attributes (amount, ts,
    device_id, ...) -- these are already in the derived CSV from ETL, so a
    graph round trip for a single known-id row would be pure overhead."""
    df = pd.read_csv(DERIVED / "transactions.csv", dtype={"transaction_id": str})
    df = df.set_index("transaction_id")
    return df.to_dict(orient="index")


_TXN_INDEX = _load_transaction_index()


def _fmt_txn(row: dict) -> str:
    return (
        f"${row['amount']:.2f} {row['product_cd']} transaction, {row['channel']}, "
        f"risk_score={row['risk_score']}, billing region {row.get('addr1')}"
    )


async def gather_evidence(case: dict, tb: McpToolbox) -> tuple[str, dict]:
    """Returns (evidence_narrative, ctx) where ctx carries the structured
    facts decision_matrix needs (exposure, shared_origin, etc)."""
    flagged_id = str(int(case["flagged_txn_id"]))
    card_id = case["card_id"]
    customer_id = case["customer_id"]
    flagged = _TXN_INDEX.get(flagged_id, {})

    profile = await tb.customer_profile(customer_id)
    window = await tb.card_transaction_window(card_id, limit_n=30)
    device_id = flagged.get("device_id")
    device_result = await tb.device_shared_accounts(device_id) if isinstance(device_id, str) and device_id else {}
    ring = await tb.fraud_ring_component(flagged_id)

    query_text = (
        f"{case['trigger_type']}: {case['trigger_text']} Card {card_id}, "
        f"amount ${flagged.get('amount', 0):.2f}, product {flagged.get('product_cd')}, "
        f"channel {flagged.get('channel')}."
    )
    # embed_content is a free enrichment, not core evidence -- degrade gracefully
    # if the embedding API is unavailable (e.g. the ~1000/day free-tier cap)
    # rather than failing the whole case over a missing "similar cases" lookup.
    try:
        query_vec = embed_text(query_text, task_type="RETRIEVAL_QUERY")
        similar = await tb.similar_closed_cases(query_vec, k=3)
        policy = await tb.policy_search(query_vec, k=3)
    except Exception as e:  # noqa: BLE001
        print(f"    [gather_evidence] embedding/vector search unavailable ({type(e).__name__}), "
              f"continuing without case-memory/policy retrieval for this case")
        similar, policy = {}, {}

    similar_cases = similar.get("Results", []) if isinstance(similar, dict) else []
    similar_outcomes = [c.get("attributes", {}).get("outcome") for c in similar_cases if isinstance(c, dict)]
    similar_ids = [c.get("v_id") for c in similar_cases if isinstance(c, dict)]

    policy_chunks = policy.get("Results", []) if isinstance(policy, dict) else []
    policy_texts = [c.get("attributes", {}).get("text", "") for c in policy_chunks if isinstance(c, dict)]

    txns = window.get("transactions", [])
    shared_customers = device_result.get("@@customer_ids", []) if device_result else []
    ring_cards_raw = ring.get("@@connected_card_ids", []) if ring else []
    known_fraud_cards_raw = ring.get("@@known_fraud_card_ids", []) if ring else []

    # Some device fingerprints are generic rather than unique (e.g. bare "iOS
    # Device" + a common OS/browser/resolution combo, seen on 168 unrelated
    # transactions in testing) -- a large "shared" count is a sign of a
    # coarse fingerprint colliding across strangers, not a real ring. Treat
    # anything above this threshold as non-diagnostic rather than evidence.
    GENERIC_DEVICE_THRESHOLD = 15
    device_is_generic = len(shared_customers) > GENERIC_DEVICE_THRESHOLD or len(ring_cards_raw) > GENERIC_DEVICE_THRESHOLD
    shared_origin = 1 < len(shared_customers) <= GENERIC_DEVICE_THRESHOLD
    ring_cards = [] if device_is_generic else ring_cards_raw
    known_fraud_cards = [] if device_is_generic else known_fraud_cards_raw

    narrative_parts = [
        f"TRIGGER: {case['trigger_type']} -- {case['trigger_text']}",
        f"Flagged transaction {flagged_id}: {_fmt_txn(flagged)}." if flagged else f"Flagged transaction {flagged_id}: attributes unavailable.",
        f"Customer profile: {profile.get('@@txn_count', 0)} total transactions, "
        f"${profile.get('@@total_amount', 0):.2f} total spend, "
        f"{len(profile.get('@@card_ids', []))} card(s), "
        f"{len(profile.get('@@device_ids', []))} distinct device(s) used, "
        f"{len(profile.get('@@billing_region_ids', []))} distinct billing region(s).",
        f"Recent activity on this card ({len(txns)} transactions in window): "
        + "; ".join(_fmt_txn(t.get("attributes", t)) for t in txns[:10] if isinstance(t, dict)),
    ]
    if device_id and device_is_generic:
        narrative_parts.append(
            f"Device profile {device_id} is linked to {len(shared_customers)} customers -- too many to be a "
            "meaningful signal; this is a generic device fingerprint (e.g. a common phone/OS/browser "
            "combination), not evidence of a shared physical device. Treat as non-diagnostic."
        )
    elif device_id and shared_customers:
        narrative_parts.append(
            f"Device profile {device_id} is linked to {len(shared_customers)} customer(s): {shared_customers}."
        )
    elif device_id:
        narrative_parts.append(f"Device profile {device_id} is used only by this customer.")
    else:
        narrative_parts.append("This transaction has no linked device profile (in-person / no identity record).")
    narrative_parts.append(
        f"Other cards seen on the SAME device as this flagged transaction: {len(ring_cards)} card(s), "
        f"of which {len(known_fraud_cards)} have confirmed-fraud history: {known_fraud_cards}."
        if ring_cards else "No other cards found on the same device as this flagged transaction "
        "(either no shared device use, or this was an in-person transaction with no device record)."
    )
    if similar_cases:
        narrative_parts.append(
            f"Similar prior cases retrieved from case memory: {list(zip(similar_ids, similar_outcomes))}."
        )
    if policy_texts:
        narrative_parts.append("Relevant policy/pattern text:\n" + "\n".join(f"- {t}" for t in policy_texts))

    exposure_usd = round(sum(abs(t.get("attributes", t).get("amount", 0)) for t in txns if isinstance(t, dict) and t.get("attributes", t).get("transaction_id") == flagged_id) or abs(flagged.get("amount", 0)), 2)

    ctx = {
        "exposure_usd": exposure_usd,
        "customer_response": "none",
        "shared_origin": shared_origin or bool(known_fraud_cards),
        "shared_origin_desc": (
            f"device shared with {len(shared_customers)} other customers" if shared_origin
            else f"{len(known_fraud_cards)} connected cards with confirmed fraud" if known_fraud_cards else ""
        ),
        "already_cleared_large_purchase": abs(flagged.get("amount", 0)) > 100,
        "single_signal": not (shared_origin or known_fraud_cards),
        "recurring_pattern_dispute": False,
        "two_plus_cards_confirmed_fraud": len(known_fraud_cards) >= 2,
        "credentials_confirmed_compromised": False,
        "flagged_txn_id": flagged_id,
        "device_id": device_id,
        "connected_card_ids": ring_cards,
        "connected_device_profiles": [device_id] if device_id and shared_origin else [],
        "similar_case_ids": similar_ids,
        "similar_outcomes": similar_outcomes,
    }
    return "\n".join(narrative_parts), ctx


def _simulate_customer_response(ctx: dict, assessment: RiskAssessment) -> tuple[str, str]:
    """Returns (response, assumed_response_text) grounded in retrieved similar
    cases per this module's docstring."""
    outcomes = ctx.get("similar_outcomes", [])
    confirmed = sum(1 for o in outcomes if o == "confirmed_fraud")
    cleared = sum(1 for o in outcomes if o == "cleared")
    if confirmed > cleared:
        basis = f"{confirmed}/{len(outcomes)} similar prior cases were confirmed fraud"
        response = "denied"
    elif cleared > confirmed:
        basis = f"{cleared}/{len(outcomes)} similar prior cases were cleared"
        response = "confirmed"
    else:
        basis = f"assessed fraud probability {assessment.fraud_probability:.2f} with no clear precedent"
        response = "denied" if assessment.fraud_probability >= 0.5 else "confirmed"
    verb = "did not make" if response == "denied" else "made"
    text = f"Customer states they {verb} this transaction (simulated; basis: {basis})."
    return response, text


def _actions_to_json(actions: list[ActionItem]) -> list[dict]:
    return [{"action": a.action, "route": a.route, "reason": a.reason} for a in actions]


async def run_one_case(case: dict, tb: McpToolbox) -> dict:
    t0 = time.time()
    tool_calls = 0

    narrative, ctx = await gather_evidence(case, tb)
    tool_calls += 6  # customer_profile, card_transaction_window, device_shared_accounts, fraud_ring_component, similar_closed_cases, policy_search

    assessment = llm.assess_risk_from_evidence(narrative)
    initial_actions = decision_matrix(assessment, ctx)

    evidence_requests: list[dict] = []
    round_num = 0
    while round_num < MAX_ROUNDS:
        settled = ctx["customer_response"] != "none"
        extreme = assessment.fraud_probability >= 0.85 or assessment.fraud_probability <= 0.15
        if settled or extreme:
            break
        round_num += 1
        response, assumed_text = _simulate_customer_response(ctx, assessment)
        evidence_requests.append({
            "type": "customer_validation", "asked_after_step": round_num, "assumed_response": assumed_text,
        })
        ctx["customer_response"] = response
        narrative += f"\n\nEVIDENCE REQUEST (round {round_num}): asked the customer to validate the flagged transaction. {assumed_text}"
        assessment = llm.assess_risk_from_evidence(narrative)
        tool_calls += 1

    final_actions = decision_matrix(assessment, ctx)
    what_changed = (
        "nothing" if [a.action for a in initial_actions] == [a.action for a in final_actions]
        else f"Simulated evidence response ({ctx['customer_response']}) changed the recommendation."
    )

    file_report = any(a.action == "FILE_REPORT" for a in final_actions)
    sar = {"file": False, "reason": "", "narrative": "", "subjects": [], "total_amount_usd": 0.0, "activity_dates": []}
    if file_report:
        sar_prompt = (
            f"Write a suspicious activity report narrative (6-12 sentences: who, what, when, where, how, "
            f"why suspicious) for this case.\n{narrative}"
        )
        sar_text = llm.generate_explanation(sar_prompt)
        flagged = _TXN_INDEX.get(ctx["flagged_txn_id"], {})
        sar = {
            "file": True,
            "reason": next((a.reason for a in final_actions if a.action == "FILE_REPORT"), ""),
            "narrative": sar_text,
            "subjects": [case["customer_id"], case["card_id"]] + ctx.get("connected_card_ids", [])[:3],
            "total_amount_usd": ctx["exposure_usd"],
            "activity_dates": [str(flagged.get("ts", ""))[:10]] * 2 if flagged.get("ts") else [],
        }
        tool_calls += 1

    explanation_prompt = (
        f"Summarize this fraud investigation in 2-6 sentences for an analyst.\n{narrative}\n"
        f"Verdict: {assessment.verdict}, probability {assessment.fraud_probability:.2f}, pattern {assessment.pattern}.\n"
        f"Final actions: {[a.action for a in final_actions]}."
    )
    summary = llm.generate_explanation(explanation_prompt)
    tool_calls += 1

    status = (
        "closed_fraud" if assessment.verdict == "fraud"
        else "closed_legitimate" if assessment.verdict == "legitimate"
        else "escalated"
    )
    affected_txn_ids = [ctx["flagged_txn_id"]] if assessment.verdict != "legitimate" else []
    exposure_usd = ctx["exposure_usd"] if assessment.verdict != "legitimate" else 0.0

    graph_case_id = case["case_id"]
    conn = get_connection()
    conn.upsertVertex("InvestigationCase", graph_case_id, attributes={
        "status": status, "verdict": assessment.verdict, "fraud_probability": assessment.fraud_probability,
        "pattern": assessment.pattern, "pattern_description": assessment.pattern_description,
        "affected_txn_ids": affected_txn_ids, "first_suspicious_txn_id": ctx["flagged_txn_id"] if affected_txn_ids else "",
        "connected_card_ids": ctx.get("connected_card_ids", []), "connected_device_profiles": ctx.get("connected_device_profiles", []),
        "exposure_usd": exposure_usd, "evidence_json": narrative[:8000],
        "similar_prior_cases": ctx.get("similar_case_ids", []), "summary": summary,
        "evidence_requests_json": json.dumps(evidence_requests), "initial_actions_json": json.dumps(_actions_to_json(initial_actions)),
        "final_actions_json": json.dumps(_actions_to_json(final_actions)), "what_changed": what_changed,
        "stop_reason": "extreme probability or verification settled" if round_num > 0 or (assessment.fraud_probability >= 0.85 or assessment.fraud_probability <= 0.15) else "round cap reached",
        "sar_file": sar["file"], "sar_reason": sar["reason"], "sar_narrative": sar["narrative"],
        "sar_subjects": sar["subjects"], "sar_total_amount_usd": sar["total_amount_usd"],
        "trigger_type": case["trigger_type"], "trigger_text": case["trigger_text"],
    })
    conn.upsertEdge("InvestigationCase", graph_case_id, "INVOLVES_CUSTOMER", "Customer", case["customer_id"])
    conn.upsertEdge("InvestigationCase", graph_case_id, "ON_CARD", "Card", case["card_id"])
    tool_calls += 2

    latency_s = round(time.time() - t0, 2)

    answer = {
        "case_id": case["case_id"],
        "case": {
            "status": status,
            "verdict": assessment.verdict,
            "fraud_probability": assessment.fraud_probability,
            "pattern": assessment.pattern,
            "pattern_description": assessment.pattern_description,
            "affected_txn_ids": affected_txn_ids,
            "first_suspicious_txn_id": ctx["flagged_txn_id"] if affected_txn_ids else "",
            "connected_card_ids": ctx.get("connected_card_ids", []),
            "connected_device_profiles": ctx.get("connected_device_profiles", []),
            "exposure_usd": exposure_usd,
            "evidence": [
                {"claim": "See full evidence narrative recorded on the graph case vertex", "source": "graph",
                 "ref": f"query:card_transaction_window({case['card_id']})", "entity_ids": [ctx["flagged_txn_id"]]},
            ],
            "similar_prior_cases": ctx.get("similar_case_ids", []),
            "summary": summary,
            "written_to_graph": True,
            "graph_case_id": graph_case_id,
        },
        "evidence_requests": evidence_requests,
        "next_best_actions": {
            "initial": _actions_to_json(initial_actions),
            "final": _actions_to_json(final_actions),
            "what_changed": what_changed,
        },
        "sar": sar,
        "stop_reason": "Fraud probability reached the stopping threshold or a simulated verification response settled the question." if round_num > 0 else "Fraud probability was extreme enough on initial evidence to act without further verification.",
        "tool_calls": tool_calls,
        "tokens": 0,  # not tracked by google.generativeai's response objects in this SDK version
        "latency_s": latency_s,
    }
    return answer


async def run_all() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    case_pack = pd.read_csv(ROOT / "data" / "raw" / "case_pack.csv")

    async with McpToolbox() as tb:
        for _, case in case_pack.iterrows():
            case_dict = case.to_dict()
            print(f"=== {case_dict['case_id']} ===", flush=True)
            try:
                answer = await run_one_case(case_dict, tb)
                out_path = OUT_DIR / f"{case_dict['case_id']}.json"
                out_path.write_text(json.dumps(answer, indent=2), encoding="utf-8")
                print(f"  verdict={answer['case']['verdict']} p={answer['case']['fraud_probability']:.2f} "
                      f"pattern={answer['case']['pattern']} actions={[a['action'] for a in answer['next_best_actions']['final']]}",
                      flush=True)
            except Exception as e:  # noqa: BLE001 — keep going on a per-case failure
                print(f"  FAILED: {type(e).__name__}: {e}", flush=True)


if __name__ == "__main__":
    asyncio.run(run_all())
