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
**Phase:** 3 done, entering 4 — full dataset is LOADED and VERIFIED on Savanna (counts below
match expected exactly); 6 GSQL agent-tool queries installed; Phase 5 agent skeleton already
matches the exact answer format.
**Next action:** Phase 4 — chunk the Fraud Policy + 5 patterns text, embed via Gemini
(`gemini-embedding-001`, truncated to 768 dim), load into `DocChunk.emb`; embed closed-case
narratives into `ClosedCase.emb`
**Blocked on:** nothing — clear to proceed

**Live graph verified (2026-09-22):**
```
Customer 13553 · Card 14322 · Transaction 590742 · DeviceProfile 9774
EmailDomain 60 · BillingRegion 332 · ClosedCase 5565 · InvestigationCase 0 · DocChunk 0
OWNS 14318 · MADE 590742 · FROM_DEVICE 140784 · PURCHASER_EMAIL 496262
RECIPIENT_EMAIL 137453 · BILLED_IN 525003 · NEXT 576424 · ON_CARD 5565
INVOLVES 14955 · INVOLVES_CUSTOMER 5565 · CONNECTED_TO 96
```
Transaction count matches raw file exactly (590,742). Card count is 14,322 vs our own
dedup's 14,318 — 4 extra, traced to legitimate sparse source data (some cards genuinely
lack card4/card6 in Vesta's original columns), not a loading bug; not worth chasing further.

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
| Gemini models | [x] | **`gemini-3.6-flash`** for reasoning (chat), **`gemini-embedding-001`** truncated to 768 dim via `output_dimensionality=768` for embeddings — `text-embedding-004` from PLAN.md is deprecated/404. Neither wired into `src/agent/llm.py` yet (still stubbed) |
| MCP allowlist | ☐ | `TG_ALLOWED_TOOLS` — prevents the ~29k token blowup. Not started — no MCP server running yet |

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
**Done:** `src/agent/nodes.py::decision_matrix` implements R1-R10 as code; verified against
3 mock scenarios including one where `initial_actions` → `final_actions` changes.

**Stopping rule (exact):** stop when fraud probability ≥0.85 or ≤0.15 with 2+ independent
evidence pieces, OR a verification response settles it, OR further steps won't change the
decision (state why in `stop_reason`).

**Suggested schema — DONE, reconciled and live.** See Phase 2 below for what changed
(3 reserved-keyword renames, InvestigationCase vocabulary, multi-pair edges).

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
- [x] venv + install: `pyTigerGraph` 2.0.4, `python-dotenv`. `langgraph`/`pydantic` installed
      earlier for the agent skeleton. **Still missing:** `tigergraph-mcp`, `langchain-mcp-adapters`,
      `streamlit`. `google-genai` 0.3.0 still not upgraded — using deprecated
      `google.generativeai` for now since it's the one confirmed working (see Live config)
- [x] `src/tg/connection.py` — works, but had to work around a pyTigerGraph 2.0.4 bug
      (see Phase 2 note below) rather than using `getToken()` directly
- [x] Smoke test: `conn.echo()` succeeds — returns `"Hello GSQL"`

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
- [x] `src/prep/etl.py` — `usecols` drops V1-V339/C*/D*/M*, downcast dtypes. Ran fine on 8GB
      RAM without chunking (column subset keeps it small despite the 708MB raw file)
- [x] Derived CSVs → `data/derived/`: customers, cards, transactions, devices, email_domains,
      billing_regions, next_edges, closed_cases, closed_case_txn_edges, closed_case_card_edges
- [x] `schema/03_loading_jobs.gsql` — loading jobs via `conn.runLoadingJobWithFile`, chunked
      (50k rows/chunk) with retry for the two large files (transactions, next_edges) — a
      single synchronous POST for the full file hit an SSL EOF from Savanna's proxy
- [x] Data loaded; **vertex/edge counts verified exactly matching expected** — see the table
      in Current State above
- [x] `Transaction-NEXT->Transaction` temporal chains built — 576,424 edges, verified

**Card-id derivation limitation (documented, not fixable from public data):** which
`(card1..card6)` tuples constitute "the same physical card" is not reliably deducible —
empirically, a case-pack customer's flagged transaction shares an identical
`(card1,card4,card6)` with a transaction group case_pack does NOT label the same card, and
card2/3/5 nulling doesn't correlate with card identity either (known Vesta missingness
artifact, independent of card identity). Resolved by grouping on `(customer_id, card1,
card4, card6)` as a best-effort partition, then **overriding with the authoritative
`card_id` from `case_pack.csv`/`closed_cases_history.csv`** wherever a transaction is named
there — verified **0 mismatches across all 20 exam cases**. Unlabeled cards get our own
`-K{n}` suffix (documented in `src/prep/etl.py`'s module docstring).

**Two GSQL/pyTigerGraph bugs found and fixed while loading (both cost real debugging time,
both now fixed and documented in the affected files' comments):**
1. `conn.getToken(secret)` fails with "User authentication failed" — pyTigerGraph 2.0.4's
   `_prep_req` attaches a default `tigergraph`/`tigergraph` Basic-auth header to the token
   request itself regardless of the `authMode` argument, and Savanna rejects that header
   before the secret in the body is even checked. **Fix:** fetch the JWT manually
   (`POST {host}/gsql/v1/tokens`) and construct `TigerGraphConnection(..., apiToken=<jwt>)`
   directly — `src/tg/connection.py`.
2. `SPLIT($col, "|")` inline in an edge's `VALUES(...)` does **not** fan out into multiple
   edges the way it does for a SET-typed vertex *attribute* — it silently loaded the entire
   pipe-joined string as one malformed vertex id (caught ~2,107 stray `Transaction`
   vertices this way on the first attempt). **Fix:** explode multi-value columns into flat
   `(case_id, target_id)` CSVs in Python (`src/prep/etl.py::build_closed_case_edges`) and
   load those with plain one-row-one-edge statements — `schema/03_loading_jobs.gsql`.
3. Also: `runLoadingJobWithFile` explicitly does not honor `USING header="true"` — the
   header row must be stripped from the file before upload or it loads as a garbage row.

---

## Phase 3 — GSQL agent tools

Pre-install all. **`INSTALL QUERY` takes minutes each and must never run at demo time.**

- [x] `card_transaction_window` — installed. Deliberately returns N most-recent txns rather
      than doing DATETIME arithmetic in GSQL; velocity/amount-anomaly windowing is computed
      agent-side in Python from this list
- [x] `customer_profile` — installed
- [x] `device_shared_accounts` — installed
- [x] `fraud_ring_component` — installed. Simplified to a fixed 2-hop device-based traversal
      rather than an open-ended WHILE-loop BFS (safer to get right without live debugging
      time); cross-references `ClosedCase` via the `CASE_ON_CARD` reverse edge for known-fraud
      flagging
- [x] `similar_closed_cases` *(vectorSearch over `ClosedCase.emb`, SYNTAX v3)* — installed,
      **not yet smoke-tested** (no embeddings loaded yet — that's Phase 4)
- [x] `policy_search` *(vectorSearch over `DocChunk.emb`, SYNTAX v3)* — installed, same caveat
- [ ] ~~`email_shared_cards`~~ / ~~`velocity_check`~~ / ~~`amount_anomaly`~~ — **descoped.**
      Computed as Python-side derived signals from `card_transaction_window` +
      `customer_profile` output instead of separate GSQL queries — avoids fragile GSQL
      DATETIME/aggregation logic for marginal benefit over doing it in the agent
- [ ] ~~`write_case` / `append_evidence` / `record_action`~~ — **descoped as GSQL queries.**
      Will be plain `conn.upsertVertex()` calls from Python (simpler and better-tested than
      GSQL `INSERT INTO` DML under time pressure) — not yet implemented
- [ ] Ring algorithms via `CALL GDBMS_ALGO.*` (louvain / wcc / k_core / pagerank) — not started;
      `fraud_ring_component`'s 2-hop traversal covers the minimum viable ring signal for now
- [x] **Every query hand-run with a real seed before the agent may call it** —
      `card_transaction_window` and `customer_profile` verified against real customer C09933
      (2,792 txns, 128 devices, 32 billing regions — all plausible); `device_shared_accounts`
      verified against a real device shared by 5 customers; `fraud_ring_component` verified
      but found noisy for high-activity cards (100+ devices → hundreds of "connected" cards
      with no ranking) — added a `LIMIT 100` cap as a stopgap; **flagging that this query
      needs real tuning (e.g. restrict to devices marked "new"/suspicious, or rank by shared-
      device frequency) before it's a reliable ring signal, not just a working query.**
      `similar_closed_cases`/`policy_search` still untested — no embeddings loaded yet

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
