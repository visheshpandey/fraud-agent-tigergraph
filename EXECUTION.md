# EXECUTION — Live Progress Tracker

> **This is the state document. It changes constantly.**
> For the design and the "why", see [PLAN.md](PLAN.md).
>
> **Deadline: 2026-09-24, 11:59 PM IST. No resubmissions.**

## How to use this file

- Tick boxes as work completes. **Never tick something that hasn't been verified to run.**
- Keep **Current State** below accurate — it is the first thing read when resuming.
- Log surprises in **Decisions & Deviations**. When reality contradicts the plan, reality wins.
- **Never put secrets in this file.** Record *that* a credential exists and where, not its value.

---

## Current State

**Last updated:** 2026-09-22
**Phase:** 0 — blockers
**Next action:** download the HHGOA_IEEE dataset to `data/raw/`, then read its README
**Blocked on:** dataset download (manual) · Savanna workspace · Gemini key check

---

## Live config

Values go in `.env` (gitignored) — this table only tracks *whether* each is established.

| Item | Status | Note |
|---|---|---|
| Savanna host | ☐ | `https://<id>.i.tgcloud.io`, port 443 |
| Savanna secret | ☐ | Admin Portal → User Management → create secret. `.env` as `TG_SECRET` |
| TigerGraph version | ☐ | **must be 4.2+** for vector attributes |
| Graph name | ☐ | e.g. `FraudGraph` |
| Gemini API key | ☐ | `.env` as `GOOGLE_API_KEY` |
| Gemini models | ☐ | reasoning model + `text-embedding-004` (768 dim) |
| MCP allowlist | ☐ | `TG_ALLOWED_TOOLS` — prevents the ~29k token blowup |

---

## Phase 0 — Blockers (human-in-the-loop)

- [ ] Download [HHGOA_IEEE dataset](https://drive.google.com/drive/folders/1YDJUW1fiE7Jx8R9KqknC4IcsED9zll2A) → `data/raw/`
      *(link-shared folder, not readable through the Drive connector — must be manual)*
- [ ] **Read the dataset README end to end**
- [ ] Record from README: exact **answer file format** — *graded deliverable, do not guess*
- [ ] Record from README: customer identifier column, risk score column name, file inventory
- [ ] Record from README: how the 20 benchmark cases are structured / triggered
- [ ] Create Savanna workspace; enable auto-start + auto-stop; note version
- [ ] Create Savanna secret; confirm `conn.getToken(secret)` works
- [ ] Verify Gemini key; note rate limits (matters when running 20 cases)

**Findings from the README** — fill this in, it overrides PLAN.md where they disagree:

```
(paste answer format + key column names here)
```

---

## Phase 1 — Project skeleton

- [x] Directory structure created
- [x] `PLAN.md` written
- [x] `EXECUTION.md` written
- [ ] `git init` + `.gitignore` (`data/`, `.env`, `__pycache__/`, `out/`, `.venv/`)
- [ ] First commit
- [ ] venv + install: `pyTigerGraph`, `tigergraph-mcp`, `langgraph`,
      `langchain-mcp-adapters`, `streamlit`, `python-dotenv`;
      **upgrade `google-genai` (0.3.0 installed, is old)**
- [ ] `src/tg/connection.py` — connection helper reading `.env`
- [ ] Smoke test: `conn.echo()` succeeds

---

## Phase 2 — Graph + data

- [ ] `schema/01_schema.gsql` — vertices + edges created
- [ ] `schema/02_vector_attrs.gsql` — `DocChunk.emb`, `Case.emb` (768, COSINE)
- [ ] `src/prep/` ETL — **`usecols` to drop V1–V339, downcast dtypes, chunked reads (8 GB RAM)**
- [ ] Derived dimension CSVs → `data/derived/`
- [ ] `schema/03_loading_jobs.gsql` — loading jobs (**not** DataFrame upserts for bulk)
- [ ] Data loaded; **vertex/edge counts match derived CSV row counts**
- [ ] `Transaction-NEXT->Transaction` temporal chains built

---

## Phase 3 — GSQL agent tools

Pre-install all. **`INSTALL QUERY` takes minutes each and must never run at demo time.**

- [ ] `card_transaction_window`
- [ ] `customer_profile`
- [ ] `device_shared_accounts`
- [ ] `email_shared_cards`
- [ ] `fraud_ring_component`
- [ ] `velocity_check`
- [ ] `amount_anomaly`
- [ ] `similar_closed_cases` *(vectorSearch over `Case.emb`)*
- [ ] `policy_search` *(vectorSearch over `DocChunk.emb`)*
- [ ] `write_case` / `append_evidence` / `record_action`
- [ ] Ring algorithms exercised via `CALL GDBMS_ALGO.*` (louvain / wcc / k_core / pagerank)
- [ ] **Every query hand-run with a real seed before the agent may call it**

---

## Phase 4 — GraphRAG layer

- [ ] Policy docs + typologies + regulatory refs chunked
- [ ] Chunks embedded → `DocChunk.emb`
- [ ] `FraudPattern` vertices for the 5 documented patterns, linked to chunks
- [ ] Closed cases (months 1–4) embedded → `Case.emb`
- [ ] Verified: a known policy phrase retrieves the right chunk first
- [ ] Verified: a known-similar closed case ranks first in `similar_closed_cases`

---

## Phase 5 — Agent

- [ ] MCP session helper — **one session held for the whole run**
- [ ] MCP tool list verified empirically; allowlist confirmed active
- [ ] Case record model with **`nba_before` and `nba_after` as first-class fields**
- [ ] Nodes: `trigger` · `open_case` · `gather_evidence` · `assess` · `check_sufficiency` ·
      `request_evidence` · `decide_action` · `explain` · `update_memory`
- [ ] `RiskAssessment` returns `confidence` + explicit `evidence_gaps`
- [ ] Decision matrix: risk × confidence × reversibility → action + approval route
- [ ] Mock APIs for simulated actions (validate txn, step-up auth, analyst request)
- [ ] Evidence-gathering loop capped at 2 rounds
- [ ] End-to-end on ONE case, with tracing
- [ ] **Verified: agent requests more evidence at least once, and `nba_before` ≠ `nba_after` somewhere**

---

## Phase 6 — Benchmark

- [ ] `src/eval/run_cases.py`
- [ ] All 20 cases → `out/cases/` in the README's format
- [ ] Each case also **written to the graph**
- [ ] SAR generated where policy requires one
- [ ] 3 cases spot-checked by hand against the policy docs
- [ ] **Run this early, not at the deadline** (Gemini rate limits)

---

## Phase 7 — UI

- [ ] Streamlit: case selector, investigation timeline, evidence panel
- [ ] Confidence / uncertainty indicator
- [ ] **NBA before-vs-after comparison** — the money shot on camera
- [ ] Approval route display
- [ ] Fraud-ring subgraph visualization
- [ ] Next.js — **stretch only**, do not start unless Phases 0–8 are done

---

## Phase 8 — Submission *(budget 2 hours; required, plus 10% of score)*

- [ ] GitHub repo public; README explains architecture + how TigerGraph is used
- [ ] Demo video 3–5 min, end to end, **recorded with Savanna already warm**
- [ ] Blog post: what built / architecture / TigerGraph usage / agentic capabilities /
      learnings / what you'd improve
- [ ] Social post on X or LinkedIn, links blog or demo, **tags @TigerGraphDB**
- [ ] **Submit:** https://forms.gle/yxXzqSULGgZ9VUF56 — **team lead only, by Sept 24 11:59 PM IST**

---

## Decisions & Deviations

| Date | What changed | Why |
|---|---|---|
| 2026-09-22 | Savanna over Community Edition | Laptop has 8 GB RAM; CE needs 16 GB min. Docker not installed, WSL not installed. |
| 2026-09-22 | Hand-rolled GraphRAG over `tigergraph/graphrag` | Official stack is multi-container and ships a competing chat UI |

---

## Session Log

| Date | Done | Next |
|---|---|---|
| 2026-09-22 | Brief read; TigerGraph stack researched; `PLAN.md` + `EXECUTION.md` written; dir skeleton created | Phase 0 blockers — dataset download + README |
