"""LLM interface — real Gemini calls (google.generativeai, not google-genai;
see src/rag/embed.py's docstring for why: google-genai 0.3.0 can't list
models against the current API surface, google.generativeai works end to end
despite its own deprecation warning).

`assess_risk_from_evidence` takes a free-text evidence bundle (already
assembled from real graph/tool output by the caller) rather than the
`ToolEvidence` list shape the mock version used — real evidence is prose plus
structured facts, not a fixed set of named tool outputs, so the caller is
responsible for building a clear evidence narrative and this module just
asks Gemini to reason over it with a fixed structured-output schema.
"""

from __future__ import annotations

import json
import os
import time

import google.generativeai as genai
from dotenv import load_dotenv

from .state import RiskAssessment

load_dotenv()
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])


# gemini-3.6-flash's free tier is capped at 20 generate_content requests PER
# DAY (not per minute -- discovered the hard way after exhausting it with a
# handful of test calls: quota_id "GenerateRequestsPerDayPerProjectPerModel-
# FreeTier", quota_value 20). A 20-case benchmark run needs far more than 20
# calls total. gemini-flash-lite-latest has an independent, much less
# restrictive free-tier quota and kept working immediately after 3.6-flash's
# daily cap was hit -- use it instead for the volume of calls this run needs.
REASONING_MODEL = "gemini-flash-lite-latest"

_MIN_SECONDS_BETWEEN_CALLS = 5.0
_last_call_at = 0.0


def _call_with_rate_limit(fn, *args, retries: int = 5, **kwargs):
    global _last_call_at
    last_err = None
    for attempt in range(1, retries + 1):
        elapsed = time.time() - _last_call_at
        if elapsed < _MIN_SECONDS_BETWEEN_CALLS:
            time.sleep(_MIN_SECONDS_BETWEEN_CALLS - elapsed)
        try:
            result = fn(*args, **kwargs)
            _last_call_at = time.time()
            return result
        except Exception as e:  # noqa: BLE001
            last_err = e
            _last_call_at = time.time()
            is_429 = "ResourceExhausted" in type(e).__name__ or "429" in str(e)
            wait = 20 if is_429 else 3 * attempt
            print(f"  [llm] attempt {attempt}/{retries} failed ({type(e).__name__}), waiting {wait}s")
            time.sleep(wait)
    raise RuntimeError("Gemini call failed after retries") from last_err

_ASSESS_SYSTEM_PROMPT = """You are a fraud investigation analyst for a bank. You are given
evidence gathered from the bank's transaction graph, customer profile, device/ring signals,
similar past cases, and relevant policy text. Assess the flagged activity and return a
structured risk assessment.

Rules for your assessment:
- `fraud_probability` must be your honest calibrated estimate, not the input risk_score.
  The risk_score is a model signal that is often wrong in both directions -- never echo it
  back as your answer.
- `pattern` must be one of: card_testing, card_not_present_fraud,
  card_not_present_new_device, out_of_region_use, account_takeover, undocumented, none.
  Use "undocumented" only when the evidence shows real coordinated/repeated abuse that fits
  none of the other five -- and fill in `pattern_description` describing it in your own
  words. Use "none" when the evidence looks legitimate.
- `evidence_gaps` should list, in plain English, any specific missing information that
  would change your confidence if you had it (e.g. "confirmation from the cardholder that
  they made this purchase"). Empty list if none.
- `rationale` should be 1-3 sentences citing the concrete evidence that drove your
  probability estimate.
- Half of all cases in this dataset are legitimate. An assessment that treats every high
  risk_score as fraud will be wrong roughly half the time -- weigh the graph evidence over
  the raw score.
"""

_EXPLAIN_SYSTEM_PROMPT = """You are writing the plain-English case summary and explanation
for a fraud investigation, for a human analyst to read. Cover: what evidence was used, why
additional evidence was requested if it was, and why the recommended actions follow from the
bank's fraud policy (cite rule numbers where given). Keep it to 2-6 sentences. Do not repeat
raw JSON -- write prose."""


# Built by hand rather than derived from RiskAssessment's pydantic schema:
# google.generativeai's proto Schema translator only understands a subset of
# JSON Schema (type/enum/items/properties/required/description) and raises
# "Unknown field for Schema" on anything pydantic adds for constraints or
# defaults (`minimum`/`maximum` from Field(ge=,le=), `default` from any
# field with one) -- both of which RiskAssessment has.
_RISK_ASSESSMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["fraud", "legitimate", "uncertain"]},
        "fraud_probability": {"type": "number"},
        "pattern": {"type": "string", "enum": [
            "card_testing", "card_not_present_fraud", "card_not_present_new_device",
            "out_of_region_use", "account_takeover", "undocumented", "none",
        ]},
        "pattern_description": {"type": "string"},
        "evidence_gaps": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": ["verdict", "fraud_probability", "pattern", "evidence_gaps", "rationale"],
}


def assess_risk_from_evidence(evidence_narrative: str) -> RiskAssessment:
    model = genai.GenerativeModel(REASONING_MODEL, system_instruction=_ASSESS_SYSTEM_PROMPT)
    resp = _call_with_rate_limit(
        model.generate_content,
        evidence_narrative,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=_RISK_ASSESSMENT_SCHEMA,
        ),
    )
    data = json.loads(resp.text)
    data.setdefault("pattern_description", "")
    return RiskAssessment.model_validate(data)


def generate_explanation(context_narrative: str) -> str:
    model = genai.GenerativeModel(REASONING_MODEL, system_instruction=_EXPLAIN_SYSTEM_PROMPT)
    resp = _call_with_rate_limit(model.generate_content, context_narrative)
    return resp.text.strip()
