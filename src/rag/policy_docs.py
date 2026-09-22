"""Curated DocChunk content for GraphRAG, sourced from data/raw/README.md.

Hand-curated rather than auto-parsed from the README's markdown: the policy
section is short and stable enough that a bespoke parser would cost more time
than it saves, and hand-curation guarantees each chunk is a clean, complete
unit (one rule, one action table, one pattern) rather than an arbitrary
paragraph-boundary split.

SCOPE LIMITATION (documented, not silently dropped): the README also lists
external regulatory references (FinCEN/FATF/FFIEC/OFAC PDFs) as "documents you
may find useful" to load into vector search. Those are not downloaded — they
are optional per the brief ("Public documents... Load the ones you find
useful"), and fetching + chunking 15 external PDFs was not the highest-value
use of remaining time versus getting the core policy/pattern/case-memory
retrieval working end-to-end. If time remains, add them here following the
same (chunk_id, doc_name, doc_type, section, text) shape.
"""

from __future__ import annotations

from typing import TypedDict


class DocChunkRecord(TypedDict):
    chunk_id: str
    doc_name: str
    doc_type: str  # policy | pattern
    section: str
    text: str
    ordinal: int


_PATTERNS: list[tuple[str, str]] = [
    ("card_testing", (
        "Card testing. A stolen card number is checked before use: three or more tiny "
        "online authorizations, often under $5, then a larger purchase. Confirmed by the "
        "sequence itself. Policy R5."
    )),
    ("card_not_present_fraud", (
        "Card-not-present fraud. The number is used online without the card. Amounts and "
        "products that don't fit the cardholder's history, often in a burst of two to four "
        "within 48 hours. On its own, one unusual online purchase is ambiguous: verify. "
        "Policy R1 to R4."
    )),
    ("card_not_present_new_device", (
        "Card-not-present fraud from a new device. Same as card-not-present fraud, with the "
        "identity record marking the device as New for this account, sometimes behind a "
        "proxy. Stronger than plain card-not-present fraud, still not proof: people buy new "
        "phones."
    )),
    ("out_of_region_use", (
        "Out-of-region use. Card-present purchases in a billing region the cardholder has no "
        "history in, while their normal activity continues at home. Several days of "
        "purchases in one new region is a trip, not a clone. Policy R2, R3."
    )),
    ("account_takeover", (
        "Account takeover. Mixed-channel activity inconsistent with the cardholder, often "
        "with device and match-flag anomalies, pointing to stolen credentials rather than a "
        "stolen number."
    )),
]

_POLICY_SECTIONS: list[tuple[str, str]] = [
    ("0_starting_point", (
        "What the agent starts with. Every transaction carries a risk_score between 0 and 1 "
        "from the bank's detection model. The model is useful and imperfect: many high "
        "scores are legitimate, and some fraud scores low. A score is a reason to look, "
        "never a verdict. The only confirmed outcomes are in the closed cases."
    )),
    ("1_actions", (
        "Actions. ALLOW_TRANSACTION: let the flagged transaction stand, no customer impact. "
        "DECLINE_TRANSACTION: decline the flagged authorization only, card stays active, low "
        "impact. MONITOR_CARD: card stays active, raise monitoring sensitivity for 72 hours, "
        "no impact. MONITOR_CONNECTED_CARDS: put other cards linked to the same device "
        "profile, region cluster, or ring under monitoring, no impact. WARN_CUSTOMER: send an "
        "informational message, no impact. VERIFY_WITH_CUSTOMER: ask the cardholder whether "
        "they made the transaction, card stays active pending reply, low impact. "
        "STEP_UP_AUTH: require a one-time passcode or app confirmation before further "
        "activity, low impact. BLOCK_CARD: block this card and reissue, high impact. "
        "BLOCK_ALL_CARDS: block every card the customer holds, very high impact. "
        "GENERATE_REPORT: write up the investigation for the internal record without opening "
        "a case, no impact. CREATE_CASE: open an internal fraud case with the evidence "
        "attached and write it to the graph, no impact. FILE_REPORT: file a suspicious "
        "activity report with the regulator, no impact. ESCALATE_TO_ANALYST: hand the case "
        "to a human analyst with the evidence, no impact. CLOSE_NO_FRAUD: close the alert as "
        "legitimate, no impact. An agent may recommend several actions for one case. Order "
        "them by what happens first."
    )),
    ("2_approval_routing", (
        "Approval routing. auto: ALLOW_TRANSACTION, MONITOR_CARD, MONITOR_CONNECTED_CARDS, "
        "WARN_CUSTOMER, VERIFY_WITH_CUSTOMER, STEP_UP_AUTH, GENERATE_REPORT, CREATE_CASE, "
        "ESCALATE_TO_ANALYST, CLOSE_NO_FRAUD may be executed by the agent. L1 (team lead) "
        "approval is required for DECLINE_TRANSACTION, and for BLOCK_CARD when exposure is "
        "$2,500 or less. L2 (fraud manager) approval is required for BLOCK_CARD when exposure "
        "exceeds $2,500, for BLOCK_ALL_CARDS always, and for FILE_REPORT always. Only auto "
        "actions may be executed by the agent; L1 and L2 actions are recommended with the "
        "route stated and wait for a human."
    )),
    ("R1", (
        "R1. Verify before you block on a weak signal. If the case rests on a single signal "
        "(including a risk score alone) and the assessed fraud probability is below 0.70, "
        "recommend VERIFY_WITH_CUSTOMER or STEP_UP_AUTH before any block. Blocking a "
        "legitimate customer on one signal is a policy breach."
    )),
    ("R2", (
        "R2. Customer denies the transaction. Recommend BLOCK_CARD and CREATE_CASE. Add "
        "FILE_REPORT if exposure exceeds $1,000 or the case connects to a shared device "
        "profile or another card's fraud."
    )),
    ("R3", (
        "R3. Customer confirms the transaction. Recommend CLOSE_NO_FRAUD. Note the "
        "confirmation in the case file."
    )),
    ("R4", (
        "R4. No reply within 24 hours. Recommend MONITOR_CARD and DECLINE_TRANSACTION for "
        "pending authorizations. Escalate if exposure exceeds $500."
    )),
    ("R5", (
        "R5. Card testing. Three or more small online authorizations on one card within an "
        "hour, followed by a larger purchase: recommend DECLINE_TRANSACTION and STEP_UP_AUTH. "
        "If a purchase over $100 has already cleared, recommend BLOCK_CARD."
    )),
    ("R6", (
        "R6. Shared origin. When several cards show fraud from the same device profile, the "
        "same billing region, or the same recipient email in one window, name the shared "
        "element, recommend CREATE_CASE and FILE_REPORT, and MONITOR_CONNECTED_CARDS for "
        "every card that shares it."
    )),
    ("R7", (
        "R7. Disputed but legitimate. When the customer disputes a charge that matches their "
        "own recurring pattern (same merchant, same amount, monthly), recommend CREATE_CASE, "
        "VERIFY_WITH_CUSTOMER, and WARN_CUSTOMER. Do not block."
    )),
    ("R8", (
        "R8. Escalate when uncertain and exposed. If the verdict is uncertain and exposure "
        "exceeds $500, or the evidence conflicts, recommend ESCALATE_TO_ANALYST."
    )),
    ("R9", (
        "R9. Undocumented patterns. When activity fits none of the known patterns but the "
        "evidence shows coordinated or repeated abuse across customers, recommend "
        "CREATE_CASE, FILE_REPORT, and ESCALATE_TO_ANALYST, and describe the pattern in your "
        "own words. Do not force it into a known category."
    )),
    ("R10", (
        "R10. Never BLOCK_ALL_CARDS unless at least two of the customer's cards show "
        "confirmed fraud or the customer's credentials are confirmed compromised."
    )),
    ("3a_case_vs_report", (
        "A case is not a report. A case (CREATE_CASE) is the bank's internal record of an "
        "investigation. Open one whenever fraud probability reaches 0.30, whenever you "
        "request evidence, or whenever a customer disputes a charge. A case can be closed as "
        "fraud or as legitimate, and can be updated as new evidence arrives; it should be "
        "written into the graph so later investigations can find it. A suspicious activity "
        "report (FILE_REPORT) is a regulatory filing sent outside the bank. File one when "
        "fraud is confirmed or strongly suspected and at least one of: exposure exceeds "
        "$1,000; the activity connects to a shared device profile, a shared region cluster, "
        "or another customer's fraud; the pattern is coordinated or undocumented (R9). A "
        "report always has a case behind it. Most cases never need a report."
    )),
    ("3b_nba_can_change", (
        "The next best action can change. Recommend what the evidence supports now, then "
        "request more evidence if the policy calls for it, then recommend again. Example: "
        "probability 0.45 on a single signal, so the initial action is VERIFY_WITH_CUSTOMER "
        "under R1. The customer denies the transaction. Probability rises, and the final "
        "actions become BLOCK_CARD, CREATE_CASE, and possibly FILE_REPORT under R2, with "
        "connected cards placed under monitoring. Record both the initial and the final "
        "recommendation and what changed between them."
    )),
    ("4_exposure", (
        "Exposure is the sum of the absolute amounts of every transaction the agent has "
        "identified as part of the fraud episode, including the flagged one. Report it in "
        "USD."
    )),
    ("5_gathering_evidence", (
        "Gathering more evidence. The agent may, without approval, ask the customer to "
        "validate a transaction, request step-up authentication, or request information from "
        "an analyst. Those responses are not provided in this exercise; simulate them and "
        "state the assumption made in the case file's evidence_requests."
    )),
    ("6_stopping", (
        "Stopping. Stop investigating when fraud probability is at or above 0.85, or at or "
        "below 0.15, supported by at least two independent pieces of evidence; or a "
        "verification response settles the question; or further steps are unlikely to change "
        "the decision (say so in stop_reason). Investigations that continue past a defensible "
        "decision waste time. Investigations that stop before one create risk. Both are "
        "marked down."
    )),
    ("7_explaining", (
        "Explaining. Every recommendation must state what evidence was used, why more "
        "evidence was requested if it was, and why the chosen actions follow from this "
        "policy. Cite the rule number."
    )),
]


def build_doc_chunks() -> list[DocChunkRecord]:
    chunks: list[DocChunkRecord] = []
    ordinal = 0
    for name, text in _PATTERNS:
        chunks.append({
            "chunk_id": f"pattern-{name}",
            "doc_name": "known_fraud_patterns",
            "doc_type": "pattern",
            "section": name,
            "text": text,
            "ordinal": ordinal,
        })
        ordinal += 1
    for section, text in _POLICY_SECTIONS:
        chunks.append({
            "chunk_id": f"policy-{section}",
            "doc_name": "fraud_policy_v1",
            "doc_type": "policy",
            "section": section,
            "text": text,
            "ordinal": ordinal,
        })
        ordinal += 1
    return chunks
