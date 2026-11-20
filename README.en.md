# nxopen-mcp-enhanced

**English** | [简体中文](README.md)

Current version 1.0.0 (not yet published to PyPI).

> **Enhanced fork** of [mingfeng6684/nxopen-mcp](https://github.com/mingfeng6684/nxopen-mcp)
> and the MCP component of
> [nxopen-journal-toolkit](https://github.com/EVOL233awa/nxopen-journal-toolkit).

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
| Reranking | None | Optional `/v1/rerank` (bge-reranker-v2-m3), 15 s timeout, skipped for unique names; **recommended** (+12.3 pt Recall@5) |
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

- **Semantic search** (BGE-M3 embeddings) so natural-language
  queries in English or 中文 find the right API even without exact names.
- **Exact-name channel**: a literal CamelCase name in your query (e.g.
  `CavityMillingBuilder`) is looked up directly and pinned to the top
  (types first) — never left to approximate matching.
- **Optional reranking** of the top candidates, which is what the evaluation
  recommends (see [Evaluation](#evaluation)).

The default is fully local and offline against an index built from your own
licensed NX installation — no Siemens files are bundled or sent anywhere. The
recommended setup then adds a remote embedding/rerank provider
(see [Remote embedding and reranking](#remote-embedding-and-reranking-recommended));
when it is enabled, only query and document text leaves the machine.

## Quick start

Requires **Python 3.11+**.

```bash
# 1. Install from this repository (not on PyPI yet)
git clone https://github.com/EVOL233awa/nxopen-mcp-enhanced
cd nxopen-mcp-enhanced
# Recommended: remote embeddings + reranking. SiliconFlow serves BAAI/bge-m3 and
#   BAAI/bge-reranker-v2-m3 for free, so nothing is downloaded. Set the
#   NXOPEN_MCP_* variables first (see "Remote embedding and reranking").
pip install -e ".[reflect]"
# Or fully local and offline: downloads ~2 GB BGE-M3 on first use
# pip install -e ".[embed,reflect]"

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
model on first use) — needed only for the local embedding path.
`[reflect]` pulls in `pythonnet` so `get_class` can show inherited
members; skip it and indexing still works, just without inheritance
chains.

**How long does indexing take?** A full NX 12 doc set is ~100k members. Local
embedding is memory-bandwidth-bound, so it takes hours; `--workers N` helps
mostly on machines with more memory channels, and a CUDA GPU helps a lot. With
a remote embedding service the wall time follows the provider's rate limit and
`--workers N` submits batches concurrently.

**First semantic query is slow by design (local path).** `serve` starts instantly, and
`get_class` / `get_member` respond immediately, but the first
`search_api` / `find_builder` call loads the BGE-M3 model. After that, semantic
queries take seconds. If your MCP client shows the first search "hanging", it's
the one-time model load — let it finish. The remote path has no load step.

By default the index is written to `~/.nxopen-mcp-enhanced/index.db`; override with
`--db <path>` on both `index` and `serve`.

## Remote embedding and reranking (recommended)

**SiliconFlow is the recommended provider**: it serves `BAAI/bge-m3` (1024-dim
embeddings) and `BAAI/bge-reranker-v2-m3` (reranking) as free models on its
official pricing page — the same two models this fork defaults to, so retrieval
quality is unchanged while the local model and its compute disappear. The free
tier has fixed rate limits and requires identity verification; the `Pro/`
variants of the same models are paid fast tiers. Check the
[pricing page](https://siliconflow.cn/pricing) and your console for current
terms.

The remote path installs no `[embed]` extra and downloads no model. Set these
before `index` and `serve`:

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

Any OpenAI-compatible embedding service accepts the same variables (Ollama uses
`NXOPEN_MCP_EMBEDDER=ollama`). `index` and `serve` must use the **same** settings:
the vectors in the index come from whichever model built it, so switching models
means rebuilding the index.

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
up an NXOpen class — you'll see the `nxopen` tool calls). On the local
embedding path the same first-semantic-query model load applies here.

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
                           optional sparse channel, RRF fusion, optional rerank
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

Measured on a real index built from an NX 12 installation (95,807 API
members) against a 73-query golden set (`eval/golden.jsonl`, mixed
English / Traditional Chinese, four query styles — semantic description,
exact class name, member lookup, builder idiom — spanning CAM, Features,
Sketch, Assemblies, Drawings, UF, and BlockStyler):

```bash
python eval/run_eval.py --db ~/.nxopen-mcp-enhanced/index.db
```

Remote `BAAI/bge-m3` embeddings + `BAAI/bge-reranker-v2-m3` reranking, same index,
same queries:

| config | Recall@5 | Recall@10 | MRR |
|---|---|---|---|
| dense-only | 56.16% | 67.12% | 0.411 |
| **dense+exact** | 57.53% | 67.12% | 0.437 |
| **dense+exact+rerank (recommended)** | **69.86%** | **78.08%** | **0.531** |

The exact-name channel guarantees that a literal class/member name is surfaced,
and reranking reorders the first 20 candidates; together they lift Recall@5 by
13.7 pt over dense alone. The remote embedder returns no sparse lexical weights,
so there is no sparse row here; the local BGE-M3 path can still enable that
channel via the `channels` parameter of `search()`.

Per query, reranking improved 11, worsened 2, left 60 unchanged. Both
regressions are "Chinese verb + English noun" queries (`取得零件的 CAM setup
物件`, `create hole feature 建立孔特徵`), where reranking down-weights the literal
API name.

Two further effects matter in practice:

- The index does **not** need rebuilding when switching between local BGE-M3
  and the same model served remotely: the vectors agree to cosine 0.99988–0.99994,
  and a 2,000-member re-embedding kept 97.1% of the golden set's top-10
  identical (the residual is batching float noise, batch 1 vs 128 included).
- Plain 2–4 character Chinese queries with no English term still miss
  (`拉伸` returns `RelaxationLength`); add the English term
  (`创建拉伸特征 extrusion`) or use `get_class` / `get_member` by name.

### Hallucination test: closed book vs. with the tools

Same model (`deepseek-v4.1-flash-1017`, max thinking), same 33 golden
questions, one variable: whether the four tools are reachable over MCP function
calling.

Grading is mechanical, so it can be re-run: every identifier in an answer
(`NXOpen.*` dotted paths, plus CamelCase tokens with 3+ humps that the answer
does not declare itself) is checked against NXOpen reflection — `NXOpen.dll`,
`NXOpen.Utilities.dll` and `NXOpen.UF.dll` — accepting `type.member` and
property chains such as `NXOpen.Session.Parts.Work.CAMSetup`. The oracle is
calibrated before grading: 14 known-real names (enum values included) must be
accepted and 7 known-fake names rejected, or the run aborts.

```bash
python eval/halluc_test.py collect --out answers.jsonl   # asks the model
python eval/halluc_test.py grade --answers answers.jsonl # reflection only
```

| metric | without MCP | with MCP |
|---|:---:|:---:|
| exactly correct | 4/33 (12.1%) | **19/33 (57.6%)** |
| hallucinated (API does not exist) | **29/33 (87.9%)** | 14/33 (42.4%) |
| total time | 3,241 s | 1,937 s |
| total tokens consumed (completion, reasoning included) | 367k | 186k |

## Demo

![Claude Code querying the real NXOpen API through nxopen-mcp-enhanced](https://raw.githubusercontent.com/EVOL233awa/nxopen-mcp-enhanced/master/docs/demo.gif)

A real session: asked to write NXOpen code that sets the spindle speed,
Claude Code calls `search_api` (semantic search, English or Chinese) and
`get_class` (members + inheritance chain), then writes code in which every
member — `FeedsBuilder`, `SpindleRpmToggle`, `SpindleRpmBuilder.Value` —
exists in the real API, with NX version info to prove it.

## Index licensing

The index embeds text from Siemens' API documentation. Building it locally from
your own licensed NX installation is what `nxopen-mcp-enhanced index` does; use
such an index only within an organization whose seats are licensed for NX. Do
**not** redistribute index files publicly — anyone outside your license should
build their own.

## License & IP

Code: MIT (see [LICENSE](LICENSE)). This repository contains **no**
Siemens files — no NXOpen XML docs, no DLLs. The index is built locally
from your own licensed NX installation's documentation via
`nxopen-mcp-enhanced index` and never leaves your machine.
