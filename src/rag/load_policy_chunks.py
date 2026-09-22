"""Embeds and upserts the curated policy/pattern DocChunks (src/rag/policy_docs.py)
into TigerGraph's DocChunk.emb — the GraphRAG grounding for policy_search.
"""

from __future__ import annotations

from src.rag.embed import embed_text
from src.rag.policy_docs import build_doc_chunks
from src.tg.connection import get_connection


def run() -> None:
    conn = get_connection()
    chunks = build_doc_chunks()
    print(f"Embedding and upserting {len(chunks)} policy/pattern chunks...")
    for c in chunks:
        vec = embed_text(c["text"], task_type="RETRIEVAL_DOCUMENT")
        conn.upsertVertex("DocChunk", c["chunk_id"], attributes={
            "doc_name": c["doc_name"], "doc_type": c["doc_type"],
            "section": c["section"], "text": c["text"], "ordinal": c["ordinal"],
            "emb": vec,
        })
        print(f"  {c['chunk_id']}")
    print("Done.")


if __name__ == "__main__":
    run()
