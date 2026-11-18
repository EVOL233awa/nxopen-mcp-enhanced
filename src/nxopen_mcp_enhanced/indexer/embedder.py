"""Embedding: chunk text composition + BGE-M3 (dense + sparse) wrapper."""
from __future__ import annotations

import threading
from typing import Protocol

import numpy as np

from nxopen_mcp_enhanced.indexer.parser import MemberRecord

_KIND_LABEL = {"T": "class", "P": "property", "M": "method",
               "F": "field", "E": "event"}


def record_to_text(r: MemberRecord) -> str:
    """One member = one chunk. API docs are naturally structured."""
    parts = [r.full_name, _KIND_LABEL.get(r.kind, r.kind), r.summary]
    for pname, pdesc in r.params:
        parts.append(f"{pname}: {pdesc}")
    if r.returns:
        parts.append(f"returns: {r.returns}")
    return " | ".join(p for p in parts if p)


class Embedder(Protocol):
    dim: int

    def encode(self, texts: list[str]) -> tuple[np.ndarray, list[dict[str, float]]]:
        """Return (L2-normalized dense matrix (n, dim), per-text sparse weights)."""
        ...



class OllamaEmbedder:
    """Dense-only BGE-M3 embeddings via a local Ollama server (no torch).

    nxopen-mcp-enhanced's default search channels are dense + exact, so the sparse
    lexical weights (not exposed by Ollama) are returned empty.
    """

    dim = 1024

    def __init__(self, url: str = "http://127.0.0.1:11434",
                 model: str = "bge-m3", batch_size: int = 32,
                 max_chars: int = 4000, timeout: float = 60.0) -> None:
        import urllib.request
        self._url = url.rstrip("/")
        self._model = model
        self._batch_size = batch_size
        self._max_chars = max_chars
        self._timeout = timeout
        self._opener = urllib.request.build_opener()
        self._opener.addheaders = [("Content-Type", "application/json")]

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        import json
        import urllib.error
        payload = json.dumps(
            {"model": self._model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            f"{self._url}/api/embed", data=payload, method="POST")
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"Ollama /api/embed failed ({exc.code}): {exc.read().decode('utf-8', 'replace')}") from exc
        emb = data.get("embeddings")
        if not emb or len(emb) != len(texts):
            raise RuntimeError(
                f"Ollama returned {len(emb or [])} embeddings for {len(texts)} inputs")
        return emb

    def encode(self, texts: list[str]) -> tuple[np.ndarray, list[dict[str, float]]]:
        clipped = [t[: self._max_chars] for t in texts]
        rows: list[list[float]] = []
        for i in range(0, len(clipped), self._batch_size):
            rows.extend(self._embed_batch(clipped[i:i + self._batch_size]))
        dense = np.asarray(rows, dtype=np.float32)
        norms = np.linalg.norm(dense, axis=1, keepdims=True)
        dense = dense / np.where(norms == 0, 1.0, norms)
        return dense, [{} for _ in texts]


class LlamaEmbedder:
    """Dense-only BGE-M3 embeddings via llama.cpp OpenAI-compatible API."""

    dim = 1024

    def __init__(self, url: str = "http://127.0.0.1:11436",
                 model: str = "bge-m3", batch_size: int = 128,
                 max_chars: int = 4000, timeout: float = 60.0,
                 api_key: str | None = None) -> None:
        import os
        import urllib.request
        self._url = url.rstrip("/")
        # Accept both a bare base URL and one that already ends in /v1.
        self._embeddings_url = (
            f"{self._url}/embeddings" if self._url.endswith("/v1")
            else f"{self._url}/v1/embeddings")
        self._model = model
        self._batch_size = batch_size
        self._max_chars = max_chars
        self._timeout = timeout
        self._opener = urllib.request.build_opener()
        headers = [("Content-Type", "application/json")]
        # A remote OpenAI-compatible provider (SiliconFlow, DashScope, ...)
        # needs a bearer token; a local llama-server ignores the header, so
        # the key is optional and only sent when one is configured.
        key = api_key if api_key is not None else os.environ.get(
            "NXOPEN_MCP_EMBED_API_KEY", "")
        if key:
            headers.append(("Authorization", f"Bearer {key}"))
        self._opener.addheaders = headers

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        import json
        import urllib.error
        payload = json.dumps(
            {"model": self._model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            self._embeddings_url, data=payload, method="POST")
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"embedding service /v1/embeddings failed ({exc.code}): "
                f"{exc.read().decode('utf-8', 'replace')}") from exc
        emb = [item.get("embedding") for item in data.get("data") or []]
        if not emb or len(emb) != len(texts):
            raise RuntimeError(
                f"embedding service returned {len(emb)} embeddings for "
                f"{len(texts)} inputs")
        return emb

    def encode(self, texts: list[str]) -> tuple[np.ndarray, list[dict[str, float]]]:
        clipped = [t[: self._max_chars] for t in texts]
        rows: list[list[float]] = []
        for i in range(0, len(clipped), self._batch_size):
            rows.extend(self._embed_batch(clipped[i:i + self._batch_size]))
        dense = np.asarray(rows, dtype=np.float32)
        norms = np.linalg.norm(dense, axis=1, keepdims=True)
        dense = dense / np.where(norms == 0, 1.0, norms)
        return dense, [{} for _ in texts]


class LazyEmbedder:
    """Defers constructing the real embedder until the first encode().

    `serve` must answer the MCP initialize handshake within the client's
    startup timeout (~30s); loading BGE-M3 takes minutes on CPU. Exact
    lookups (get_class / get_member) never touch the model at all.
    """

    dim = 1024

    def __init__(self, factory) -> None:
        self._factory = factory
        self._real: Embedder | None = None
        self._lock = threading.Lock()
        # Tool calls now run in worker threads; the local BGE-M3 model is not
        # safe to encode from several threads at once.
        self._encode_lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._real is None:
                self._real = self._factory()

    def start_preload(self) -> None:
        """Warm the model in a background thread (serve --preload):
        the MCP handshake still answers instantly, but by the time the
        first semantic query arrives the model is usually ready."""
        threading.Thread(target=self._ensure_loaded, daemon=True).start()

    def encode(self, texts: list[str]) -> tuple[np.ndarray, list[dict[str, float]]]:
        self._ensure_loaded()
        with self._encode_lock:
            return self._real.encode(texts)


class BGEM3Embedder:
    """Real embedder. Heavy import is deferred so CI never touches it."""

    dim = 1024

    def __init__(self) -> None:
        from FlagEmbedding import BGEM3FlagModel  # lazy: pulls torch
        import torch  # noqa: PLC0415 鈥?decide fp16 by device
        # fp16 is a big win on CUDA but *slower* than fp32 on CPU
        # (no hardware fp16 path), so enable it only when a GPU is used.
        self._model = BGEM3FlagModel(
            "BAAI/bge-m3", use_fp16=torch.cuda.is_available())

    def encode(self, texts: list[str]) -> tuple[np.ndarray, list[dict[str, float]]]:
        # max_length=1024 (default 8192): API-doc chunks rarely carry useful
        # signal past 1k tokens, and CPU attention cost grows quadratically 鈥?
        # a few giant NXOpen.UF entries would otherwise stall a whole batch.
        out = self._model.encode(
            texts, return_dense=True, return_sparse=True,
            batch_size=32, max_length=1024)
        dense = np.asarray(out["dense_vecs"], dtype=np.float32)
        norms = np.linalg.norm(dense, axis=1, keepdims=True)
        dense = dense / np.where(norms == 0, 1.0, norms)
        sparse = [
            {tok: float(w) for tok, w in d.items()}
            for d in out["lexical_weights"]
        ]
        return dense, sparse
