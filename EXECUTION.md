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
**Phase:** 2 — schema is LIVE on Savanna (9 vertex types, all edges, 2 vector attributes
confirmed via `conn.getVertexTypes()`). Agent skeleton (Phase 5) already matches the exact
answer format.
**Next action:** ETL — `src/prep/` to turn `data/raw/*.csv` into loadable derived CSVs, then
`schema/03_loading_jobs.gsql` to bulk-load them
**Blocked on:** nothing — clear to proceed

**Written but NOT yet run against a live instance:** `schema/01_schema.gsql`,
`schema/02_vector_attrs.gsql`. They are drafted from the known IEEE-CIS column structure
and must be reconciled with the dataset README (customer id column, risk score column
name) before loading. Do not tick Phase 2 until they execute cleanly on Savanna.

---

## Live config

Values go in `.env` (gitignored) — this table only tracks *whether* each is established.

| Item | Status | Note |
|---|---|---|
| Savanna host | [x] | `https://tg-a7ee9332-e51c-40b6-8dd4-d58f6b1dd205.tg-2635877100.i.tgcloud.io` |
| Savanna secret | [x] | created via `CREATE SECRET` in Query Editor, saved to `.env` as `TG_SECRET` |
| TigerGraph version | [x] | **4.2.5** — supports vector attributes |
| Graph name | [x] | `FraudGraph` (in `.env`, not yet created on the server — schema not run yet) |
| Gemini API key | [x] | verified live via `google.generativeai` — `gemini-3.6-flash` responds. **Note:** that package is deprecated upstream; use `google-genai` (already installed) for real integration, not `google.generativeai` |
| Gemini models | ☐ | reasoning model TBD + `text-embedding-004` (768 dim) — not yet wired into `src/agent/llm.py` |
| MCP allowlist | ☐ | `TG_ALLOWED_TOOLS` — prevents the ~29k token blowup |

---

## Phase 0 — Blockers (human-in-the-loop)

- [x] Download [HHGOA_IEEE dataset](https://drive.google.com/drive/folders/1YDJUW1fiE7Jx8R9KqknC4IcsED9zll2A) → `data/raw/`
      *(landed in Downloads first, moved manually — Drive connector could not enumerate the folder)*
- [x] **Read the dataset README end to end**
- [x] Record from README: exact **answer file format** — see findings block above
- [x] Record from README: customer identifier column, risk score column name, file inventory
- [x] Record from README: how the 20 benchmark cases are structured / triggered
- [x] Create Savanna workspace; note version — **Workspace-1, TG-00 (16Gi), v4.2.5, Active.**
      Auto Suspend already 60min; Auto Start still Disabled (recommend enabling via "..." menu)
- [x] Create Savanna secret — created via `CREATE SECRET` in Query Editor; not yet tested with
      `conn.getToken(secret)` (no pyTigerGraph connection code written yet)
- [x] Verify Gemini key — confirmed live, `gemini-3.6-flash` responds. Rate limits not yet
      characterized (matters once running 20 cases back to back)

**Findings from the README** — this overrides PLAN.md where they disagree. README read in full
2026-09-22; source: `data/raw/README.md`.

**Files (confirmed on disk):** `transactions.csv` (590,742 rows, 708MB, cols = all 393 Vesta +
`customer_id`,`ts`,`channel`,`risk_score`), `identity.csv` (144,432 rows, online txns only, joins
on `TransactionID`), `closed_cases_history.csv` (5,565 rows: 4,665 confirmed_fraud / 900 cleared),
`case_pack.csv` (the 20 exam cases).

**IDs:** `customer_id` = `C01234`; card_id = `C01234-K1` (customer + card suffix, NOT our
card1-6 composite hash). `ProductCD=W` → in_person, no identity record. Everything else → online.

**Answer format (graded, exact):** one JSON file per case, `cases/<case_id>.json`, 20 files.
Top level: `case_id`, `case`, `evidence_requests`, `next_best_actions`, `sar`, `stop_reason`,
`tool_calls`, `tokens`, `latency_s`.
- `case`: status(open/closed_fraud/closed_legitimate/escalated), verdict(fraud/legitimate/uncertain),
  fraud_probability, pattern(enum below), pattern_description, affected_txn_ids,
  first_suspicious_txn_id, connected_card_ids, connected_device_profiles, exposure_usd,
  evidence[{claim,source,ref,entity_ids}], similar_prior_cases, summary, written_to_graph,
  graph_case_id
- `next_best_actions`: **`initial` / `final`** (not nba_before/nba_after), each a list of
  {action, route, reason}; `what_changed`
- `sar`: file(bool), reason, narrative, subjects, total_amount_usd, activity_dates
- Full worked example is in the README (case HHG-017) — use it as the literal target shape.

**Pattern enum (exact):** `card_testing` · `card_not_present_fraud` ·
`card_not_present_new_device` · `out_of_region_use` · `account_takeover` · `undocumented` · `none`

**Actions (exact strings, from policy):** `ALLOW_TRANSACTION`, `DECLINE_TRANSACTION`,
`MONITOR_CARD`, `MONITOR_CONNECTED_CARDS`, `WARN_CUSTOMER`, `VERIFY_WITH_CUSTOMER`,
`STEP_UP_AUTH`, `BLOCK_CARD`, `BLOCK_ALL_CARDS`, `GENERATE_REPORT`, `CREATE_CASE`,
`FILE_REPORT`, `ESCALATE_TO_ANALYST`, `CLOSE_NO_FRAUD`

**Approval routes (exact):** `auto` | `L1` (team lead) | `L2` (fraud manager) — NOT the
`analyst`/`dual`/`auto` scheme drafted in src/agent/nodes.py. Full route table is in the
policy §2. `BLOCK_CARD` is L1 if exposure ≤$2,500 else L2 — route depends on a *value*, not
just the action.

**Decision logic is a numbered rulebook (R1-R10), not a generic risk×confidence×reversibility
matrix.** Key rules: R1 verify before blocking on a weak single signal (prob<0.70); R2 customer
denies → block+create_case(+file_report if exposure>$1000 or shared device/ring); R3 customer
confirms → close_no_fraud; R4 no reply in 24h → monitor+decline, escalate if exposure>$500;
R5 card testing → decline+step_up, block_card if a >$100 purchase already cleared; R6 shared
device/region/email across cards → name it, create_case+file_report+monitor_connected_cards;
R7 disputed-but-matches-own-recurring-pattern → create_case+verify+warn, never block; R8
uncertain verdict + exposure>$500 or conflicting evidence → escalate_to_analyst; R9 undocumented
coordinated pattern → create_case+file_report+escalate, describe in own words; R10 never
BLOCK_ALL_CARDS unless 2+ cards confirmed fraud or credentials confirmed compromised.
**`src/agent/nodes.py::decision_matrix` must be rewritten against these rules, not the generic
matrix currently in place.**

**Stopping rule (exact):** stop when fraud probability ≥0.85 or ≤0.15 with 2+ independent
evidence pieces, OR a verification response settles it, OR further steps won't change the
decision (state why in `stop_reason`).

**Suggested schema (README's, ours diverges — reconcile):** vertices `Customer`, `Card`,
`Transaction`, `DeviceProfile` (not our `Device`), `EmailDomain`, `BillingRegion`, `ClosedCase`
(README treats this as its own vertex type, not folded into `Case`). Edges:
`Customer-OWNS->Card`, `Card-MADE->Transaction`, `Transaction-FROM_DEVICE->DeviceProfile`,
`Transaction-PURCHASER_EMAIL->EmailDomain` (not our `USES_EMAIL`), `Transaction-BILLED_IN->
BillingRegion`, `Transaction-NEXT->Transaction`, `ClosedCase-INVOLVES->Transaction`,
`ClosedCase-ON_CARD->Card`, `ClosedCase-CONNECTED_TO->Card`.

**Vector store target:** load closed-case narratives + this README's pattern section + the
policy + regulatory PDFs (FinCEN/FATF/FFIEC/OFAC, links in README) into vector search —
confirms our `DocChunk`/policy_search design, just needs real content now.

**Evidence simulation is required, not optional:** customer/analyst replies are NOT provided
by the exam. The agent must simulate them itself and record the assumption in
`evidence_requests[].assumed_response`. Our `tools.py` mock action APIs already do this shape
of thing — needs its output format aligned to `evidence_requests`.

**Rules:** never use the original public Kaggle IEEE-CIS files to recover outcomes
(disqualification). Every ID in answers must exist in this dataset.

**Consequence:** `src/agent/state.py`, `nodes.py` (esp. `decision_matrix`), and `schema/01_schema.gsql`
all need rework to match this exact vocabulary before Phase 2/6 can proceed correctly.

---

## Phase 1 — Project skeleton

- [x] Directory structure created
- [x] `PLAN.md` written
- [x] `EXECUTION.md` written
- [x] `git init` + `.gitignore` (`data/`, `.env`, `__pycache__/`, `out/`, `.venv/`)
- [x] First commit
- [ ] venv + install: `pyTigerGraph`, `tigergraph-mcp`, `langgraph`,
      `langchain-mcp-adapters`, `streamlit`, `python-dotenv`;
      **upgrade `google-genai` (0.3.0 installed, is old)**
- [ ] `src/tg/connection.py` — connection helper reading `.env`
- [ ] Smoke test: `conn.echo()` succeeds

---

## Phase 2 — Graph + data

- [x] `schema/01_schema.gsql` — **LIVE on Savanna.** Reconciled against the README's
      suggested schema: `Customer, Card, Transaction, DeviceProfile, EmailDomain,
      BillingRegion, ClosedCase, InvestigationCase, DocChunk` + all edges. Renamed 3 fields
      that hit reserved GSQL keywords: `screen`→`screen_res`, `proxy`→`proxy_flag`, and the
      `Case` vertex itself → `InvestigationCase` (CASE WHEN is reserved). `InvestigationCase`
      mirrors the README's answer-format `case` object field-for-field.
- [x] `schema/02_vector_attrs.gsql` — **LIVE.** `ClosedCase.emb` + `InvestigationCase.emb`,
      768-dim COSINE HNSW. Needed `USE GLOBAL` before both `CREATE` and `RUN GLOBAL SCHEMA_
      CHANGE JOB` (graph-scoped `USE GRAPH` context fails with "Please 'use global' first").
- [x] Verify workspace version — **4.2.5**, confirmed via `conn.getVer()`
- [x] Both schema scripts execute cleanly against Savanna — confirmed via `conn.getVertexTypes()`
      returning all 9 types

**pyTigerGraph gotcha (cost real time, worth flagging):** `conn.getToken(secret)` fails with
"User authentication failed" on this Savanna instance — pyTigerGraph 2.0.4's `_prep_req`
attaches a default `tigergraph`/`tigergraph` Basic-auth header to the token request itself
regardless of the `authMode` argument, and Savanna rejects that header before the secret in
the body is even checked. Fix: fetch the JWT manually (`POST {host}/gsql/v1/tokens` with
`{"secret": ..., "lifetime": ...}` via `requests`) and construct `TigerGraphConnection(host=,
graphname=, apiToken=<jwt>)` directly. Implemented in `src/tg/connection.py`.
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

- [ ] MCP session helper — **one session held for the whole run** *(no MCP server exists
      yet — `src/agent/tools.py` has a documented seam for it, mock backend for now)*
- [ ] MCP tool list verified empirically; allowlist confirmed active
- [x] Case record model with **`nba_before` and `nba_after` as first-class fields**
      (`src/agent/state.py::CaseState`)
- [x] Nodes: `trigger` · `open_case` · `gather_evidence` · `assess` · `check_sufficiency` ·
      `request_evidence` · `decide_action` · `explain` · `update_memory`
      (`src/agent/nodes.py`, wired in `src/agent/graph.py`)
- [x] `RiskAssessment` returns `confidence` + explicit `evidence_gaps`
      *(stubbed heuristic in `src/agent/llm.py`, not a real Gemini call yet)*
- [x] Decision matrix: risk × confidence × reversibility → action + approval route
      (`src/agent/nodes.py::decision_matrix`, explicit code, not prompt text)
- [x] Mock APIs for simulated actions (validate txn, step-up auth, analyst request)
      (`src/agent/tools.py`)
- [x] Evidence-gathering loop capped at 2 rounds — verified: with a forced
      always-uncertain assessment, the loop still terminates at `round_count == 2` and
      routes to `decide_action` regardless of confidence
- [x] End-to-end on ONE case, run via `python -m src.agent.graph`
      (mock tools + stubbed LLM only — no TigerGraph, no real Gemini)
- [x] **Verified: agent requests more evidence at least once, and `nba_before` ≠ `nba_after`**
      — the `card-ambig-042` mock scenario does exactly this
      (`gather_more_evidence`/`analyst` → `no_action`/`auto` after owner confirmation)

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
