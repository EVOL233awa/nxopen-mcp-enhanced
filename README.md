# nxopen-mcp-enhanced

**English** | [简体中文](README.zh-CN.md)

> **Our enhanced fork** of [mingfeng6684/nxopen-mcp](https://github.com/mingfeng6684/nxopen-mcp)
> and the MCP component of
> [nxopen-journal-toolkit](https://github.com/EVOL233awa/nxopen-journal-toolkit).
> Not related to `NX_MCP-Enhanced` (a separate NX 2506 session-automation project).

This fork can be installed **standalone** (API retrieval only), but it is **recommended to install it
together with the [`nxopen-journal`](https://github.com/EVOL233awa/nxopen-journal) skill**: the MCP
supplies the real NXOpen API facts, the skill supplies the NX 12 journal recipes, batch runner and
verification gates. `nxopen-journal-toolkit` installs both and checks them together.

### Changes vs. upstream

| Area | Upstream `nxopen-mcp` 0.2.0 | This fork |
|---|---|---|
| Package / module / command | `nxopen-mcp` / `nxopen_mcp` / `nxopen-mcp` | `nxopen-mcp-enhanced` / `nxopen_mcp_enhanced` / `nxopen-mcp-enhanced` |
| Default data dir | `~/.nxopen-mcp/` | `~/.nxopen-mcp-enhanced/` (coexists with upstream) |
| Embeddings | Local BGE-M3 in-process | Local BGE-M3 **or** OpenAI-compatible remote embedding |
| Reranking | None | Optional `/v1/rerank` (bge-reranker-v2-m3), 15 s timeout, skipped for unique names |
| Offline behavior | Fails when the embedding service is down | Whole-name and CamelCase-token local exact fallback, notice on first line |
| `get_class` | Full member list | Paginated `offset`/`limit` (default 200, footer shows total and next offset) |
| Concurrency | Synchronous tool handlers | Async handlers (`asyncio.to_thread`); `get_class`/`get_member` answer while a slow search runs |
| NX 12 XML discovery | `UGII/managed` | also `NXBIN/managed` and install root |

The local BGE-M3 retrieval path is unchanged; all additions are opt-in or backwards-compatible.

MCP server that gives AI coding agents (Claude Code, Codex, Cursor)
accurate knowledge of the Siemens NXOpen .NET API — eliminating
hallucinated API calls via hybrid retrieval over your own NX installation's
official documentation.

## Why

LLMs hallucinate NXOpen APIs: it's a niche domain (Siemens NX CAM/CAD
automation) with sparse public training data, so models confidently invent
classes, methods, and parameters that don't exist. This server grounds
agents in the real docs instead of guesses:

- **Semantic search** (BGE-M3 dense + sparse embeddings) so natural-language
  queries in English or 中文 find the right API even without exact names.
- **Exact-name channel**: a literal CamelCase name in your query (e.g.
  `CavityMillingBuilder`) is looked up directly and pinned to the top
  (types first) — never left to approximate matching.
- **RRF fusion** available to combine channels — though evaluation made
  dense + exact the default (see [Evaluation](#evaluation)).

By default everything runs locally and offline against an index built from your own
licensed NX installation — no Siemens files are bundled or sent anywhere. Remote
embedding/reranking is opt-in; when enabled, only query and document text is sent
to the provider you configure.

## Quick start

Requires **Python 3.11+**.

```bash
# 1. Install from this repository (not on PyPI yet)
git clone https://github.com/EVOL233awa/nxopen-mcp-enhanced
cd nxopen-mcp-enhanced
# local embeddings: downloads ~2 GB BGE-M3 on first use
pip install -e ".[embed,reflect]"
# remote embeddings instead: pip install -e ".[reflect]" and set NXOPEN_MCP_* (see below)

# 2. Build the index from YOUR NX installation (one-time — see time note below)
nxopen-mcp-enhanced index --nx-path "D:\Siemens\NX12.0"

# 3. Register with Claude Code (user scope: available in every project)
claude mcp add -s user nxopen -- nxopen-mcp-enhanced serve

# 4. Ask Claude Code to write NXOpen code — it now queries real APIs.
```

If you use `nxopen-journal-toolkit`, `nxjt install` performs steps 1 and 3 for you and
`nxjt index` performs step 2; the manual commands above are the standalone path.

`index` looks for `NXOpen*.xml` doc files under `<nx-path>\UGII\managed`, then
`<nx-path>\NXBIN\managed`, then `<nx-path>` itself, and for `NXOpen*.dll`
assemblies in the same folders.

Extras: `[embed]` pulls in `FlagEmbedding` (downloads the ~2GB BGE-M3
model on first use) — required for indexing and semantic search.
`[reflect]` pulls in `pythonnet` so `get_class` can show inherited
members; skip it and indexing still works, just without inheritance
chains.

**How long does indexing take?** Honest numbers: a full NX 12 doc set is
~100k members; on an 8-core laptop CPU that's **several hours** of
embedding (memory-bandwidth-bound — `--workers N` helps mainly on
machines with more memory channels; a CUDA GPU helps a lot). Plan to run
it overnight, or copy a teammate's index (see
[Sharing a pre-built index](#sharing-a-pre-built-index)).

**First semantic query is slow by design.** `serve` starts instantly, and
`get_class` / `get_member` respond immediately, but the first
`search_api` / `find_builder` call loads the BGE-M3 model (~1–2 min).
After that, semantic queries take seconds. If your MCP client shows the
first search "hanging", it's the one-time model load — let it finish.

By default the index is written to `~/.nxopen-mcp-enhanced/index.db`; override with
`--db <path>` on both `index` and `serve`.

## Remote embedding and reranking (optional)

The default local BGE-M3 path needs no configuration. To use an OpenAI-compatible
service instead (no `[embed]` extra, no 2 GB download), set these before `index`
and `serve`:

| Variable | Example |
|---|---|
| `NXOPEN_MCP_EMBEDDER` | `remote` |
| `NXOPEN_MCP_EMBED_URL` | `https://api.siliconflow.cn` |
| `NXOPEN_MCP_EMBED_MODEL` | `BAAI/bge-m3` |
| `NXOPEN_MCP_EMBED_API_KEY` | your bearer token |
| `NXOPEN_MCP_RERANK` | `1` to enable reranking |
| `NXOPEN_MCP_RERANK_URL` | `https://api.siliconflow.cn/v1/rerank` |
| `NXOPEN_MCP_RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` |
| `NXOPEN_MCP_RERANK_API_KEY` | your bearer token |

Behavior:
- Reranking only reorders the first 20 candidates; it has a 15 s timeout and falls
  back to the unranked order on any error.
- Unique exact names (`ExtrudeBuilder`) skip reranking; ambiguous short names
  (`Tag`, `Validate`) and natural-language queries keep it.
- If the embedding service is unreachable, the whole query is tried as a literal
  name (`Part`, `Session`, `NXOpen.Features.ExtrudeBuilder`) and CamelCase tokens
  inside it fall back to local exact matches, with a notice on the first line;
  other queries fail. `get_class` / `get_member` never wait on the embedding
  service and answer while a slow semantic call is in flight.

If `nxopen-mcp-enhanced` isn't on your PATH (e.g. installed into a venv), use the
full path to the executable (Windows: `<venv>\Scripts\nxopen-mcp-enhanced.exe`)
in the commands and configs below.

### `.mcp.json` (Claude Code / other MCP-aware clients)

```json
{
  "mcpServers": {
    "nxopen": {
      "command": "nxopen-mcp-enhanced",
      "args": ["serve"]
    }
  }
}
```

If you built the index at a non-default path, pass it explicitly:

```json
{
  "mcpServers": {
    "nxopen": {
      "command": "nxopen-mcp-enhanced",
      "args": ["serve", "--db", "D:\\path\\to\\index.db"]
    }
  }
}
```

### Codex

Codex CLI reads MCP servers from `~/.codex/config.toml`
(Windows: `C:\Users\<you>\.codex\config.toml`; create the file if it
doesn't exist). Add:

```toml
[mcp_servers.nxopen]
command = "nxopen-mcp-enhanced"
args = ["serve"]
```

If `nxopen-mcp-enhanced` isn't on PATH, use the full executable path (double the
backslashes on Windows):

```toml
[mcp_servers.nxopen]
command = "D:\\path\\to\\venv\\Scripts\\nxopen-mcp-enhanced.exe"
args = ["serve", "--db", "D:\\path\\to\\index.db"]
```

Alternatively, one CLI command does the same thing:

```bash
codex mcp add nxopen -- nxopen-mcp-enhanced serve
```

Restart Codex, then verify with `codex mcp list` (or just ask it to look
up an NXOpen class — you'll see the `nxopen` tool calls). Note the same
first-semantic-query model load (~1–2 min) applies here.

### Cursor

Add the same JSON block as `.mcp.json` above to Cursor's MCP settings
(project `.cursor/mcp.json`, or global via Settings → MCP).

## Tools

| tool | purpose |
|---|---|
| `search_api` | Hybrid semantic search over the API (dense + exact-name by default, sparse optional). Accepts English or 中文 queries; use when you don't know the exact class/member name. |
| `get_class` | Member list for a class, including inherited members. Paginated: `offset` / `limit` (default 200), the footer shows the total and the next offset. Use when you know the class name. |
| `get_member` | Exact signature, parameters, return value, NX version, and license requirement for one member. |
| `find_builder` | Given a CAM operation name (e.g. "cavity milling", "hole drilling"), finds the matching `*Builder` class, its creator method, and a Builder → Commit → Destroy code skeleton. |

## Architecture

```
NXOpen*.xml / *.dll  (your NX install)
        │
        ▼
  indexer/parser.py        one XML doc-comment member -> one MemberRecord
  indexer/inheritance.py   optional: reflect DLLs (pythonnet) for base-class chains
        │
        ▼
  indexer/embedder.py      BGE-M3 dense vector + sparse token weights per record
        │
        ▼
  indexer/build.py         writes members, dense_vec (sqlite-vec), sparse_postings
        │                  into a single SQLite file (index.db)
        ▼
  retrieval/store.py       exact-name lookup, class/member/inheritance queries
  retrieval/hybrid.py      dense ANN + exact CamelCase match (default),
                           optional sparse channel, RRF fusion
        │
        ▼
  server.py                4 MCP tools (FastMCP, stdio transport)
  cli.py                   `nxopen-mcp-enhanced index` / `nxopen-mcp-enhanced serve`
```

Design decisions:

- **BYO-Docs licensing.** This repository contains no Siemens XML/DLL
  files. Users point `nxopen-mcp-enhanced index` at their own licensed NX
  installation; the resulting index is a local SQLite file that never
  leaves the machine and is never committed (see `.gitignore`).
- **One-member-one-chunk.** Each indexed unit is a single API member
  (type, property, method, field, or event) rather than an arbitrary text
  window, so retrieval results map 1:1 onto something an agent can act on
  (a class, a method signature) instead of a fragment of a doc page.
- **RRF fusion, not score blending.** When the sparse channel is enabled,
  dense and sparse rankings are combined with Reciprocal Rank Fusion,
  which is scale-free and doesn't require calibrating dense-vs-sparse
  score magnitudes against each other (the evaluated default runs
  dense + exact only).
  Exact CamelCase name matches are promoted ahead of the fused list
  outright, since a literal name in the query is a much stronger signal
  than similarity.
- **Inheritance via reflection, with graceful degradation.** Ancestor
  chains (needed by `get_class` to show inherited members) are extracted
  by reflecting the NXOpen DLLs with `pythonnet` (`[reflect]` extra) at
  index time. If the extra isn't installed or DLLs aren't found alongside
  the XML docs, indexing still succeeds — `get_class` simply has no
  inherited members to show.

## Evaluation

Measured on a real index built from an NX 12 installation (97,913 API
members) against a 73-query golden set (`eval/golden.jsonl`, mixed
English / Traditional Chinese, four query styles — semantic description,
exact class name, member lookup, builder idiom — spanning CAM, Features,
Sketch, Assemblies, Drawings, UF, and BlockStyler):

```bash
python eval/run_eval.py --db ~/.nxopen-mcp-enhanced/index.db
```

| config | Recall@5 | Recall@10 | MRR |
|---|---|---|---|
| dense-only | 58.90% | 68.49% | 0.420 |
| sparse-only | 34.25% | 38.36% | 0.193 |
| **dense+exact (default)** | **58.90%** | **68.49%** | **0.445** |
| dense+sparse+exact | 49.32% | 61.64% | 0.409 |

### With vs. without the tool: hallucination test

Same model (Claude Haiku), the original 33 golden questions, one
variable — whether the nxopen-mcp-enhanced tools are available. Answers were graded against the golden
set; "hallucinated" means the proposed member does not exist anywhere in
the real 97,913-member index:

| metric | closed-book (no tool) | with nxopen-mcp-enhanced |
|---|:---:|:---:|
| exactly correct | 13/33 (39.4%) | **31/33 (93.9%)** |
| wrong but real API | 13/33 (39.4%) | 2/33 (6.1%) |
| **hallucinated (API does not exist)** | **7/33 (21.2%)** | **0/33 (0%)** |
| time to answer all 33 | 84 s | 321 s (44 tool calls) |

The closed-book hallucinations are the dangerous kind — plausible names
like `NXOpen.CAM.MillGeometryBuilder` (real name: `MillGeomBuilder`) or
`NXOpen.Session.Parts.Open` (real: `NXOpen.PartCollection.Open`) that
read fine and fail at compile time. Tool-assisted answering costs ~7 s
per question and eliminated hallucinations entirely.

**Evaluation-driven default.** The original design fused dense, sparse
and exact-name channels with uniform RRF. Measurement showed BGE-M3's
sparse channel *hurt* on this corpus — on the initial 33-query set a
weight sweep (w_sparse ∈ {0.5, 0.3, 0.15}) never recovered the
dense-only baseline, and expanding the golden set to 73 queries
replicated the finding (Recall@5 58.9% → 49.3% when sparse is fused).
The exact-name channel — after reordering its matches (types first,
shortest name first, capped at 3) — matches dense recall while
*improving* MRR (0.420 → 0.445) and guaranteeing literal-name hits. The
default is therefore **dense + exact**; the sparse channel remains
available via the `channels` parameter of `search()`.

## Demo

![Claude Code querying the real NXOpen API through nxopen-mcp-enhanced](docs/demo.gif)

A real session: asked to write NXOpen code that sets the spindle speed,
Claude Code calls `search_api` (semantic search, English or Chinese) and
`get_class` (members + inheritance chain), then writes code in which every
member — `FeedsBuilder`, `SpindleRpmToggle`, `SpindleRpmBuilder.Value` —
exists in the real API, with NX version info to prove it.

## Sharing a pre-built index

The index is a single SQLite file (~500 MB for a full NX 12 doc set), so
teammates can skip the hours-long build:

1. Install nxopen-mcp-enhanced (the `[reflect]` extra is not needed — inheritance
   chains are already baked into the index).
2. Copy the index file to `~/.nxopen-mcp-enhanced/index.db` (or keep it elsewhere
   and pass `--db <path>` to `serve`).
3. Register the server: `claude mcp add -s user nxopen -- nxopen-mcp-enhanced serve`

A full step-by-step onboarding guide (with troubleshooting):
[docs/setup-prebuilt-index.md](docs/setup-prebuilt-index.md)
([繁體中文版](docs/setup-prebuilt-index.zh-TW.md)).

The BGE-M3 model (~2 GB) still downloads on the first *semantic* query —
it encodes the query text, independent of the index. Exact lookups
(`get_class` / `get_member`) never need the model.

**Licensing boundary:** the index embeds text from Siemens' API
documentation. Sharing it **within an organization whose seats are
licensed for NX** is reasonable; do **not** redistribute index files
publicly — anyone outside your license should build their own with
`nxopen-mcp-enhanced index`.

## License & IP

Code: MIT (see [LICENSE](LICENSE)). This repository contains **no**
Siemens files — no NXOpen XML docs, no DLLs. The index is built locally
from your own licensed NX installation's documentation via
`nxopen-mcp-enhanced index` and never leaves your machine.
