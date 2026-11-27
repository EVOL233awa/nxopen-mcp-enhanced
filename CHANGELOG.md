# Changelog

`nxopen-mcp-enhanced` 的版本变更记录。

格式遵循 [Keep a Changelog 2.0.0](https://keepachangelog.com/zh-CN/2.0.0/)，版本号遵循 [Semantic Versioning 2.0.0](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Changed

- 文档：补 `NXOPEN_MCP_OLLAMA_URL`、`NXOPEN_MCP_OLLAMA_MODEL`、`NXOPEN_MCP_OLLAMA_BATCH` 的说明。
- 内部：嵌入后端支持 `NXOPEN_MCP_EMBEDDER_FACTORY` 注入，测试钩子移出生产入口。
- 许可：`LICENSE` 版权行补仓库地址，新增 `NOTICE` 与 `TRADEMARK.md`（MIT 条款不变）。

### Fixed

- 依赖 `typer` 下限提到 0.16，避免与 click 8.2 及以上组合时 CLI 报 `unexpected extra argument`。

## [1.0.0] - 2026-11-21

基于上游 0.2.0 的首个增强版本。

### Added

- 嵌入：新增 OpenAI 兼容 `/v1/embeddings` 远程模式，默认模型 `BAAI/bge-m3`；本地 BGE-M3 保留。
- 重排：新增可选 `/v1/rerank` 重排，15 s 超时后回退未重排顺序，唯一精确名跳过。
- `get_class`：新增 `offset` / `limit` 分页，末尾给出总数与下一个 offset。
- 文档：新增中英双语 README。

### Changed

- 包名、模块与命令改为 `nxopen-mcp-enhanced` / `nxopen_mcp_enhanced` / `nxopen-mcp-enhanced`。
- 默认数据目录改为 `~/.nxopen-mcp-enhanced/`，可与上游 `~/.nxopen-mcp/` 共存。
- NX 12 文档发现兼查 `NXBIN/managed` 与安装根。
- 内部：依赖约束为 `mcp>=1.2,<2`，匹配 FastMCP API。

### Fixed

- 嵌入服务不可用时回退本地精确匹配（整串名与驼峰标识符），并在首行标注。
- 离线回退：单字名同样走本地精确匹配。
- 慢查询期间 `get_class` / `get_member` 不再被阻塞。

[1.0.0]: https://github.com/EVOL233awa/nxopen-mcp-enhanced/releases/tag/v1.0.0
