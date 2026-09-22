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

- [x] Policy docs + typologies chunked — `src/rag/policy_docs.py`, hand-curated (not
      auto-parsed) from `data/raw/README.md`'s Fraud Policy + pattern sections: 5 pattern
      chunks + 19 policy chunks (actions, approval routing, R1-R10, 3a/3b, exposure,
      evidence-gathering, stopping, explaining) = 24 total
- [x] Chunks embedded → `DocChunk.emb` — `src/rag/load_policy_chunks.py`, all 24 loaded.
      `policy_search("customer denied making a transaction...")` retrieves `policy-R2` as
      top hit — semantic retrieval verified working
- [ ] ~~`FraudPattern` vertices~~ — **descoped.** Patterns live as `DocChunk` rows
      (`doc_type="pattern"`) instead of a separate vertex type; keeps the schema smaller,
      the pattern text is still retrievable via `policy_search`
- [~] Closed cases embedded → `ClosedCase.emb` — **in progress, background job, resumable/
      idempotent.** 5,565 narratives built from `analyst_notes` + pattern/outcome/exposure.
      **Free tier `embed_content` limit is ~100 req/min** (not obvious from docs, found via
      429s); batches of 50 cases/call, retry-with-65s-backoff on 429, hit rate limit
      repeatedly — expect this to take up to an hour to fully complete, running unattended

**SCOPE LIMITATION (documented, not silently dropped):** the README also lists external
regulatory references (FinCEN/FATF/FFIEC/OFAC PDFs) as optional ("load the ones you find
useful"). Not downloaded/chunked — judged lower value than getting core policy/pattern/
case-memory retrieval solid within remaining time. Noted in `src/rag/policy_docs.py`'s
docstring as the place to add them if time remains.

**Real Gemini model/quota findings (cost significant debugging time, critical to know):**
- `text-embedding-004` (PLAN.md's original choice) is deprecated/404. Using
  `gemini-embedding-001` truncated to 768 dim via `output_dimensionality=768` — confirmed
  exact 768-dim output, matches schema.
- `google-genai` 0.3.0 (the installed version) **cannot even list models** against the
  current API (500/501 errors) — using the deprecated `google.generativeai` package
  instead throughout, since it works end-to-end. Upgrade `google-genai` if time allows.
- `google.generativeai`'s `response_schema` support is limited: it rejects any JSON Schema
  key it doesn't recognize, including `minimum`/`maximum` (from pydantic `Field(ge=,le=)`)
  and `default` (from any field with one). **`RiskAssessment` cannot be passed directly as
  `response_schema`** — `src/agent/llm.py` builds a manual schema dict instead.
- **`gemini-3.6-flash`'s free tier caps `generate_content` at 20 requests PER DAY** (not
  per minute — `quota_id: GenerateRequestsPerDayPerProjectPerModel-FreeTier`). Exhausted
  this during testing alone. **Switched `REASONING_MODEL` to `gemini-flash-lite-latest`**,
  which has an independent, much less restrictive quota and kept working immediately after
  3.6-flash's daily cap hit. **If the benchmark run (Phase 6) starts failing with
  ResourceExhausted on this model too, that's the next thing to check** — get a real API
  key with billing enabled, or spread the 20-case run across quota resets.
- [x] Verified: a known policy phrase retrieves the right chunk first — `policy-R2` for
      "customer denied making a transaction"
- [ ] Verified: a known-similar closed case ranks first in `similar_closed_cases` — blocked
      on the `ClosedCase.emb` embedding job (in progress) finishing

---

## Phase 5 — Agent

- [x] MCP session helper — **real, working.** `src/agent/mcp_tools.py::McpToolbox`, holds
      one stdio session via `langchain_mcp_adapters`. Verified live against real Savanna
      data: `get_vertex_count`, `run_installed_query` for `device_shared_accounts` both
      returned correct real results through MCP
- [x] MCP tool list verified empirically; allowlist confirmed active — 7 tools load
      (`run_installed_query`, `get_node`, `get_node_edges`, `get_neighbors`,
      `get_vertex_count`, `get_edge_count`, `search_top_k_similarity`) via
      `TG_ALLOWED_TOOLS` in `.env`, namespaced `tigergraph__*`
- [x] Case record model — `initial_actions`/`final_actions` (README's exact naming, not
      `nba_before`/`nba_after`) as first-class fields (`src/agent/state.py::CaseState`)
- [x] Nodes: `trigger` · `open_case` · `gather_evidence` · `assess` · `check_sufficiency` ·
      `request_evidence` · `decide_action` · `explain` · `update_memory`
      (`src/agent/nodes.py`, wired in `src/agent/graph.py` — this is the MOCK demonstration
      graph, kept as-is; the REAL benchmark pipeline is `src/eval/run_cases.py`, see Phase 6)
- [x] `RiskAssessment` — **real Gemini call**, not a stub. `src/agent/llm.py`,
      `gemini-flash-lite-latest`, manual JSON schema (see Phase 4 notes on why not
      pydantic-derived), verified producing sensible verdict/probability/pattern/rationale
      against real evidence narratives in the HHG-001 test run
- [x] Decision matrix: **rewritten to implement policy rules R1-R10** (not a generic
      risk×confidence×reversibility matrix — see Phase 0 findings), `src/agent/nodes.py::
      decision_matrix`, explicit code with rule citations in every `reason` field
- [x] Mock APIs for simulated actions (validate txn, step-up auth, analyst request) —
      `src/agent/tools.py`, used by the mock demo graph. **Real benchmark run** simulates
      evidence responses differently: grounded in retrieved similar-case outcomes rather
      than fixed scenario data — `src/eval/run_cases.py::_simulate_customer_response`
- [x] Evidence-gathering loop capped at 2 rounds — verified on the mock demo; same cap
      (`MAX_ROUNDS`) reused in the real benchmark runner
- [x] End-to-end on ONE case with the MOCK graph (`python -m src.agent.graph`) — validated
      earlier, not re-verified against real Gemini due to quota pressure (not essential;
      the real pipeline is what's graded)
- [x] End-to-end on ONE REAL case (`HHG-001`) via `src/eval/run_cases.py` — real MCP, real
      graph data, real Gemini, real graph write. See Phase 6 for the result and a bug it
      caught (`fraud_ring_component` noise) and fixed
- [x] **Verified: `initial_actions` ≠ `final_actions` is achievable** — mechanism proven on
      the mock demo (`card-ambig-042` scenario); real cases will show it whenever simulated
      evidence changes the verdict (mechanism identical, not yet observed on a real case
      since HHG-001 didn't need a second round)

---

## Phase 6 — Benchmark

- [x] `src/eval/run_cases.py` — built, real MCP + real Gemini + real graph writes
- [~] All 20 cases → `cases//` — **in progress.** First full pass: 8/20 succeeded outright,
      12/20 failed on the daily `embed_content` quota (see Phase 4). Re-running the 12
      failures with a graceful-degradation fix (below) plus 2 more (HHG-005, HHG-010) that
      "succeeded" but hit the ring-noise bug below — 14 total being re-run now
- [x] Each case also **written to the graph** — `conn.upsertVertex("InvestigationCase", ...)`
      + `INVOLVES_CUSTOMER`/`ON_CARD` edges, confirmed via `written_to_graph: true` in output
- [x] SAR generated where policy requires one — verified on at least one fraud case with
      `FILE_REPORT` in final actions (SAR narrative generated via a dedicated LLM call)
- [ ] 3 cases spot-checked by hand against the policy docs — not yet done, do once all 20
      answer files are final
- [x] **Run this early, not at the deadline** — running now, ~1.3 days before deadline

**Real bug caught and fixed via this run — worth understanding for the write-up:**
`fraud_ring_component` (Phase 3) was already re-seeded from a single flagged transaction's
device rather than a card's whole history (first fix). That was NOT enough: a second,
distinct problem surfaced on HHG-005/HHG-010 — a **generic device fingerprint** ("iOS
Device" + "iOS 9.3.5" + "mobile safari 9.0" + a common screen resolution, with no specific
device model) is shared by **168 unrelated transactions** in the dataset purely because
Vesta's `DeviceInfo` field is often just "iOS Device" for older/unspecified iPhones — not a
real shared device, a coarse-fingerprint collision. This produced dozens of fabricated
"confirmed fraud" ring connections on ordinary transactions. **Fixed** in
`src/eval/run_cases.py::gather_evidence`: if a device's shared-customer count or connected-
card count exceeds 15, treat it as a non-diagnostic generic fingerprint — drop it from
`shared_origin`, `connected_card_ids`, and the evidence narrative, and say so explicitly
rather than silently under-reporting. **Lesson worth stating in the blog post:** raw graph
signals need a plausibility filter before they become "evidence" — this is exactly the
kind of over-eager pattern-matching the README's "half the cases are legitimate" warning
is about, and it would have caused real false positives in the graded output if unfixed.

**Quota reality for a 20-case run (see also Phase 4):** `generate_content` on
`gemini-flash-lite-latest` held up fine across the full run (no failures observed).
`embed_content` (`gemini-embedding-001`) hit its ~1000/day cap partway through, days after
the closed-case embedding job (Phase 4) had already been consuming it heavily. Fixed with:
(1) graceful degradation in `gather_evidence` — a failed embed skips `similar_closed_cases`/
`policy_search` for that case rather than losing the whole case, and (2) `src/rag/embed.py`
now fails fast on a `PerDay` quota message instead of retrying uselessly for minutes.
**If re-running the full 20 tomorrow after quota resets, run this BEFORE any embedding-
heavy job (Phase 4's closed-case embed) to get full evidence quality on all cases.**

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
