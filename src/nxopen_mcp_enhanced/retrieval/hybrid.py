"""Hybrid retrieval: dense + sparse + exact-name channels fused with RRF."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from collections import defaultdict

from nxopen_mcp_enhanced.indexer.embedder import Embedder
from nxopen_mcp_enhanced.retrieval.store import Store

_CAMEL_RE = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+\b")
_CANDIDATES = 50


def extract_camel_tokens(query: str) -> list[str]:
    return _CAMEL_RE.findall(query)


def rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[int]:
    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, mid in enumerate(ranking):
            scores[mid] += 1.0 / (k + rank + 1)
    return sorted(scores, key=scores.__getitem__, reverse=True)


class EmbeddingUnavailableError(RuntimeError):
    """The semantic channel could not reach its embedding service.

    Raised only from the embedder call so the tool layer can fall back to
    exact-name matches without swallowing unrelated failures.
    """


class HybridSearcher:
    def __init__(self, store: Store, embedder: Embedder):
        self.store = store
        self.embedder = embedder
        self.rerank_url: str | None = None
        if os.environ.get("NXOPEN_MCP_RERANK", "").lower() in ("1", "true", "on"):
            self.rerank_url = os.environ.get(
                "NXOPEN_MCP_RERANK_URL", "http://127.0.0.1:8000/v1/rerank")

    def _dense(self, qvec) -> list[int]:
        from nxopen_mcp_enhanced.indexer.build import serialize_f32
        rows = self.store.conn.execute(
            "SELECT member_id FROM dense_vec WHERE embedding MATCH ? "
            "ORDER BY distance LIMIT ?",
            [serialize_f32(qvec), _CANDIDATES]).fetchall()
        return [r["member_id"] for r in rows]

    def _sparse(self, qweights: dict[str, float]) -> list[int]:
        scores: dict[int, float] = defaultdict(float)
        for tok, qw in qweights.items():
            for r in self.store.conn.execute(
                    "SELECT member_id, weight FROM sparse_postings WHERE token = ?",
                    [tok]):
                scores[r["member_id"]] += qw * r["weight"]
        ranked = sorted(scores, key=scores.__getitem__, reverse=True)
        return ranked[:_CANDIDATES]

    def _exact(self, query: str) -> list[int]:
        ids: list[int] = []
        for tok in extract_camel_tokens(query):
            ids.extend(self.store.exact_name_matches(tok))
        return ids

    def exact_search(self, query: str, top_k: int = 10,
                     namespace: str | None = None) -> list[dict]:
        """Offline fallback: the whole query as a literal name first, then
        CamelCase tokens found inside it. The whole-name step is what makes
        single-word names (Part, Session, Tag) and fully-qualified names work
        without an embedding service."""
        ids: list[int] = []
        whole = query.strip()
        for mid in self.store.exact_query_matches(whole):
            if mid not in ids:
                ids.append(mid)
        for tok in extract_camel_tokens(query):
            for mid in self.store.exact_name_matches(tok):
                if mid not in ids:
                    ids.append(mid)
        results = self.store.get_members_by_ids(ids)
        if namespace:
            results = [r for r in results if r["namespace"].startswith(namespace)]
        return results[:top_k]

    def _skip_rerank(self, query: str) -> bool:
        """Only a unique exact name skips reranking. Ambiguous short names keep
        it: their top-5 changes completely under reranking and there is no
        evidence that skipping is better."""
        return self.store.unique_name_exists(query.strip())

    def _rerank(self, query: str, members: list[dict]) -> list[dict]:
        """Optional rerank of semantic candidates via an OpenAI-compatible
        rerank endpoint (POST /v1/rerank). Falls back to input order on any
        error so retrieval still works without the service."""
        if len(members) < 2:
            return members
        # Only the head can realistically reach the caller's top_k; reranking
        # the full candidate list costs 3x latency at no measured gain.
        cand, tail = members[:20], members[20:]
        docs = [f"{m['full_name']}: {m.get('summary', '')}"[:400] for m in cand]
        body = {"query": query, "documents": docs, "top_n": len(docs)}
        rerank_model = os.environ.get("NXOPEN_MCP_RERANK_MODEL", "")
        if rerank_model:
            body["model"] = rerank_model
        payload = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        key = os.environ.get("NXOPEN_MCP_RERANK_API_KEY", "")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(
            self.rerank_url, data=payload, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            print(f"[rerank] service unavailable, skipping: {exc}",
                  file=sys.stderr)
            return members
        results = data.get("results") or []
        order = [r["index"] for r in sorted(
            results, key=lambda r: r["relevance_score"], reverse=True)]
        by_idx = {i: m for i, m in enumerate(cand)}
        ranked = [by_idx[i] for i in order if i in by_idx]
        if not ranked:
            return members
        # Never drop candidates: items the reranker threshold excluded keep
        # their original relative order after the ranked ones.
        seen = {id(m) for m in ranked}
        rest = [m for m in cand if id(m) not in seen] + tail
        return ranked + rest

    # Default channels chosen by evaluation on a 33-query golden set:
    # BGE-M3's sparse channel *lowered* Recall@5 from 69.7% to 54.5% when
    # RRF-fused with dense on this corpus (at any fusion weight), so the
    # default is dense + exact; sparse remains available via `channels`.
    DEFAULT_CHANNELS = frozenset({"dense", "exact"})

    def search(self, query: str, top_k: int = 10,
               namespace: str | None = None,
               channels: set[str] = DEFAULT_CHANNELS,
               ) -> list[dict]:
        exact = self._exact(query) if "exact" in channels else []
        rankings: list[list[int]] = []
        if channels & {"dense", "sparse"}:
            try:
                dense_q, sparse_q = self.embedder.encode([query])
            except Exception as exc:
                raise EmbeddingUnavailableError(str(exc)) from exc
            if "dense" in channels:
                rankings.append(self._dense(dense_q[0]))
            if "sparse" in channels:
                rankings.append(self._sparse(sparse_q[0]))
        fused_rest = rrf_fuse(rankings)
        rest_members = self.store.get_members_by_ids(fused_rest)
        if (self.rerank_url and rest_members
                and not self._skip_rerank(query)):
            rest_members = self._rerank(query, rest_members)
        rest_ids = [m["id"] for m in rest_members]
        # Exact-name matches are precise (user typed a literal class/member
        # name), so they're surfaced ahead of similarity-only channels
        # rather than merely contributing one vote to the RRF sum.
        seen: set[int] = set()
        fused: list[int] = []
        for mid in [*exact, *rest_ids]:
            if mid not in seen:
                seen.add(mid)
                fused.append(mid)
        results = self.store.get_members_by_ids(fused)
        if namespace:
            results = [r for r in results if r["namespace"].startswith(namespace)]
        return results[:top_k]
