"""Real evidence-gathering tools backed by TigerGraph MCP, replacing the mock
scenarios in tools.py with live calls against the actual Savanna graph.

Holds ONE MCP session for the life of an `McpToolbox` instance rather than
opening a new stdio subprocess per call — `client.get_tools()` (no session)
opens and closes a connection every time and is dramatically slower over
more than a couple of calls, per PLAN.md and the TigerGraph MCP README.

`TG_ALLOWED_TOOLS` in `.env` scopes the server down to 7 tools
(run_installed_query, get_node, get_node_edges, get_neighbors,
get_vertex_count, get_edge_count, search_top_k_similarity) — the full tool
set is documented to exceed ~29k tokens, which would blow out the agent's
context for no benefit since every domain-specific need goes through
run_installed_query against our pre-installed GSQL queries anyway.

MCP tool results come back as a list of content blocks whose `text` is a
markdown-wrapped JSON blob (```json ... ``` followed by a human-readable
echo) — `_parse_mcp_result` extracts just the JSON object.
"""

from __future__ import annotations

import json
import re
from contextlib import AsyncExitStack
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _parse_mcp_result(result: Any) -> dict:
    """MCP tool results are a list of content blocks; take the first text
    block's fenced ```json``` object rather than the trailing prose echo."""
    if isinstance(result, list) and result:
        text = result[0].get("text", "") if isinstance(result[0], dict) else str(result[0])
    else:
        text = str(result)
    m = _JSON_BLOCK.search(text)
    if not m:
        raise ValueError(f"No JSON block found in MCP result: {text[:300]}")
    return json.loads(m.group(1))


class McpToolbox:
    """Async context manager holding one TigerGraph MCP session.

    Usage:
        async with McpToolbox() as tb:
            evidence = await tb.card_transaction_window("C09933-K2")
    """

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._tools_by_name: dict[str, Any] = {}

    async def __aenter__(self) -> "McpToolbox":
        client = MultiServerMCPClient({
            "tigergraph": {"transport": "stdio", "command": "tigergraph-mcp", "args": []}
        })
        session = await self._stack.enter_async_context(client.session("tigergraph"))
        tools = await load_mcp_tools(session)
        self._tools_by_name = {t.name: t for t in tools}
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._stack.aclose()

    async def _call(self, tool_name: str, **kwargs) -> dict:
        tool = self._tools_by_name[f"tigergraph__{tool_name}"]
        raw = await tool.ainvoke(kwargs)
        parsed = _parse_mcp_result(raw)
        if not parsed.get("success", True):
            raise RuntimeError(f"{tool_name} failed: {parsed}")
        return parsed.get("data", parsed)

    async def _run_query(self, query_name: str, params: dict) -> Any:
        data = await self._call("run_installed_query", query_name=query_name, params=params)
        return data.get("result", data)

    # ---- evidence tools, same shape/intent as tools.py's mock versions ------

    async def card_transaction_window(self, card_id: str, limit_n: int = 20) -> dict:
        result = await self._run_query("card_transaction_window", {"card_id": card_id, "limit_n": limit_n})
        txns = result[0].get("Txns", []) if result else []
        return {"card_id": card_id, "transactions": txns}

    async def customer_profile(self, customer_id: str) -> dict:
        result = await self._run_query("customer_profile", {"customer_id": customer_id})
        return result[0] if result else {}

    async def device_shared_accounts(self, device_id: str) -> dict:
        result = await self._run_query("device_shared_accounts", {"device_id": device_id})
        return result[0] if result else {}

    async def fraud_ring_component(self, seed_txn_id: str) -> dict:
        result = await self._run_query("fraud_ring_component", {"seed_txn_id": seed_txn_id})
        return result[0] if result else {}

    async def similar_closed_cases(self, query_vector: list[float], k: int = 3) -> dict:
        result = await self._run_query("similar_closed_cases", {"query_vector": query_vector, "k": k})
        return result[0] if result else {}

    async def policy_search(self, query_vector: list[float], k: int = 5) -> dict:
        result = await self._run_query("policy_search", {"query_vector": query_vector, "k": k})
        return result[0] if result else {}

    async def hub_score(self, vertex_type: str, vertex_id: str) -> float:
        """Reads the precomputed PageRank centrality score (schema/queries/
        pagerank_hub_score.gsql) for a Card or DeviceProfile -- a real, global
        graph algorithm's output, not a per-call traversal. High relative to
        peers = structurally central in the card<->device network, which is
        what a fraud ring producing many-cards-through-one-device looks like."""
        data = await self._call("get_node", vertex_type=vertex_type, vertex_id=vertex_id)
        return float(data.get("attributes", {}).get("hub_score", 0.0))
