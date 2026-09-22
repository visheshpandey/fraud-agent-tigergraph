"""Agent tool surface — evidence-gathering tools + controlled-action tools.

Tool names match PLAN.md's agent tools table. Every function here is a MOCK backed by
hardcoded, internally-consistent fraud scenarios keyed by `entity_id`. The call sites in
`nodes.py` only ever import functions from this module by name — swapping the mock
backend for real TigerGraph MCP tool calls later means rewriting the function bodies
here (fetch via `run_installed_query` / `search_top_k_similarity` etc.), not touching
any node code.

Per PLAN.md, the real version will hold ONE MCP session for the whole run
(`async with client.session(...) as session: tools = await load_mcp_tools(session)`).
No MCP server exists yet, so that is not implemented — this module is the seam where
it will plug in.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Mock scenario data. Three internally-consistent cases:
#   "card-clean-001"   -> normal spending pattern, no fraud signal
#   "card-ring-777"    -> high-confidence account-takeover / fraud-ring case
#   "card-ambig-042"   -> ambiguous single spike, needs a second evidence round
# ---------------------------------------------------------------------------

_SCENARIOS: dict[str, dict[str, Any]] = {
    "card-clean-001": {
        "card_transaction_window": {
            "card": "card-clean-001",
            "days": 7,
            "transactions": [
                {"id": "t1", "amount": 42.10, "product": "grocery", "hours_ago": 3},
                {"id": "t2", "amount": 18.50, "product": "coffee", "hours_ago": 27},
                {"id": "t3", "amount": 120.00, "product": "utility_bill", "hours_ago": 96},
            ],
            "velocity_flag": False,
        },
        "customer_profile": {
            "customer": "cust-clean-001",
            "account_age_days": 940,
            "avg_monthly_spend": 650.0,
            "prior_disputes": 0,
        },
        "device_shared_accounts": {
            "device": "dev-clean-1",
            "linked_customers": ["cust-clean-001"],
            "shared_account_count": 1,
        },
        "fraud_ring_component": {
            "seed": "card-clean-001",
            "hops": 2,
            "component_size": 1,
            "known_fraud_members": 0,
        },
        "similar_closed_cases": {
            "k": 3,
            "cases": [
                {"case_id": "case-0091", "similarity": 0.31, "outcome": "cleared"},
            ],
        },
        "policy_search": {
            "query": "routine low-risk transaction review",
            "chunks": [
                {"doc": "policy_low_risk.md", "text": "Transactions matching the customer's established pattern require no escalation."},
            ],
        },
    },
    "card-ring-777": {
        "card_transaction_window": {
            "card": "card-ring-777",
            "days": 7,
            "transactions": [
                {"id": "t1", "amount": 899.00, "product": "electronics", "hours_ago": 1},
                {"id": "t2", "amount": 950.00, "product": "electronics", "hours_ago": 2},
                {"id": "t3", "amount": 1020.00, "product": "gift_card", "hours_ago": 3},
                {"id": "t4", "amount": 875.00, "product": "gift_card", "hours_ago": 4},
            ],
            "velocity_flag": True,
        },
        "customer_profile": {
            "customer": "cust-ring-777",
            "account_age_days": 12,
            "avg_monthly_spend": 80.0,
            "prior_disputes": 0,
        },
        "device_shared_accounts": {
            "device": "dev-ring-9",
            "linked_customers": ["cust-ring-777", "cust-ring-778", "cust-ring-779", "cust-ring-780"],
            "shared_account_count": 4,
        },
        "fraud_ring_component": {
            "seed": "card-ring-777",
            "hops": 2,
            "component_size": 6,
            "known_fraud_members": 3,
        },
        "similar_closed_cases": {
            "k": 3,
            "cases": [
                {"case_id": "case-0033", "similarity": 0.92, "outcome": "confirmed_fraud"},
                {"case_id": "case-0057", "similarity": 0.88, "outcome": "confirmed_fraud"},
            ],
        },
        "policy_search": {
            "query": "new account high velocity gift card purchases shared device",
            "chunks": [
                {"doc": "policy_ato.md", "text": "New accounts (<30 days) with device fan-out across 3+ customers and gift-card velocity spikes meet the account-takeover pattern; freeze pending verification."},
            ],
        },
    },
    "card-ambig-042": {
        "card_transaction_window": {
            "card": "card-ambig-042",
            "days": 7,
            "transactions": [
                {"id": "t1", "amount": 45.00, "product": "grocery", "hours_ago": 20},
                {"id": "t2", "amount": 60.00, "product": "restaurant", "hours_ago": 50},
                {"id": "t3", "amount": 640.00, "product": "electronics", "hours_ago": 2},
            ],
            "velocity_flag": False,
        },
        "customer_profile": {
            "customer": "cust-ambig-042",
            "account_age_days": 410,
            "avg_monthly_spend": 300.0,
            "prior_disputes": 0,
        },
        "device_shared_accounts": {
            "device": "dev-ambig-2",
            "linked_customers": ["cust-ambig-042"],
            "shared_account_count": 1,
        },
        "fraud_ring_component": {
            "seed": "card-ambig-042",
            "hops": 2,
            "component_size": 1,
            "known_fraud_members": 0,
        },
        "similar_closed_cases": {
            "k": 3,
            "cases": [
                {"case_id": "case-0104", "similarity": 0.58, "outcome": "confirmed_fraud"},
                {"case_id": "case-0071", "similarity": 0.55, "outcome": "cleared"},
            ],
        },
        "policy_search": {
            "query": "single amount anomaly no device or velocity signal",
            "chunks": [
                {"doc": "policy_ambiguous.md", "text": "A single amount anomaly with no corroborating velocity, device, or ring signal is inconclusive; verify with the account owner before deciding."},
            ],
        },
        # Extra evidence surfaced only on the SECOND gather_evidence round, after
        # request_evidence runs validate_transaction_with_owner.
        "round_2": {
            "card_transaction_window": {
                "card": "card-ambig-042",
                "days": 30,
                "transactions": [
                    {"id": "t0", "amount": 610.00, "product": "electronics", "hours_ago": 4300},
                ],
                "velocity_flag": False,
                "note": "customer made a similarly sized electronics purchase 6 months ago",
            },
        },
    },
}

_DEFAULT_SCENARIO = "card-clean-001"


def _scenario(entity_id: str) -> dict[str, Any]:
    return _SCENARIOS.get(entity_id, _SCENARIOS[_DEFAULT_SCENARIO])


def card_transaction_window(card: str, days: int = 7, round: int = 0) -> dict[str, Any]:
    """Recent activity on a card over the trailing `days` days.

    `round` selects between first-pass and follow-up (post request_evidence) data for
    scenarios where a second look surfaces more context (e.g. card-ambig-042).
    """
    scenario = _scenario(card)
    if round >= 2 and "round_2" in scenario:
        return scenario["round_2"]["card_transaction_window"]
    return scenario["card_transaction_window"]


def customer_profile(customer: str) -> dict[str, Any]:
    """Accounts, cards, and baseline behavior for a customer."""
    return _scenario(customer)["customer_profile"]


def device_shared_accounts(device: str) -> dict[str, Any]:
    """One device linked to many customers — ATO / fraud-ring signal."""
    return _scenario(device)["device_shared_accounts"]


def fraud_ring_component(seed: str, hops: int = 2) -> dict[str, Any]:
    """Connected component (WCC/k-core style) around a seed card/customer/device."""
    return _scenario(seed)["fraud_ring_component"]


def similar_closed_cases(vec: str, k: int = 3) -> dict[str, Any]:
    """vectorSearch over Case.emb — case memory. `vec` stands in for an embedding key."""
    return _scenario(vec)["similar_closed_cases"]


def policy_search(vec: str, k: int = 3) -> dict[str, Any]:
    """vectorSearch over DocChunk.emb — GraphRAG grounding. `vec` stands in for a query key."""
    return _scenario(vec)["policy_search"]


# ---------------------------------------------------------------------------
# Controlled-action mock API — called from `request_evidence`, deterministic canned
# responses (no real customer contact / auth system exists yet).
# ---------------------------------------------------------------------------


def validate_transaction_with_owner(entity_id: str, transaction_id: str) -> dict[str, Any]:
    """Simulate contacting the account owner to confirm/deny a transaction."""
    if entity_id == "card-ring-777":
        return {"action": "validate_transaction_with_owner", "response": "owner_unreachable", "confirmed": False}
    if entity_id == "card-ambig-042":
        return {"action": "validate_transaction_with_owner", "response": "owner_confirms_purchase", "confirmed": True}
    return {"action": "validate_transaction_with_owner", "response": "owner_confirms_purchase", "confirmed": True}


def step_up_auth(entity_id: str) -> dict[str, Any]:
    """Simulate a step-up authentication challenge (e.g. OTP/biometric)."""
    if entity_id == "card-ring-777":
        return {"action": "step_up_auth", "response": "challenge_failed", "passed": False}
    return {"action": "step_up_auth", "response": "challenge_passed", "passed": True}


def ask_analyst(entity_id: str, question: str) -> dict[str, Any]:
    """Simulate routing a question to a human analyst for a quick read."""
    return {"action": "ask_analyst", "question": question, "response": "analyst_flags_for_manual_review"}
