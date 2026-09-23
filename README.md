# Agentic Fraud Investigation Agent

Built for the TigerGraph "Agentic Fraud Investigation" hackathon (Hacker House Goa 2026).
An AI agent that investigates flagged card transactions, decides what a bank should do
about them, and revises that decision as new evidence comes in — grounded in a real
transaction graph and a written fraud policy, not just an LLM's own judgment.

## What it does

Given a trigger (a risk-scored transaction, a customer complaint, or an analyst request),
the agent:

1. Pulls the transaction's recent card activity, the cardholder's baseline behavior, and
   whether the device used shows up on any other cards — from a live graph, not a lookup
   table.
2. Checks whether this looks like one of five known fraud patterns, an undocumented one, or
   nothing at all, using the bank's actual written policy (chunked and embedded) as
   grounding rather than the model's own assumptions about what a bank should do.
3. Assesses a probability and decides whether it has enough to act. If not, it asks a
   question (customer validation, step-up auth, analyst input) and re-assesses once that
   answer is in.
4. Recommends one or more actions with an approval route (`auto` / `L1` team lead / `L2`
   fraud manager), citing the specific policy rule behind each one.
5. Writes the case back into the graph, so the next investigation can find it — that's the
   agent's memory.

## Why a graph

Fraud signals are relational: the same device on two different cards, a billing region a
customer has never used, a transaction pattern that matches (or breaks) a prior confirmed
case. A spreadsheet answers "what happened on this card." A graph answers "who else touched
this device, and did any of them turn out to be fraud" — that traversal is what the
2-hop `fraud_ring_component` query and the `device_shared_accounts` query actually do, live,
against [TigerGraph](https://www.tigergraph.com/) Savanna.

**Case memory and policy grounding both live in the same database as the graph**, as native
vector attributes (`ClosedCase.emb`, `InvestigationCase.emb`, `DocChunk.emb`) — not a
separate vector store bolted on the side. "Have we seen this before?" is one `vectorSearch`
call, not a second system to keep in sync.

## Architecture

```
Trigger (risk score / customer report / analyst request)
        │
        ▼
 gather evidence ──────► TigerGraph MCP ──────► TigerGraph Savanna
        │                (7 allow-listed tools)   graph + native vectors
        ▼
   assess (Gemini,                 similar closed cases  ◄─┐
   structured output)              policy/pattern text   ◄─┤ vectorSearch
        │                                                   │
        ▼                                          ClosedCase.emb, DocChunk.emb
 enough evidence? ──no──► request evidence (simulated,
        │yes                grounded in retrieved outcomes)
        ▼                          │
 decide action                     │
 (policy rules R1-R10,             ▼
  coded, not prompted)      re-assess ──► decide again
        │
        ▼
  write case to graph + emit the graded answer JSON
```

The investigation loop's state machine and its decision logic were built and validated
first against a mock graph (`src/agent/graph.py`, `python -m src.agent.graph`) — that's what
proves the *mechanism* (evidence-gathering loop, revised recommendation, round cap) works
independent of any one day's API quota. The actual graded run
(`src/eval/run_cases.py`) reuses the same decision logic and state model against the real
graph, real MCP, and real Gemini.

## Repository layout

```
schema/
  01_schema.gsql          vertices, edges (Customer, Card, Transaction, DeviceProfile,
                           EmailDomain, BillingRegion, ClosedCase, InvestigationCase, DocChunk)
  02_vector_attrs.gsql    native vector attributes for case memory + policy retrieval
  03_loading_jobs.gsql    bulk CSV loading
  queries/                6 installed GSQL queries = the agent's graph-native tool surface
src/
  prep/etl.py             raw CSVs → loadable derived CSVs (card-id reconciliation, memory-
                           constrained column selection)
  tg/                     TigerGraph connection + loader
  rag/                    policy/pattern text chunking, embedding, case-memory embedding
  agent/                  state model, decision rules, mock demo graph, real MCP toolbox,
                           LLM interface
  eval/run_cases.py       the actual benchmark runner — produces cases/*.json
app/streamlit_app.py      analyst dashboard over the answer files
cases/                    the 20 graded answer files
PLAN.md                   design rationale and architectural decisions
EXECUTION.md              live build log — what was tried, what broke, what fixed it
```

`PLAN.md` and `EXECUTION.md` are kept as working documents, not polish — they're the
honest record of every real constraint hit while building this (a laptop with 8GB RAM, a
pyTigerGraph auth bug on Savanna, GSQL's `SPLIT()` not fanning out into edges the way it
does for attributes, and free-tier LLM quotas that forced two model swaps mid-build) and
how each was actually resolved, not glossed over.

## Running it

Requires a `.env` with `TG_HOST`, `TG_SECRET`, `TG_GRAPHNAME`, `GOOGLE_API_KEY` (see
`PLAN.md`/`EXECUTION.md` for how these were obtained).

```bash
pip install -r requirements.txt

# One-time setup against a fresh TigerGraph Savanna workspace:
python -c "from src.tg.connection import get_connection as c; print(c().gsql(open('schema/01_schema.gsql').read()))"
python -c "from src.tg.connection import get_connection as c; print(c().gsql(open('schema/02_vector_attrs.gsql').read()))"
python -m src.prep.etl
python -c "from src.tg.connection import get_connection as c; print(c().gsql(open('schema/03_loading_jobs.gsql').read()))"
python -m src.tg.load
# install each schema/queries/*.gsql the same way, then:
python -m src.rag.load_policy_chunks
python -m src.rag.embed_closed_cases

# Run the benchmark (produces cases/*.json):
python -m src.eval.run_cases

# View the results:
streamlit run app/streamlit_app.py
```

## What TigerGraph MCP is used for

The agent never queries TigerGraph directly — every graph access goes through
[TigerGraph MCP](https://github.com/tigergraph/tigergraph-mcp) over a single held stdio
session (`src/agent/mcp_tools.py`), scoped down via `TG_ALLOWED_TOOLS` to 7 tools
(`run_installed_query`, `get_node`, `get_node_edges`, `get_neighbors`, `get_vertex_count`,
`get_edge_count`, `search_top_k_similarity`) rather than the full tool set, which the
server's own docs note can exceed ~29k tokens on its own. Every domain-specific need —
transaction windows, device sharing, ring detection, case-memory retrieval, policy
retrieval — goes through `run_installed_query` against the 6 GSQL queries pre-installed in
`schema/queries/`.

## What's not done

- The external regulatory references (FinCEN/FATF/FFIEC/OFAC) the README lists as optional
  reading are not downloaded/chunked — only the bank's own Fraud Policy and the 5 documented
  patterns are in the vector store. Noted as a scope limitation, not silently dropped.
- Graph algorithms (`CALL GDBMS_ALGO.*` for louvain/k-core/pagerank) were not exercised;
  the 2-hop device-based traversal in `fraud_ring_component` covers the minimum viable ring
  signal within the time available.
- `google-genai` (the current, non-deprecated Gemini SDK) couldn't list models against the
  API surface available during this build; `google.generativeai` (deprecated but working)
  is used throughout instead.
