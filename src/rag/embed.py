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


def embed_text(text: str, task_type: str = "SEMANTIC_SIMILARITY", retries: int = 3) -> list[float]:
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
            time.sleep(2 * attempt)
    raise RuntimeError(f"Embedding failed after {retries} attempts") from last_err
