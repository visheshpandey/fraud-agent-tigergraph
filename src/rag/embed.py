"""Gemini embedding wrapper, truncated to match the schema's 768-dim vector attrs.

PLAN.md specified `text-embedding-004` — that model returns 404 (deprecated/
removed). `gemini-embedding-001` is the current replacement; it natively
returns 3072 dims, but supports `output_dimensionality` to truncate via
Matryoshka representation learning, so 768 is requested directly rather than
changing the schema's DIMENSION to 3072.

Uses the deprecated `google.generativeai` package, not `google-genai` —
`google-genai` 0.3.0 (the version installed) can't even list models against
the current API surface (500/501 errors), while `google.generativeai` works
end to end despite its own deprecation warning. Swap once `google-genai` is
upgraded past 0.3.0.
"""

from __future__ import annotations

import os
import time

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

EMBED_MODEL = "models/gemini-embedding-001"
EMBED_DIM = 768


def embed_text(text: str, task_type: str = "SEMANTIC_SIMILARITY", retries: int = 2) -> list[float]:
    """Free tier caps embed_content at ~100 requests/minute AND ~1000/day.
    Only 2 short retries, not a long 65s-per-attempt backoff: callers
    (src/eval/run_cases.py::gather_evidence) treat a failure here as a soft,
    expected failure and degrade gracefully (skip case-memory/policy
    retrieval for that case) rather than losing the whole case over it -- so
    there is no reason to block a 20-case run for 5+ minutes per call on a
    rate limit that, in practice, has sometimes persisted for the rest of a
    day's testing. A real per-minute 429 clears in the two ~20s waits below;
    a day-scale 429 (with or without "PerDay" in the message -- the exact
    wording varies) fails fast either way.
    """
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            res = genai.embed_content(
                model=EMBED_MODEL, content=text,
                output_dimensionality=EMBED_DIM, task_type=task_type,
            )
            return res["embedding"]
        except Exception as e:  # noqa: BLE001 — retry on transient API errors
            last_err = e
            if "PerDay" in str(e):
                raise RuntimeError("Daily embed_content quota exhausted") from e
            time.sleep(20)
    raise RuntimeError(f"Embedding failed after {retries} attempts") from last_err
