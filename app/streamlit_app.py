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

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
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


def build_subgraph_figure(center_card: str, case: dict) -> go.Figure | None:
    """Renders the flagged card, the device(s) it shares with other cards (if
    any), and those connected cards -- the same structure `fraud_ring_component`
    and `hub_score` reason over, made visible instead of read as JSON."""
    connected_cards = case.get("connected_card_ids", []) or []
    connected_devices = case.get("connected_device_profiles", []) or []
    if not connected_cards and not connected_devices:
        return None

    g = nx.Graph()
    g.add_node(center_card, role="center")
    if connected_devices:
        for dev in connected_devices:
            g.add_node(dev, role="device")
            g.add_edge(center_card, dev)
            for other in connected_cards:
                g.add_node(other, role="connected")
                g.add_edge(dev, other)
    else:
        for other in connected_cards:
            g.add_node(other, role="connected")
            g.add_edge(center_card, other)

    pos = nx.spring_layout(g, seed=7, k=0.9)

    edge_x, edge_y = [], []
    for u, v in g.edges():
        edge_x += [pos[u][0], pos[v][0], None]
        edge_y += [pos[u][1], pos[v][1], None]
    edge_trace = go.Scatter(x=edge_x, y=edge_y, mode="lines",
                             line=dict(width=1, color="#888"), hoverinfo="none")

    role_style = {
        "center": ("#e74c3c", 22, "circle"),
        "device": ("#f39c12", 16, "diamond"),
        "connected": ("#7f8c8d", 12, "circle"),
    }
    node_traces = []
    for role, (color, size, symbol) in role_style.items():
        nodes = [n for n, d in g.nodes(data=True) if d["role"] == role]
        if not nodes:
            continue
        node_traces.append(go.Scatter(
            x=[pos[n][0] for n in nodes], y=[pos[n][1] for n in nodes],
            mode="markers+text", text=nodes, textposition="bottom center",
            hovertext=nodes, hoverinfo="text",
            marker=dict(color=color, size=size, symbol=symbol, line=dict(width=1, color="white")),
            name={"center": "Flagged card", "device": "Shared device", "connected": "Connected card"}[role],
        ))

    fig = go.Figure(data=[edge_trace, *node_traces])
    fig.update_layout(
        showlegend=True, height=420, margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        plot_bgcolor="white",
    )
    return fig


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

    st.subheader("Fraud-ring subgraph")
    center_card = trigger_row["card_id"] if trigger_row is not None else case_id
    fig = build_subgraph_figure(center_card, case)
    if fig is not None:
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Red = the flagged card. Orange = a shared device (from `fraud_ring_component`). "
            "Gray = other cards seen on that device. Built from the same graph traversal the "
            "agent used as evidence, not a separate mockup."
        )
    else:
        st.caption("No connected cards or shared devices for this case — nothing to draw.")

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
