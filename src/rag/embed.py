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


def embed_text(text: str, task_type: str = "SEMANTIC_SIMILARITY", retries: int = 5) -> list[float]:
    """Free tier caps embed_content at ~100 requests/minute AND ~1000/day.
    A per-minute 429 is worth a ~65s wait; a per-DAY 429 will still be a 429
    in 65s (or in 5 minutes) since it doesn't reset until the daily window
    rolls over -- fail immediately in that case rather than burning minutes
    per call. Callers (src/eval/run_cases.py) treat this as a soft failure
    and degrade gracefully rather than losing the whole case over it.
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
            is_429 = "ResourceExhausted" in type(e).__name__ or "429" in str(e)
            time.sleep(65 if is_429 else 2 * attempt)
    raise RuntimeError(f"Embedding failed after {retries} attempts") from last_err
