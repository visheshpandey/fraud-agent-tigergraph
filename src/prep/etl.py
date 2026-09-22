"""Transforms data/raw/*.csv into loadable derived CSVs under data/derived/.

Memory-constrained by design (8GB RAM machine): only reads the columns the
graph schema actually models. V1-V339, C1-C14, D1-D15, M1-M9 are deliberately
excluded — 339+ unnamed engineered columns per row would blow up the vertex
attribute count for no graph-structural benefit (see schema/01_schema.gsql's
header comment). They stay in data/raw/transactions.csv for later ad-hoc
pandas-side signal work if a case needs them.

Card-id derivation: which (card1..card6) tuples constitute the "same physical
card" is NOT reliably deducible from the public columns alone. Empirically:
customer C09933's flagged case-pack transaction shares an IDENTICAL
(card1, card4, card6) with another transaction group the case pack does NOT
label the same way, and card2/card3/card5 nulling doesn't line up with card
identity either — Vesta's original missingness on those fields is independent
of which physical card was used. So: group by (customer_id, card1, card4,
card6) as a best-effort "same physical card" partition, then OVERRIDE any
group containing a transaction named in case_pack.csv or
closed_cases_history.csv with that file's authoritative card_id. Groups with
no authoritative label get our own sequential `-K{n}` suffix, skipping
suffixes already claimed by an override for that customer. This guarantees
every ID we cite for a graded case matches the dataset exactly; unlabeled
cards get a self-consistent (if not independently verifiable) grouping.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
DERIVED = Path(__file__).resolve().parents[2] / "data" / "derived"

TXN_COLS = [
    "TransactionID", "TransactionDT", "TransactionAmt", "ProductCD",
    "card1", "card2", "card3", "card4", "card5", "card6",
    "addr1", "addr2", "dist1", "dist2", "P_emaildomain", "R_emaildomain",
    "customer_id", "ts", "channel", "risk_score",
]

ID_COLS = ["TransactionID", "DeviceType", "DeviceInfo", "id_15", "id_23", "id_30", "id_31", "id_33"]

DTYPES = {
    "TransactionID": "int64", "TransactionDT": "int32", "TransactionAmt": "float32",
    "ProductCD": "category", "card1": "Int32", "card2": "Int32", "card3": "Int32",
    "card4": "category", "card5": "Int32", "card6": "category",
    "addr1": "Int32", "addr2": "Int32", "dist1": "Int32", "dist2": "Int32",
    "P_emaildomain": "category", "R_emaildomain": "category",
    "customer_id": "category", "channel": "category", "risk_score": "float32",
}


def _device_id(row: pd.Series) -> str | None:
    if pd.isna(row.get("DeviceInfo")) and pd.isna(row.get("id_30")) and pd.isna(row.get("id_31")):
        return None
    key = "|".join(str(row.get(c, "")) for c in ("DeviceInfo", "id_30", "id_31", "id_33", "DeviceType"))
    return "D-" + hashlib.sha1(key.encode()).hexdigest()[:12]


def load_transactions() -> pd.DataFrame:
    print("Reading transactions.csv (subset of columns only)...")
    df = pd.read_csv(RAW / "transactions.csv", usecols=TXN_COLS, dtype=DTYPES, parse_dates=["ts"])
    print(f"  {len(df):,} rows")
    return df


def load_identity() -> pd.DataFrame:
    print("Reading identity.csv...")
    df = pd.read_csv(RAW / "identity.csv", usecols=ID_COLS)
    df["device_id"] = df.apply(_device_id, axis=1)
    print(f"  {len(df):,} rows, {df['device_id'].notna().sum():,} with a derivable device profile")
    return df


def load_authoritative_card_ids() -> dict[int, str]:
    """TransactionID -> card_id, from the two files that give ground truth."""
    mapping: dict[int, str] = {}

    case_pack = pd.read_csv(RAW / "case_pack.csv")
    for _, r in case_pack.iterrows():
        mapping[int(r["flagged_txn_id"])] = r["card_id"]

    closed = pd.read_csv(RAW / "closed_cases_history.csv", usecols=["card_id", "txn_ids"])
    for _, r in closed.iterrows():
        if pd.isna(r["txn_ids"]):
            continue
        for txn_id in str(r["txn_ids"]).split("|"):
            txn_id = txn_id.strip()
            if txn_id:
                mapping[int(float(txn_id))] = r["card_id"]

    print(f"Authoritative card_id known for {len(mapping):,} transactions "
          f"(case_pack.csv + closed_cases_history.csv)")
    return mapping


def assign_card_ids(txn: pd.DataFrame, authoritative: dict[int, str]) -> pd.Series:
    """Returns a card_id Series aligned to txn.index. See module docstring for the
    grouping heuristic and the override rule."""
    group_key = list(zip(txn["customer_id"], txn["card1"], txn["card4"], txn["card6"]))
    txn = txn.assign(_group=group_key)

    # For each (customer, group) pick the override label if ANY transaction in
    # that group has an authoritative one; ties (shouldn't happen, but a group
    # spanning two different official labels) resolve to the first seen.
    override_by_group: dict[tuple, str] = {}
    for idx, row in txn.iterrows():
        official = authoritative.get(int(row["TransactionID"]))
        if official is not None:
            override_by_group.setdefault(row["_group"], official)

    # Assign fallback labels for ungrouped-yet groups, per customer, skipping
    # any suffix number an override already claimed for that customer.
    used_suffixes: dict[str, set[int]] = {}
    for group, label in override_by_group.items():
        customer_id = group[0]
        suffix = label.rsplit("-K", 1)[-1]
        if suffix.isdigit():
            used_suffixes.setdefault(customer_id, set()).add(int(suffix))

    fallback_by_group: dict[tuple, str] = {}
    next_suffix: dict[str, int] = {}
    # Stable order: first appearance by ts within each customer, so labeling is
    # at least deterministic across re-runs.
    ordered_groups = (
        txn.sort_values("ts").drop_duplicates("_group")[["_group", "customer_id"]].itertuples(index=False)
    )
    for group, customer_id in ordered_groups:
        if group in override_by_group:
            continue
        used = used_suffixes.setdefault(customer_id, set())
        n = next_suffix.get(customer_id, 1)
        while n in used:
            n += 1
        used.add(n)
        next_suffix[customer_id] = n + 1
        fallback_by_group[group] = f"{customer_id}-K{n}"

    card_id_by_group = {**fallback_by_group, **override_by_group}
    return txn["_group"].map(card_id_by_group)


def build_cards(txn: pd.DataFrame) -> pd.DataFrame:
    agg = (
        txn.groupby("card_id", observed=True)
        .agg(
            customer_id=("customer_id", "first"),
            card1=("card1", "first"),
            card2=("card2", lambda s: s.dropna().iloc[0] if s.notna().any() else pd.NA),
            card3=("card3", lambda s: s.dropna().iloc[0] if s.notna().any() else pd.NA),
            card4=("card4", "first"),
            card5=("card5", lambda s: s.dropna().iloc[0] if s.notna().any() else pd.NA),
            card6=("card6", "first"),
        )
        .reset_index()
    )
    return agg


def build_billing_regions(txn: pd.DataFrame) -> pd.DataFrame:
    sub = txn.dropna(subset=["addr1"])
    agg = sub.groupby("addr1", observed=True)["addr2"].agg(
        lambda s: s.mode().iloc[0] if not s.mode().empty else pd.NA
    ).reset_index()
    agg["region_id"] = agg["addr1"].astype("Int64").astype(str)
    return agg[["region_id", "addr1", "addr2"]]


def build_email_domains(txn: pd.DataFrame) -> pd.DataFrame:
    domains = pd.concat([
        txn["P_emaildomain"].dropna().astype(str),
        txn["R_emaildomain"].dropna().astype(str),
    ]).unique()
    return pd.DataFrame({"domain": domains})


def build_next_edges(txn: pd.DataFrame) -> pd.DataFrame:
    sub = txn[["card_id", "TransactionID", "ts", "TransactionDT"]].sort_values(["card_id", "ts"])
    sub["next_txn"] = sub.groupby("card_id", observed=True)["TransactionID"].shift(-1)
    sub["next_dt"] = sub.groupby("card_id", observed=True)["TransactionDT"].shift(-1)
    sub = sub.dropna(subset=["next_txn"])
    # shift() promotes the whole column to float64 (NaN has no int representation),
    # so every non-null value picks up a ".0" suffix once written to CSV — that
    # silently mismatches the integer-formatted Transaction primary ids and makes
    # GSQL auto-vivify a second, attribute-less vertex per edge. Cast back after
    # dropna, once no NaNs remain to force the float promotion.
    sub["next_txn"] = sub["next_txn"].astype("int64")
    sub["next_dt"] = sub["next_dt"].astype("int64")
    sub["gap_seconds"] = (sub["next_dt"] - sub["TransactionDT"]).astype(int)
    return sub.rename(columns={"TransactionID": "from_txn", "next_txn": "to_txn"})[
        ["from_txn", "to_txn", "gap_seconds"]
    ]


def build_closed_case_edges(closed: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Explodes the pipe-separated txn_ids / connected_card_ids columns into flat
    (case_id, target_id) pairs ourselves, one row per edge. GSQL's SPLIT() fans
    out correctly for a SET-typed vertex ATTRIBUTE load but NOT for an edge's
    TO-vertex list — tried inline (`VALUES($0, SPLIT($8, "|"))`) and it silently
    loaded the whole pipe-joined string as a single malformed vertex id instead
    of one edge per element. Exploding in pandas sidesteps that entirely."""
    txn = closed[["case_id", "txn_ids"]].copy()
    txn["txn_ids"] = txn["txn_ids"].astype(str).str.split("|")
    txn = txn.explode("txn_ids").rename(columns={"txn_ids": "txn_id"})
    txn = txn[txn["txn_id"] != ""]

    cards = closed[["case_id", "connected_card_ids"]].dropna(subset=["connected_card_ids"]).copy()
    cards["connected_card_ids"] = cards["connected_card_ids"].astype(str).str.split("|")
    cards = cards.explode("connected_card_ids").rename(columns={"connected_card_ids": "card_id"})
    cards = cards[cards["card_id"] != ""]

    return txn, cards


def run() -> None:
    DERIVED.mkdir(parents=True, exist_ok=True)

    txn = load_transactions()
    ident = load_identity()
    authoritative = load_authoritative_card_ids()

    print("Assigning card_id...")
    txn["card_id"] = assign_card_ids(txn, authoritative)
    print(f"  {txn['card_id'].nunique():,} distinct cards across {txn['customer_id'].nunique():,} customers")

    print("Joining device profiles (online transactions only)...")
    txn = txn.merge(ident[["TransactionID", "device_id"]], on="TransactionID", how="left")

    print("Building dimension tables...")
    customers = pd.DataFrame({"customer_id": txn["customer_id"].astype(str).unique()})
    cards = build_cards(txn)
    billing_regions = build_billing_regions(txn)
    email_domains = build_email_domains(txn)
    devices = ident.dropna(subset=["device_id"]).drop_duplicates("device_id")[
        ["device_id", "DeviceInfo", "DeviceType", "id_30", "id_31", "id_33", "id_23", "id_15"]
    ].rename(columns={
        "DeviceInfo": "device_info", "DeviceType": "device_type",
        "id_30": "os", "id_31": "browser", "id_33": "screen_res", "id_23": "proxy_flag",
    })
    devices["is_new"] = (devices["id_15"] == "New").map({True: "true", False: "false"})
    devices = devices.drop(columns=["id_15"])

    print("Building NEXT edges (temporal chain per card)...")
    next_edges = build_next_edges(txn)

    txn_out = txn[[
        "TransactionID", "TransactionDT", "ts", "TransactionAmt", "ProductCD", "channel",
        "risk_score", "addr1", "addr2", "dist1", "dist2", "P_emaildomain", "R_emaildomain",
        "customer_id", "card_id", "device_id",
    ]].rename(columns={
        "TransactionID": "transaction_id", "TransactionDT": "transaction_dt",
        "TransactionAmt": "amount", "ProductCD": "product_cd",
        "P_emaildomain": "p_emaildomain", "R_emaildomain": "r_emaildomain",
    })

    print("Writing derived CSVs...")
    customers.to_csv(DERIVED / "customers.csv", index=False)
    cards.to_csv(DERIVED / "cards.csv", index=False)
    txn_out.to_csv(DERIVED / "transactions.csv", index=False)
    devices.to_csv(DERIVED / "devices.csv", index=False)
    email_domains.to_csv(DERIVED / "email_domains.csv", index=False)
    billing_regions.to_csv(DERIVED / "billing_regions.csv", index=False)
    next_edges.to_csv(DERIVED / "next_edges.csv", index=False)

    # closed_cases_history.csv is loadable close to as-is; normalize report_filed
    # from Yes/No to GSQL's expected lowercase true/false BOOL literal.
    closed = pd.read_csv(RAW / "closed_cases_history.csv")
    closed["report_filed"] = closed["report_filed"].map({"Yes": "true", "No": "false"})
    closed.to_csv(DERIVED / "closed_cases.csv", index=False)

    cc_txn_edges, cc_card_edges = build_closed_case_edges(closed)
    cc_txn_edges.to_csv(DERIVED / "closed_case_txn_edges.csv", index=False)
    cc_card_edges.to_csv(DERIVED / "closed_case_card_edges.csv", index=False)

    print("Done:")
    for f in sorted(DERIVED.glob("*.csv")):
        print(f"  {f.name}: {sum(1 for _ in open(f, encoding='utf-8')) - 1:,} rows")


if __name__ == "__main__":
    run()
