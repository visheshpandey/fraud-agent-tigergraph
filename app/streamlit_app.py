"""Analyst dashboard for the fraud investigation agent.

Reads the graded answer files from cases/*.json (produced by
src/eval/run_cases.py) — no live agent calls happen here, this is purely a
viewer over already-investigated cases, which keeps it usable even while a
benchmark run is still in progress or the API quota is exhausted.

Run with: streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "cases"  # the graded answer files, per the README
CASE_PACK = ROOT / "data" / "raw" / "case_pack.csv"

st.set_page_config(page_title="Fraud Investigation Agent", layout="wide")


@st.cache_data(ttl=5)
def load_cases() -> dict[str, dict]:
    cases = {}
    if CASES_DIR.exists():
        for f in sorted(CASES_DIR.glob("*.json")):
            cases[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return cases


@st.cache_data
def load_case_pack() -> pd.DataFrame:
    if CASE_PACK.exists():
        return pd.read_csv(CASE_PACK).set_index("case_id")
    return pd.DataFrame()


def action_badge(route: str) -> str:
    color = {"auto": "green", "L1": "orange", "L2": "red"}.get(route, "gray")
    return f":{color}[{route}]"


def render_actions(actions: list[dict], label: str) -> None:
    st.markdown(f"**{label}**")
    if not actions:
        st.caption("(none)")
        return
    for a in actions:
        st.markdown(f"- `{a['action']}` — {action_badge(a['route'])} — {a['reason']}")


def main() -> None:
    st.title("Fraud Investigation Agent")
    st.caption("TigerGraph + LangGraph + Gemini — HHGOA Hackathon")

    cases = load_cases()
    case_pack = load_case_pack()

    if not cases:
        st.warning(
            "No answer files found in `cases/`. Run `python -m src.eval.run_cases` "
            "to investigate the 20 benchmark cases first."
        )
        st.stop()

    with st.sidebar:
        st.header("Cases")
        case_id = st.selectbox("Select a case", sorted(cases.keys()))
        st.metric("Total investigated", len(cases))
        verdicts = pd.Series([c["case"]["verdict"] for c in cases.values()]).value_counts()
        st.bar_chart(verdicts)

    answer = cases[case_id]
    case = answer["case"]
    nba = answer["next_best_actions"]
    sar = answer["sar"]

    trigger_row = case_pack.loc[case_id] if case_id in case_pack.index else None

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Verdict", case["verdict"].upper())
    col2.metric("Fraud probability", f"{case['fraud_probability']:.0%}")
    col3.metric("Pattern", case["pattern"])
    col4.metric("Exposure", f"${case['exposure_usd']:,.2f}")

    # Confidence / uncertainty indicator
    p = case["fraud_probability"]
    if p >= 0.85 or p <= 0.15:
        st.success(f"High confidence ({p:.0%}) — decision is well-supported by evidence.")
    elif 0.3 <= p <= 0.7:
        st.warning(f"Uncertain ({p:.0%}) — verdict is `{case['verdict']}`, evidence is mixed.")
    else:
        st.info(f"Moderate confidence ({p:.0%}).")

    if trigger_row is not None:
        st.subheader("Trigger")
        st.write(f"**{trigger_row['trigger_type']}**: {trigger_row['trigger_text']}")

    st.subheader("Investigation timeline")
    steps = ["Trigger", "Gather evidence", "Assess"]
    if answer["evidence_requests"]:
        steps += ["Request evidence", "Re-assess"]
    steps += ["Decide action", "Explain", "Write to graph"]
    st.write(" → ".join(steps))

    left, right = st.columns(2)

    with left:
        st.subheader("Next best action — before vs. after")
        initial_names = [a["action"] for a in nba["initial"]]
        final_names = [a["action"] for a in nba["final"]]
        if initial_names != final_names:
            st.markdown("🔄 **Recommendation changed**")
        render_actions(nba["initial"], "Initial (before evidence request)")
        render_actions(nba["final"], "Final (after evidence request)")
        st.markdown(f"**What changed:** {nba['what_changed']}")

    with right:
        st.subheader("Evidence")
        for e in case["evidence"]:
            st.markdown(f"- **{e['source']}** — {e['claim']} _(ref: `{e['ref']}`)_")
        if answer["evidence_requests"]:
            st.markdown("**Evidence requested during investigation:**")
            for r in answer["evidence_requests"]:
                st.markdown(f"- `{r['type']}` (after step {r['asked_after_step']}): {r['assumed_response']}")
        if case["similar_prior_cases"]:
            st.markdown(f"**Similar prior cases:** {', '.join(case['similar_prior_cases'])}")

    st.subheader("Summary")
    st.write(case["summary"])

    if sar["file"]:
        st.subheader("Suspicious Activity Report")
        st.markdown(f"**Reason:** {sar['reason']}")
        st.write(sar["narrative"])
        st.caption(f"Subjects: {', '.join(sar['subjects'])} — Total: ${sar['total_amount_usd']:,.2f}")

    with st.expander("Raw answer JSON"):
        st.json(answer)

    st.caption(
        f"Graph case id: `{case['graph_case_id']}` · Written to graph: {case['written_to_graph']} · "
        f"Tool calls: {answer['tool_calls']} · Latency: {answer['latency_s']}s"
    )


if __name__ == "__main__":
    main()
