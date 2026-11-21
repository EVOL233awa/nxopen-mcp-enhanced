# Changelog

格式遵循 [Keep a Changelog 2.0.0](https://keepachangelog.com/zh-CN/2.0.0/)，版本号遵循
[Semantic Versioning 2.0.0](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2026-11-21

基于上游 0.2.0 的首个增强版本。

### Added

- 嵌入：新增 OpenAI 兼容 `/v1/embeddings` 远程模式，默认 `BAAI/bge-m3`；本地 BGE-M3 保留。
- 重排：新增可选 `/v1/rerank`（`bge-reranker-v2-m3`），15 s 超时，唯一名跳过。
- `get_class`：新增 `offset` / `limit` 分页（默认 200），末尾给出总数与下一个 offset。
- 文档：新增中英双语 README。

### Changed

- 包名、模块与命令改为 `nxopen-mcp-enhanced` / `nxopen_mcp_enhanced` / `nxopen-mcp-enhanced`。
- 默认数据目录改为 `~/.nxopen-mcp-enhanced/`，可与上游 `~/.nxopen-mcp/` 共存。
- NX 12 文档发现兼查 `NXBIN/managed` 与安装根，不再只查 `UGII/managed`。
- 依赖约束为 `mcp>=1.2,<2`，匹配 FastMCP API。

### Fixed

- 嵌入服务不可用时回退本地精确匹配（整串名与驼峰标识符），首行标注，不再直接失败。
- 断网回退覆盖单字名。
- 慢查询期间 `get_class` / `get_member` 不再被阻塞。
