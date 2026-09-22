# PLAN — Agentic Fraud Investigation Agent (TigerGraph HHGOA)

> **This is the design document. It stays mostly static.**
> For live progress and "what were we doing", see [EXECUTION.md](EXECUTION.md).

## Context

TigerGraph "Agentic Fraud Investigation" hackathon
([brief](https://docs.google.com/document/d/1AGFr8ltj8hF3CxJ2n2pWjyg7JkCsIbd9-z_kRuHP-dw/edit)).
Due **2026-09-24, 11:59 PM IST**. One submission per team, **no resubmissions**.

**Problem.** Fraud analysts manually stitch together transaction history, money-movement
traces, connected accounts, policy lookups and risk judgements before deciding what to do.
It is slow and usually finishes after the money is gone. The hackathon asks for an agent
that runs that investigation itself and — crucially — **reasons under uncertainty**:
deciding when it has enough evidence to act, and when it must go get more.

**Deliverables.** Working agent · GitHub repo · answer files for the 20 benchmark cases ·
3–5 min demo video · technical blog post · social post tagging @TigerGraphDB.

**Scoring drives the design.**

| Criterion | Weight |
|---|---|
| Investigation accuracy | 25% |
| **Next best action** (incl. handling uncertainty) | 25% |
| Agentic design & engineering | 15% |
| Innovation | 15% |
| Case summary & explainability | 10% |
| Demo quality | 10% |

Half the score is investigation accuracy + NBA. The NBA criterion explicitly rewards
*handling ambiguity, knowing when more evidence is needed, and revising the recommendation
once it arrives*. **That is the highest-leverage thing to build well — above UI polish.**

**Mandatory, each judged:** TigerGraph for *both* graph and vector storage · GSQL + graph
algorithms · TigerGraph MCP as the agent's tool surface · GraphRAG grounding (graph
evidence + policy docs, not raw data dumps) · a UI.

## Settled decisions

| Decision | Choice | Why |
|---|---|---|
| TigerGraph | **Savanna free cloud** | **Laptop has 8 GB RAM; Community Edition needs 16 GB min / 20 GB rec.** Docker isn't installed and WSL2 + Docker Desktop would consume 2–3 GB before TigerGraph starts. Hardware decides this. |
| Agent framework | **LangGraph** | State graph maps 1:1 onto the brief's 8-step flow; checkpointing gives case state + memory cheaply; scores directly against "agentic design". |
| LLM | **Gemini** | Only key on hand. Also supplies embeddings (`text-embedding-004`, 768 dim). |
| UI | **Streamlit**, Next.js only as stretch | Pure Python, no build step. Next.js is not a commitment. |
| GraphRAG | **Hand-rolled ~100-line retrieval layer** | Official `tigergraph/graphrag` is a multi-container platform (DB + embedding + completion + chat-history + nginx) and ships its own chat UI that would compete with our UI requirement. Cite it in the README as the pattern followed. |

## Verified environment

- Python **3.11.9** · Node **24.14.1** · git — present
- **Docker absent** · **WSL not installed**
- **RAM 7,991 MB total** · 140 GB disk free · x64, virtualization enabled in firmware
- Installed: `pandas` 2.3.1, `google-genai` 0.3.0 (**upgrade**), `google-generativeai` 0.8.6
- Missing: `pyTigerGraph`, `tigergraph-mcp`, `langgraph`, `langchain-mcp-adapters`, `streamlit`

## Architecture

```
Trigger (risk score / customer report / analyst)
   │
   ├─ LangGraph state machine ──────────────────────────────┐
   │    open_case → gather_evidence → assess                │
   │                     ↑              │                   │
   │                     └── request_evidence ←─ uncertain?  │
   │                                    │ confident         │
   │                     decide_action → explain → remember  │
   └────────────────────┬───────────────────────────────────┘
                        │ tools
        ┌───────────────┴────────────────┐
        │  TigerGraph MCP (allowlisted)  │
        └───────────────┬────────────────┘
                        │
   TigerGraph Savanna: graph (fraud network) + vectors (DocChunk.emb, Case.emb)
```

### Repo layout

```
goatask/
  data/raw/           dataset (gitignored)
  data/derived/       prepared CSVs for loading
  schema/
    01_schema.gsql            vertices + edges
    02_vector_attrs.gsql      DocChunk.emb, Case.emb
    03_loading_jobs.gsql
    queries/*.gsql            installed queries = agent tools
  src/
    tg/         connection, setup, loaders
    prep/       pandas ETL → derived CSVs
    rag/        chunk + embed policy docs, vector search
    agent/      LangGraph graph, nodes, tools, prompts
    cases/      case record model, writer to graph + JSON
    eval/       benchmark runner for the 20 cases
  app/streamlit_app.py
  out/cases/          the 20 answer files
```

### Graph schema

Standard modeling of IEEE-CIS — derive dimension vertices from transaction columns.
*Confirm exact column names and the customer identifier from the dataset README; the base
Kaggle dataset has no explicit customer id, but the brief cites ~13,500 customers so one
was likely added.*

**Vertices** — `Customer` · `Card` (card1–card6 composite) · `Transaction` (TransactionID,
TransactionDT, TransactionAmt, ProductCD, **risk_score**) · `Device` (DeviceInfo,
DeviceType, OS, browser, resolution) · `EmailDomain` · `BillingRegion` (addr1/addr2) ·
`FraudPattern` (the 5 documented patterns) · `Case` · `Evidence` · `Action` · `DocChunk`

**Edges** — `Customer-OWNS->Card` · `Card-MADE->Transaction` ·
`Transaction-FROM_DEVICE->Device` · `Transaction-USES_EMAIL->EmailDomain` ·
`Transaction-BILLED_IN->BillingRegion` · `Transaction-NEXT->Transaction` (temporal chain
per card) · `Case-INVOLVES->{Customer,Card,Transaction}` · `Case-HAS_EVIDENCE->Evidence` ·
`Case-RECOMMENDS->Action` · `Case-MATCHES->FraudPattern` · `Case-SIMILAR_TO->Case`

**Two vector attributes, both native TigerVector** — satisfies the graph+vector
requirement with no bolt-on vector DB:

```gsql
ALTER VERTEX DocChunk ADD VECTOR ATTRIBUTE emb(DIMENSION=768, METRIC="COSINE");
ALTER VERTEX Case     ADD VECTOR ATTRIBUTE emb(DIMENSION=768, METRIC="COSINE");
```

768 = Gemini `text-embedding-004`, inside every tier's dimension cap. `INDEXTYPE=HNSW` is
the default and is auto-maintained.

> **`Case.emb` is the centerpiece.** Embedding each closed case summary makes "retrieve
> similar past cases" a single `vectorSearch` — satisfying the *case memory* requirement
> and the *vector storage* requirement with one mechanism, and giving the agent genuine
> cross-case learning. Lead with this in the blog post.

### ETL — memory-constrained

**With 8 GB RAM, a naive `pd.read_csv` on the transaction file will fail.** IEEE-CIS has
394 columns, of which V1–V339 are anonymized floats we mostly don't need for graph
structure. Use `usecols` to take only identity/behavioral columns, downcast dtypes
(`float32`, `category`), read in chunks. Derive `Card`/`Device`/`EmailDomain`/
`BillingRegion` dimension tables in pandas, dedupe, write to `data/derived/*.csv`.

**Bulk-load via GSQL loading jobs over CSV, not `upsertVertexDataFrame`** — DataFrame
upserts POST JSON over REST++ per batch and will crawl at 590k rows. Reserve upserts for
small derived types (Case, Evidence, Action) written at runtime.

### Agent tools (installed GSQL queries)

Pre-install all during setup — **`INSTALL QUERY` takes minutes each and must never run at
demo time.** Prefer `CALL GDBMS_ALGO.*` packaged templates (no install step) for algorithms.

| Tool | Purpose |
|---|---|
| `card_transaction_window(card, days)` | recent activity on a card |
| `customer_profile(customer)` | accounts, cards, baseline behavior |
| `device_shared_accounts(device)` | one device ↔ many customers (ATO / ring signal) |
| `email_shared_cards(email)` | shared-email fan-out |
| `fraud_ring_component(seed, hops)` | WCC / k-core around a seed |
| `velocity_check(card, window)` | transaction count + amount spikes |
| `amount_anomaly(card)` | deviation from the card's own baseline |
| `similar_closed_cases(vec, k)` | **vectorSearch over `Case.emb`** — case memory |
| `policy_search(vec, k)` | **vectorSearch over `DocChunk.emb`** — GraphRAG |
| `write_case` / `append_evidence` / `record_action` | case progression |

Ring-detection algorithms: `GDBMS_ALGO.community.louvain` / `.wcc` (rings) · `.k_core`
(dense collusion cores) · `centrality.pagerank` (hub devices/cards) · `similarity.jaccard`.

**MCP allowlist is mandatory.** The full TigerGraph MCP tool set exceeds **~29,000 tokens**
and will blow the agent's context. Set `TG_ALLOWED_TOOLS` to roughly eight:
`run_installed_query`, `get_node`, `get_node_edges`, `get_neighbors`,
`search_top_k_similarity`, `upsert_vectors`, `add_nodes`, `add_edges`. Everything
domain-specific goes through `run_installed_query`. **Verify the real tool list
empirically** before writing bindings — published tool counts disagree with the README.

Hold **one** MCP session for the whole run; `client.get_tools()` opens and closes a
connection per call (~4× slower over ~9 calls):

```python
async with client.session("tigergraph-mcp-server") as session:
    tools = await load_mcp_tools(session)
```

### The investigation loop (LangGraph)

Nodes map onto the brief's 8 steps:

1. `trigger` — normalize incoming signal (risk score / customer report / analyst request)
2. `open_case` — create `Case` vertex, assign id
3. `gather_evidence` — ReAct sub-loop over the tools above
4. `assess` — emit structured `RiskAssessment`: matched patterns, fraud type, risk level,
   **confidence ∈ [0,1]**, explicit **`evidence_gaps: list[str]`**
5. `check_sufficiency` — conditional edge; route act vs. gather-more using confidence *and*
   action reversibility *and* policy requirements
6. `request_evidence` — controlled, policy-approved action (validate transaction with owner /
   step-up auth / ask analyst), **simulated via mock API**, deterministic response,
   **capped at 2 rounds**, loops back to `gather_evidence`
7. `decide_action` — next best action(s) + **approval route** (auto / analyst / dual)
8. `explain` — evidence used, why more was requested, why these actions
9. `update_memory` — write case + embedding back to the graph

**Uncertainty is the 25% criterion — make it explicit and demoable.** Decision matrix over
(risk level × confidence × action reversibility) → action + approval route. Rule of thumb:
low confidence + irreversible action (block account) must never auto-execute; it gathers
more evidence or escalates.

> **Do not miss this deliverable.** The brief requires the next best action and approval
> route recorded **both before any additional evidence is requested and after it is
> received**. Make `nba_before` and `nba_after` first-class fields on the case record from
> the start — easy to discover too late, and it is exactly the "revises its recommendation"
> behavior the NBA criterion rewards.

### Outputs per benchmark case

One answer file per case in `out/cases/` — *exact schema confirmed from the dataset README*
— containing the case record (investigation, evidence, findings, decisions, actions),
`nba_before` / `nba_after` with approval routes, and a suspicious activity report where
policy requires one. **The case must also be written to the graph**, not just the file.

### UI (Streamlit)

Single dashboard: case selector → investigation timeline → evidence panel → **confidence /
uncertainty indicator** → **NBA before-vs-after comparison** → approval route → fraud-ring
subgraph. Prioritize the before/after view; it is the clearest on-camera demonstration of
the highest-scoring behavior.

## Verification

- **Connection** — `conn.echo()`, then `conn.getVertexCount('*')` after load; counts must
  match derived CSV row counts
- **Vectors** — a known policy phrase retrieves the right chunk first; a known-similar
  closed case ranks first in `similar_closed_cases`
- **GSQL tools** — every installed query hand-run via `conn.runInstalledQuery` with a real
  seed before the agent is allowed to call it
- **MCP** — list tools from a live session; confirm the allowlist took effect
- **Agent** — one benchmark case end-to-end with tracing; verify it requests more evidence
  at least once and that `nba_before` ≠ `nba_after` on at least one case
- **Full benchmark** — all 20 cases produce well-formed answer files; spot-check 3 by hand
  against the policy docs
- **Demo rehearsal** — full Streamlit flow **with Savanna already warm**

## Risks

| Risk | Mitigation |
|---|---|
| **Answer format guessed wrong** — graded deliverable | Read dataset README first; its format is authoritative over this plan |
| **8 GB RAM during ETL** | `usecols` to drop V1–V339, downcast dtypes, chunked reads |
| **Savanna cold start mid-demo** (~4 min + warm-up) | Wake the workspace before recording; never record cold |
| **MCP ~29k token context blowup** | `TG_ALLOWED_TOOLS` from day one |
| **`INSTALL QUERY` latency** | Pre-install in setup; prefer `CALL GDBMS_ALGO.*` templates |
| **Gemini rate limits** across 20 cases × many calls | Cache aggressively, Flash for sub-steps, run the benchmark early not at the deadline |
| Savanna is free *credits*, not a free instance | Credits last ~1 year, no card needed — but don't leave the workspace running idle |

## Note on prior art

Public repos from this same hackathon exist and converge on a similar schema (it is the
obvious modeling of IEEE-CIS). The schema above was derived independently from the column
structure. **Do not copy competitor code** — innovation is 15% of the score.
`github.com/tigergraph/ecosys` (official GSQL + VectorSearch tutorials) is the safe
reference.
