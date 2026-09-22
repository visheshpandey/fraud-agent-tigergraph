"""LLM interface — thin wrapper around 'assess risk' and 'generate explanation'.

Both functions currently return DETERMINISTIC STUBBED output computed from simple
heuristics over the collected evidence, not a real model call — no API key is assumed
available yet. They return the same pydantic model (`RiskAssessment`) a real Gemini
call would need to produce, so swapping the body of `assess_risk_from_evidence` for a
`google-genai` structured-output call (`response_schema=RiskAssessment`) is a body-only
change — every call site keeps working unmodified.
"""

from __future__ import annotations

from .state import CaseState, RiskAssessment, ToolEvidence


def _evidence_by_source(evidence: list[ToolEvidence], source: str) -> dict | None:
    matches = [e for e in evidence if e["source"] == source]
    if not matches:
        return None
    return matches[-1]["data"]  # most recent round wins


def assess_risk_from_evidence(evidence: list[ToolEvidence]) -> RiskAssessment:
    """STUB for a Gemini structured-output call. Heuristic over mock tool evidence."""

    txn = _evidence_by_source(evidence, "card_transaction_window") or {}
    profile = _evidence_by_source(evidence, "customer_profile") or {}
    device = _evidence_by_source(evidence, "device_shared_accounts") or {}
    ring = _evidence_by_source(evidence, "fraud_ring_component") or {}
    validation = _evidence_by_source(evidence, "validate_transaction_with_owner")
    step_up = _evidence_by_source(evidence, "step_up_auth")

    velocity_flag = bool(txn.get("velocity_flag"))
    shared_accounts = int(device.get("shared_account_count", 1))
    known_fraud_members = int(ring.get("known_fraud_members", 0))
    account_age_days = int(profile.get("account_age_days", 9999))

    transactions = txn.get("transactions", [])
    avg_spend = float(profile.get("avg_monthly_spend", 0) or 0)
    max_amount = max((t.get("amount", 0) for t in transactions), default=0.0)
    amount_anomaly = avg_spend > 0 and max_amount > 2 * avg_spend

    if velocity_flag and shared_accounts >= 3 and known_fraud_members > 0:
        return RiskAssessment(
            verdict="fraud",
            fraud_probability=0.93,
            pattern="account_takeover",
            evidence_gaps=[],
            rationale=(
                f"Velocity spike on a {account_age_days}-day-old account, device shared "
                f"across {shared_accounts} customers, {known_fraud_members} known-fraud "
                "ring members in the connected component."
            ),
        )

    if amount_anomaly and not velocity_flag and shared_accounts == 1:
        if validation is not None and validation.get("confirmed"):
            return RiskAssessment(
                verdict="legitimate",
                fraud_probability=0.12,
                pattern="none",
                evidence_gaps=[],
                rationale=(
                    "Single amount anomaly, but the account owner confirmed the "
                    "transaction and a similarly sized prior purchase exists on record."
                ),
            )
        if validation is not None and not validation.get("confirmed"):
            return RiskAssessment(
                verdict="fraud",
                fraud_probability=0.80,
                pattern="card_not_present_fraud",
                evidence_gaps=[],
                rationale="Owner could not confirm the anomalous transaction.",
            )
        return RiskAssessment(
            verdict="uncertain",
            fraud_probability=0.45,
            pattern="none",
            evidence_gaps=["owner confirmation of the anomalous transaction"],
            rationale=(
                f"Single transaction (${max_amount:.2f}) exceeds 2x baseline spend "
                f"(${avg_spend:.2f}/mo) with no corroborating velocity, device, or ring "
                "signal — inconclusive on its own (policy R1)."
            ),
        )

    if step_up is not None and not step_up.get("passed"):
        return RiskAssessment(
            verdict="fraud",
            fraud_probability=0.85,
            pattern="account_takeover",
            evidence_gaps=[],
            rationale="Step-up authentication challenge failed.",
        )

    return RiskAssessment(
        verdict="legitimate",
        fraud_probability=0.10,
        pattern="none",
        evidence_gaps=[],
        rationale="Transaction pattern matches established customer baseline.",
    )


def generate_explanation(state: CaseState) -> str:
    """STUB for a Gemini call that writes the plain-English case explanation.
    Policy §7: must state evidence used, why more was requested if it was, and why
    the chosen actions follow from the policy (cite the rule number — the rule
    citation itself lives in each ActionItem.reason, this just narrates around it).
    """

    assessment = state.get("risk_assessment")
    evidence = state.get("tool_evidence", [])
    rounds = state.get("round_count", 0)
    initial = state.get("initial_actions", [])
    final = state.get("final_actions", [])

    lines = [
        f"Case {state.get('case_id')}: verdict={assessment.verdict if assessment else 'n/a'}, "
        f"fraud_probability={assessment.fraud_probability if assessment else 'n/a'}, "
        f"pattern={assessment.pattern if assessment else 'n/a'}.",
        f"Evidence gathered over {rounds} round(s) from: "
        + ", ".join(sorted({e['source'] for e in evidence})) + ".",
    ]

    requested_more = any(
        e["source"] in ("validate_transaction_with_owner", "step_up_auth", "ask_analyst") for e in evidence
    )
    if requested_more:
        lines.append(
            "Additional evidence was requested because the first round left gaps "
            "(fraud probability had not yet reached the stopping threshold)."
        )
    elif assessment and assessment.evidence_gaps:
        lines.append(
            "Evidence gaps remain but the round cap was reached before they could be closed: "
            + "; ".join(assessment.evidence_gaps) + "."
        )
    else:
        lines.append("No additional evidence was needed beyond the initial round.")

    initial_names = [a.action for a in initial]
    final_names = [a.action for a in final]
    if initial_names != final_names:
        lines.append(
            f"Recommendation was revised after new evidence: {initial_names} -> {final_names}. "
            f"{state.get('what_changed', '')}"
        )
    else:
        lines.append(f"Recommended action(s): {final_names or initial_names}.")

    return " ".join(lines)
