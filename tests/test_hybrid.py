from pathlib import Path
import pytest
from nxopen_mcp_enhanced.indexer.build import build_index, load_vec_extension
from nxopen_mcp_enhanced.retrieval.hybrid import HybridSearcher, extract_camel_tokens, rrf_fuse
from nxopen_mcp_enhanced.retrieval.store import Store
from tests.fakes import FakeEmbedder

FIXTURE = Path(__file__).parent / "fixtures" / "sample_doc.xml"


def test_extract_camel_tokens():
    toks = extract_camel_tokens("CavityMillingBuilder 的切削深度怎麼設定 top k")
    assert toks == ["CavityMillingBuilder"]


def test_rrf_fuse_rewards_agreement():
    # id=1 在兩個排名都名列前茅,應勝過只在單一排名居首的 id=9
    fused = rrf_fuse([[1, 2, 3], [9, 1, 2]])
    assert fused[0] == 1


@pytest.fixture
def searcher(tmp_path):
    db = tmp_path / "index.db"
    emb = FakeEmbedder()
    build_index([FIXTURE], db, emb, on_progress=lambda _: None)
    store = Store(db)
    load_vec_extension(store.conn)
    return HybridSearcher(store, emb)


def test_exact_channel_finds_named_class(searcher):
    results = searcher.search("CavityMillingBuilder 怎麼用")
    assert results[0]["full_name"].endswith("CavityMillingBuilder")


def test_namespace_filter(searcher):
    results = searcher.search("builder", namespace="NXOpen.NoSuch")
    assert results == []


def test_exact_search_matches_whole_single_word(searcher):
    """exact_search is the offline path; it must accept names that contain no
    CamelCase boundary (Tag, Part, Session)."""
    mid = searcher.store.conn.execute(
        "SELECT id FROM members WHERE name = 'CavityMillingBuilder'").fetchone()["id"]
    searcher.store.conn.execute(
        "UPDATE members SET name = 'Builder' WHERE id = ?", [mid])
    searcher.store.conn.commit()
    results = searcher.exact_search("Builder")
    assert results and results[0]["name"] == "Builder"


def test_rerank_failure_logs_to_stderr(searcher, monkeypatch, capsys):
    monkeypatch.setenv("NXOPEN_MCP_RERANK", "1")
    monkeypatch.setenv("NXOPEN_MCP_RERANK_URL",
                       "http://127.0.0.1:9/v1/rerank")
    reranking = HybridSearcher(searcher.store, searcher.embedder)
    reranking.search("builder")
    captured = capsys.readouterr()
    assert captured.out == ""          # stdout stays JSON-RPC only
    assert "[rerank]" in captured.err
