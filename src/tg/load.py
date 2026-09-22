"""Uploads data/derived/*.csv and runs the load_fraud_graph loading job.

`conn.runLoadingJobWithFile()` warns that `USING header="true"` in the GSQL
job is not honored via this upload path — the header row must be stripped
before the file is sent, or it gets loaded as a (garbage) data row. So the
job (schema/03_loading_jobs.gsql) has no `header=` option at all, and every
CSV is re-written headerless to a scratch copy right before upload.

Each call re-runs the WHOLE job, but only the FILENAME variable matching the
given `fileTag` gets a real file for that call — other LOAD statements in the
job reference FILENAMEs that stay unbound and are skipped. Vertices must
finish loading before edges that reference them, so files are uploaded in
that order.

Large files (transactions.csv at 590k rows, next_edges.csv at 576k) get a
single synchronous POST killed by an SSL EOF from Savanna's proxy — well
under the 128MB size limit, so this is a timeout, not a size rejection.
Fixed by chunking any file over CHUNK_THRESHOLD rows into CHUNK_SIZE-row
pieces uploaded one at a time, with a retry per chunk.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from src.tg.connection import get_connection

DERIVED = Path(__file__).resolve().parents[2] / "data" / "derived"
JOB_NAME = "load_fraud_graph"

CHUNK_THRESHOLD = 100_000
CHUNK_SIZE = 50_000
MAX_RETRIES = 3

# (source CSV, FILENAME variable) — vertices before edges, since ON_CARD /
# CONNECTED_TO / INVOLVES / INVOLVES_CUSTOMER (bound to f_closed_cases) and
# every f_transactions-bound edge need their target vertices to already exist.
FILES = [
    ("customers.csv", "f_customers"),
    ("cards.csv", "f_cards"),
    ("devices.csv", "f_devices"),
    ("email_domains.csv", "f_email_domains"),
    ("billing_regions.csv", "f_billing_regions"),
    ("transactions.csv", "f_transactions"),  # loads Transaction vertices AND their edges
    ("next_edges.csv", "f_next_edges"),
    ("closed_cases.csv", "f_closed_cases"),  # loads ClosedCase vertices AND their edges
    ("closed_case_txn_edges.csv", "f_cc_txn_edges"),
    ("closed_case_card_edges.csv", "f_cc_card_edges"),
]


def _iter_chunks(src: Path, scratch_dir: Path) -> list[Path]:
    """Splits src (assumed to have a header row) into headerless chunk files."""
    with open(src, encoding="utf-8") as f:
        next(f)  # drop header row
        lines = f.readlines()

    if len(lines) <= CHUNK_THRESHOLD:
        dst = scratch_dir / src.name
        with open(dst, "w", encoding="utf-8", newline="") as fout:
            fout.writelines(lines)
        return [dst]

    chunks = []
    for i in range(0, len(lines), CHUNK_SIZE):
        dst = scratch_dir / f"{src.stem}.part{i // CHUNK_SIZE}{src.suffix}"
        with open(dst, "w", encoding="utf-8", newline="") as fout:
            fout.writelines(lines[i : i + CHUNK_SIZE])
        chunks.append(dst)
    return chunks


def _upload_with_retry(conn, filepath: Path, tag: str) -> dict:
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return conn.runLoadingJobWithFile(str(filepath), tag, JOB_NAME, timeout=600_000)
        except Exception as e:  # noqa: BLE001 — retry on any transient network error
            last_err = e
            print(f"    attempt {attempt}/{MAX_RETRIES} failed: {type(e).__name__}: {e}")
            time.sleep(3 * attempt)
    raise RuntimeError(f"Failed to load {filepath.name} after {MAX_RETRIES} attempts") from last_err


def run() -> None:
    conn = get_connection()
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        for filename, tag in FILES:
            src = DERIVED / filename
            chunks = _iter_chunks(src, scratch)
            print(f"Loading {filename} ({tag}) — {len(chunks)} chunk(s)...")
            for i, chunk in enumerate(chunks, 1):
                print(f"  chunk {i}/{len(chunks)}: {chunk.name}")
                result = _upload_with_retry(conn, chunk, tag)
                stats = result[0]["statistics"]["parsingStatistics"] if result else {}
                print(f"    {stats}")


if __name__ == "__main__":
    run()
