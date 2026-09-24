"""Demonstrates the real, graded decision_matrix() revising its recommendation
as evidence changes -- deterministically, for the demo video.

Why this exists: none of the 20 official benchmark cases needed a second
evidence round (each had clear enough signal to resolve confidently in round
1 -- a good outcome, not a gap). And src/agent/graph.py's live-Gemini mock
demo is not reproducible run-to-run for recording purposes, since the real
LLM's exact probability/gap output varies slightly each call. This script
sidesteps both problems by calling the SAME decision_matrix() function the
real benchmark pipeline uses, directly, with two realistic RiskAssessment
states representing "before the customer replies" and "after the customer
denies the transaction" -- exactly the R1 -> R2 transition Fraud Policy §3b
describes as its own example. Nothing here is fabricated: decision_matrix()
is the actual code path graded for next-best-action quality, unmodified.

Run with: python -m src.agent.demo_decision_change
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore")  # quiet google.generativeai's deprecation notice for the recording

from src.agent.nodes import decision_matrix  # noqa: E402
from src.agent.state import RiskAssessment  # noqa: E402


def main() -> None:
    print("=" * 72)
    print("SCENARIO: a $292 online purchase flagged by the risk model (score 0.79).")
    print("No prior fraud signal on this device or card -- a single weak signal.")
    print("=" * 72)

    # Round 1: only the risk score is in hand. Single signal, below the 0.70
    # verification threshold policy rule R1 sets.
    before = RiskAssessment(
        verdict="uncertain",
        fraud_probability=0.55,
        pattern="none",
        pattern_description="",
        evidence_gaps=["confirmation from the cardholder that they made this purchase"],
        rationale="Risk score alone; no corroborating device, ring, or history signal.",
    )
    ctx_before = {
        "exposure_usd": 292.36, "customer_response": "none", "shared_origin": False,
        "shared_origin_desc": "", "already_cleared_large_purchase": False,
        "single_signal": True, "recurring_pattern_dispute": False,
        "two_plus_cards_confirmed_fraud": False, "credentials_confirmed_compromised": False,
    }
    initial_actions = decision_matrix(before, ctx_before)

    print("\n--- BEFORE requesting more evidence ---")
    print(f"Assessment: verdict={before.verdict}, fraud_probability={before.fraud_probability}")
    print(f"Evidence gap noted: {before.evidence_gaps[0]}")
    print("Recommended actions:")
    for a in initial_actions:
        print(f"  {a.action:20s} route={a.route:5s} reason={a.reason}")

    print("\n>>> Agent requests VERIFY_WITH_CUSTOMER (policy-approved, auto-executable).")
    print(">>> Simulated response: customer states they did NOT make this purchase.\n")

    # Round 2: the customer's denial is now in hand -- this IS the R2
    # precondition (Fraud Policy §3b's own worked example).
    after = RiskAssessment(
        verdict="fraud",
        fraud_probability=0.90,
        pattern="card_not_present_fraud",
        pattern_description="",
        evidence_gaps=[],
        rationale="Cardholder denies the transaction -- policy R2 applies directly.",
    )
    ctx_after = dict(ctx_before, customer_response="denied")
    final_actions = decision_matrix(after, ctx_after)

    print("--- AFTER the customer's response ---")
    print(f"Assessment: verdict={after.verdict}, fraud_probability={after.fraud_probability}")
    print("Recommended actions:")
    for a in final_actions:
        print(f"  {a.action:20s} route={a.route:5s} reason={a.reason}")

    changed = [a.action for a in initial_actions] != [a.action for a in final_actions]
    print(f"\nRecommendation changed: {changed}")
    print(f"  Before: {[a.action for a in initial_actions]}")
    print(f"  After:  {[a.action for a in final_actions]}")


if __name__ == "__main__":
    main()
