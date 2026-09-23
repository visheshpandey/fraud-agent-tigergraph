"""Embeds every closed case's narrative into ClosedCase.emb — this is the case
memory PLAN.md calls the centerpiece: "retrieve similar past cases" becomes a
single vectorSearch over 5,565 real historical investigations.

Batches both the Gemini embedding calls and the TigerGraph upserts (rather
than one API call per case) since 5,565 sequential round trips would be the
slowest part of the whole pipeline otherwise.
"""

from __future__ import annotations

import os
import time

import google.generativeai as genai
import pandas as pd
from dotenv import load_dotenv

from src.rag.embed import EMBED_DIM, EMBED_MODEL
from src.tg.connection import get_connection

load_dotenv()
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

BATCH_SIZE = 50
DERIVED = __import__("pathlib").Path(__file__).resolve().parents[2] / "data" / "derived"


def _narrative(row: pd.Series) -> str:
    notes = row["analyst_notes"] if isinstance(row["analyst_notes"], str) and row["analyst_notes"] else (
        f"Cleared alert, no confirmed fraud. Pattern: none."
        if row["outcome"] == "cleared" else "No analyst notes recorded."
    )
    return (
        f"{notes} Pattern: {row['pattern']}. Outcome: {row['outcome']}. "
        f"Exposure: ${row['exposure_usd']:.2f}. Transactions involved: {row['n_txns']}."
    )


def _embed_batch(texts: list[str], retries: int = 3) -> list[list[float]]:
    """Free tier is capped at 100 embed_content requests/minute AND ~1000/day.
    In practice the 429 seen while building this sometimes persisted across
    many minutes of retrying at 65s/attempt -- if the daily cap is what's
    actually hit, no amount of waiting within one run fixes it. Retry
    modestly (a real per-minute limit clears in ~40s) and let this job fail
    fast and get re-run later (it's idempotent) rather than block for
    several minutes on every batch on a bad day."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            res = genai.embed_content(
                model=EMBED_MODEL, content=texts,
                output_dimensionality=EMBED_DIM, task_type="RETRIEVAL_DOCUMENT",
            )
            return res["embedding"]
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"    batch attempt {attempt}/{retries} failed: {type(e).__name__} — waiting 20s", flush=True)
            time.sleep(20)
    raise RuntimeError("Embedding batch failed") from last_err


def run() -> None:
    conn = get_connection()
    closed = pd.read_csv(DERIVED / "closed_cases.csv")
    print(f"Embedding {len(closed)} closed cases in batches of {BATCH_SIZE}...")

    for start in range(0, len(closed), BATCH_SIZE):
        batch = closed.iloc[start : start + BATCH_SIZE]
        narratives = [_narrative(r) for _, r in batch.iterrows()]
        vectors = _embed_batch(narratives)

        vertices = [
            (row["case_id"], {"emb": vec})
            for (_, row), vec in zip(batch.iterrows(), vectors)
        ]
        conn.upsertVertices("ClosedCase", vertices)
        print(f"  {start + len(batch)}/{len(closed)}", flush=True)
        time.sleep(1.0)  # stay under the 100 req/min free-tier cap (1 request/batch)

    print("Done.")


if __name__ == "__main__":
    run()
