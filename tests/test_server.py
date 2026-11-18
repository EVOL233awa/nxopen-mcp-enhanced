import asyncio
import time
from pathlib import Path

import pytest

from nxopen_mcp_enhanced.indexer.build import build_index, load_vec_extension
from nxopen_mcp_enhanced.indexer.parser import MemberRecord
from nxopen_mcp_enhanced.retrieval.hybrid import HybridSearcher
from nxopen_mcp_enhanced.retrieval.store import Store
from nxopen_mcp_enhanced.server import create_server, format_member
from tests.fakes import FakeEmbedder

FIXTURE = Path(__file__).parent / "fixtures" / "sample_doc.xml"


def test_literal_none_license_is_hidden():
    out = format_member({"full_name": "NXOpen.X", "kind": "T",
                         "summary": "", "license": "None"})
    assert "license" not in out


def _tool_map(store, searcher):
    server = create_server(store, searcher)
    return {t.name: t.fn for t in server._tool_manager.list_tools()}


def _call(tools, name, **kwargs):
    return asyncio.run(tools[name](**kwargs))


@pytest.fixture
def tools(tmp_path):
    db = tmp_path / "index.db"
    emb = FakeEmbedder()
    build_index([FIXTURE], db, emb, on_progress=lambda _: None)
    store = Store(db)
    load_vec_extension(store.conn)
    store.insert_members([MemberRecord(
        full_name="NXOpen.Tag", kind="T", namespace="NXOpen",
        parent_type=None, name="Tag",
        summary="A tag used to identify an object within NX.")])
    return _tool_map(store, HybridSearcher(store, emb))


def test_registers_exactly_four_tools(tools):
    assert set(tools) == {"search_api", "get_class", "get_member", "find_builder"}
    # 同步工具会被 FastMCP 直接跑在事件循环里，必须全部是协程。
    assert all(asyncio.iscoroutinefunction(fn) for fn in tools.values())


def test_search_api_returns_markdown(tools):
    out = _call(tools, "search_api", query="CavityMillingBuilder")
    assert "NXOpen.CAM.CavityMillingBuilder" in out


def test_get_class_includes_members_and_inheritance_note(tools):
    out = _call(tools, "get_class", class_name="CavityMillingBuilder")
    assert "BlankGeometry" in out


def test_get_member_shows_license(tools):
    out = _call(tools, "get_member",
                member_name="OperationCollection.CreateCavityMillingBuilder")
    assert 'cam_base ("CAM BASE")' in out


def test_find_builder_shows_creator_and_skeleton(tools):
    out = _call(tools, "find_builder", operation="cavity milling")
    assert "CreateCavityMillingBuilder" in out
    assert "Commit" in out  # Builder→Commit→Destroy 骨架


def test_get_class_not_found_is_friendly(tools):
    out = _call(tools, "get_class", class_name="NoSuchClass")
    assert "not found" in out.lower()


def test_empty_names_do_not_return_a_random_row(tools):
    assert "not found" in _call(tools, "get_member", member_name="").lower()
    assert "not found" in _call(tools, "get_class", class_name="").lower()


def test_top_k_below_one_is_rejected(tools):
    assert "top_k must be >= 1" in _call(tools, "search_api", query="extrude",
                                         top_k=0)


def test_offline_fallback_matches_single_word_name(tmp_path):
    """A bare class name has no CamelCase token, so only a whole-name lookup
    can serve it while the embedding service is down."""
    db = tmp_path / "index.db"
    emb = FakeEmbedder()
    build_index([FIXTURE], db, emb, on_progress=lambda _: None)
    store = Store(db)
    load_vec_extension(store.conn)
    store.insert_members([MemberRecord(
        full_name="NXOpen.Tag", kind="T", namespace="NXOpen",
        parent_type=None, name="Tag", summary="A tag.")])

    class DownEmbedder:
        dim = 8

        def encode(self, texts):
            raise RuntimeError("offline")

    tools = _tool_map(store, HybridSearcher(store, DownEmbedder()))
    out = _call(tools, "search_api", query="Tag")
    assert "exact-name matches only" in out
    assert "NXOpen.Tag" in out


def test_semantic_call_does_not_block_exact_lookup(tmp_path):
    db = tmp_path / "index.db"
    emb = FakeEmbedder()
    build_index([FIXTURE], db, emb, on_progress=lambda _: None)
    store = Store(db)
    load_vec_extension(store.conn)

    class SlowSearcher:
        def search(self, *args, **kwargs):
            time.sleep(0.4)
            return []

        def exact_search(self, *args, **kwargs):
            return []

    tools = _tool_map(store, SlowSearcher())

    async def main():
        slow = asyncio.create_task(tools["search_api"](query="anything"))
        await asyncio.sleep(0.05)
        start = time.monotonic()
        await tools["get_member"](member_name="CavityMillingBuilder")
        elapsed = time.monotonic() - start
        await slow
        return elapsed

    assert asyncio.run(main()) < 0.2
