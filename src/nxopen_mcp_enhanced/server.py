"""MCP server: 4 tools over the hybrid retrieval layer."""
from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP

from nxopen_mcp_enhanced.retrieval.hybrid import EmbeddingUnavailableError, HybridSearcher
from nxopen_mcp_enhanced.retrieval.store import Store

_KIND_LABEL = {"T": "class", "P": "property", "M": "method",
               "F": "field", "E": "event"}

_BUILDER_SKELETON = """\
Standard NXOpen builder workflow:
```csharp
var builder = collection.{creator}(camObject);
try {{
    // ... set builder properties ...
    var result = builder.Commit();
}} finally {{
    builder.Destroy();
}}
```"""


def format_member(m: dict) -> str:
    lines = [f"### {m['full_name']}",
             f"- kind: {_KIND_LABEL.get(m['kind'], m['kind'])}"]
    if m.get("summary"):
        lines.append(f"- summary: {m['summary']}")
    if m.get("signature"):
        lines.append(f"- parameters: ({m['signature']})")
    for pname, pdesc in m.get("params", []):
        lines.append(f"  - {pname}: {pdesc}")
    if m.get("returns"):
        lines.append(f"- returns: {m['returns']}")
    if m.get("version"):
        lines.append(f"- since: {m['version']}")
    lic = m.get("license")
    if lic and lic.strip().lower() != "none":  # XML writes literal "None"
        lines.append(f"- license: {lic}")
    return "\n".join(lines)


def _member_line(m: dict) -> str:
    sig = f"({m['signature']})" if m.get("signature") else ""
    return f"- [{_KIND_LABEL.get(m['kind'], m['kind'])}] {m['name']}{sig} — {m['summary']}"


def _search_or_exact(searcher: HybridSearcher, query: str,
                     **kwargs) -> tuple[list[dict], bool]:
    """Return (results, degraded). An unreachable embedding service falls back
    to exact-name matches; without any, the error propagates."""
    try:
        return searcher.search(query, **kwargs), False
    except EmbeddingUnavailableError:
        exact = searcher.exact_search(query, **kwargs)
        if exact:
            return exact, True
        raise


def create_server(store: Store, searcher: HybridSearcher) -> FastMCP:
    mcp = FastMCP("nxopen")

    # FastMCP calls synchronous tool bodies on the event loop, so one slow
    # embedding or rerank request would also stall get_class/get_member.
    # Each body runs in a worker thread; the store connection is opened with
    # check_same_thread=False for that reason.
    def _search_api(query: str, namespace: str | None, top_k: int) -> str:
        results, degraded = _search_or_exact(
            searcher, query, top_k=top_k, namespace=namespace)
        if not results:
            return "No matching API members found."
        out = "\n\n".join(format_member(m) for m in results)
        if degraded:
            out = ("Semantic search unavailable (embedding service unreachable); "
                   "showing exact-name matches only.\n\n" + out)
        return out

    @mcp.tool()
    async def search_api(query: str, namespace: str | None = None,
                         top_k: int = 10) -> str:
        """Semantic search over the real NXOpen .NET API. Use when you don't
        know the exact class or member name. Query may be English or Chinese."""
        if top_k < 1:
            return "top_k must be >= 1."
        return await asyncio.to_thread(_search_api, query, namespace, top_k)

    def _get_class(class_name: str, offset: int, limit: int) -> str:
        c = store.get_class(class_name)
        if not c:
            return f"Class '{class_name}' not found. Try search_api instead."
        if offset < 0 or limit < 1:
            return "offset must be >= 0 and limit must be >= 1."
        sections: list[tuple[str, dict]] = [
            ("## Members", m) for m in c["members"]]
        if c["ancestors"]:
            inherited = (f"\n## Inherited "
                         f"(from {' -> '.join(c['ancestors'])})")
            sections += [(inherited, m) for m in c["inherited_members"]]
        total = len(sections)
        out = [format_member(c["type"]), ""]
        if not total:
            out += ["## Members", "(none)"]
            return "\n".join(out)
        page = sections[offset:offset + limit]
        if not page:
            out.append(f"offset {offset} is past the end ({total} members).")
            return "\n".join(out)
        last_header = ""
        for header, m in page:
            if header != last_header:
                out.append(header)
                last_header = header
            out.append(_member_line(m))
        if total > offset + len(page):
            out.append(f"\n(showing {offset + 1}-{offset + len(page)} "
                       f"of {total}; pass offset={offset + len(page)} "
                       f"to continue)")
        elif offset:
            out.append(f"\n(showing {offset + 1}-{offset + len(page)} "
                       f"of {total})")
        return "\n".join(out)

    @mcp.tool()
    async def get_class(class_name: str, offset: int = 0,
                        limit: int = 200) -> str:
        """List members of an NXOpen class, including inherited members from
        its ancestor chain. Large classes are paginated: the footer shows the
        total and the next offset."""
        return await asyncio.to_thread(_get_class, class_name, offset, limit)

    def _get_member(member_name: str) -> str:
        m = store.get_member(member_name)
        if not m:
            return f"Member '{member_name}' not found. Try search_api instead."
        return format_member(m)

    @mcp.tool()
    async def get_member(member_name: str) -> str:
        """Get exact signature, parameters, return value, NX version and
        license requirement of a single NXOpen member."""
        return await asyncio.to_thread(_get_member, member_name)

    def _find_builder(operation: str) -> str:
        results, degraded = _search_or_exact(
            searcher, f"{operation} builder", top_k=20)
        builders = [m for m in results
                    if m["kind"] == "T" and m["name"].endswith("Builder")]
        if not builders:
            return f"No builder found for '{operation}'. Try search_api."
        out = []
        if degraded:
            out.append("Semantic search unavailable (embedding service "
                       "unreachable); showing exact-name matches only.\n")
        for b in builders[:3]:
            out.append(format_member(b))
            cref = b.get("creator_cref")
            if cref:
                pre_paren = cref.split("(")[0]
                # creator_cref is expected to be a dotted Type.Method
                # reference (e.g. "OperationCollection.CreateFooBuilder(...)");
                # guard against a dotless value so rsplit(".", 1)[1] can't
                # IndexError, and just skip the creator/skeleton lines.
                if "." in pre_paren:
                    creator = pre_paren.rsplit(".", 1)[1]
                    out.append(f"\nCreate via: `{cref}`")
                    out.append(_BUILDER_SKELETON.format(creator=creator))
            out.append("")
        return "\n".join(out)

    @mcp.tool()
    async def find_builder(operation: str) -> str:
        """Find the NXOpen Builder class for a CAM operation (e.g. 'cavity
        milling', 'hole drilling') and how to create/commit it."""
        return await asyncio.to_thread(_find_builder, operation)

    return mcp
