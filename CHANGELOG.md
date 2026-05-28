# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.0] - 2026-05-28

### Added — Domain-driven architecture restructure

- **`graph/` domain package** — new top-level package replacing scattered `core/` modules
  - `graph/db.py` — merged from `core/db.py` + `core/context.py`; SQLite schema init, DB class, `_add_column_if_missing`
  - `graph/schema.sql` — canonical DDL (moved from `core/schema.sql`)
  - `graph/models/` — `Node`, `Edge`, and all enums (`EdgeType`, `ConfidenceTier`, `NodeKind`, `NodeSource`, `Complexity`, `SummarySource`, `QuestionType`)
  - `graph/repository/` — `NodeRepository`, `EdgeRepository`, `FingerprintRepository`, `TagRepository`, `SearchRepository`, `ContextRepository`, `TraversalRepository`, `SessionRepository`, `AnalyticsRepository`
- **MCP server moved** — entry point is now `loom.server.run:run_stdio` (was `loom.mcp.run`)
- `store/` package retained for backwards compatibility; new code uses `graph/repository/`
- 403 unit tests passing

### Added — Index-time enrichment

- **File fingerprinting** — SHA-256 + mtime stored in new `file_fingerprints` table; enables true incremental re-index (skip files whose mtime and hash are unchanged)
- **Complexity classification** — `SIMPLE` / `MODERATE` / `COMPLEX` assigned per function/method, stored in `nodes.complexity` column
- **AutoTagger** — post-parse pass applying decorator tags (`api-endpoint`, `async-task`, `auth`, etc.), import-derived tags, and directory-based tags
- **TestLinker** — creates `TESTED_BY` edges between test files and production code they cover (Python, TypeScript, JavaScript, Java)
- **GraphTagger** — graph-derived tags: `dead-code`, `entry-point`, `hub`, `bridge`; runs after community detection
- **Tag search** — `tag:X` token syntax in `search_code` and `loom query`; multiple `tag:` tokens use AND semantics
- **Enhanced context packets** — `get_context` response now includes `complexity`, `tags`, and `tested_by` fields for function/method nodes
- **Agent tags** — `store_understanding` accepts optional `tags: list[str]`; stored in `node_tags` with `source="agent"`, survive re-index
- **`node_tags` table** — `(node_id, tag, source)` schema; `source="agent"` tags are preserved across re-analyze
- **`tags_normalized` column** — space-separated tags on `nodes`, indexed in FTS5 `nodes_fts` for text-search over tags

## [0.1.0] - 2026-03-09

### Added
- Initial release of Loom
- Repository indexing into FalkorDB graph
- Multi-language code understanding (Python, TS/JS, Java, Go, Rust, Ruby, markup)
- Call graph extraction
- Document ingestion (Markdown, PDF)
- Jira and traceability workflows
- Semantic linking (name match, embedding match, LLM match)
- Incremental sync and watch mode
- Semantic search with query-time graph expansion
- MCP server for editor/agent integration
- CLI commands: analyze, enrich, query, trace, calls, entrypoints, watch, sync, serve

---

## Release process

1. Update version in `pyproject.toml`
2. Add a new section to `CHANGELOG.md` under `[Unreleased]`
3. Commit and push
4. Create a GitHub Release with the changelog for that version
5. Tag the release: `git tag v0.1.0 && git push --tags`
