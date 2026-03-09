# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Vector index DDL correctness and schema init error visibility
- Embedding persistence via `vecf32()` for FalkorDB `VECTOR` type
- Lexical context in `loom calls` (parents/children via `CONTAINS` edges)
- Graph expansion includes `CONTAINS` edges in search
- CLI ambiguity handling for `loom calls` target resolution
- Comprehensive unit tests for vector indexing and embedding storage
- QA diagnostic script for DB-level vector query validation
- Open-source readiness: LICENSE (MIT), CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, GitHub templates, CI

### Fixed
- Vector index never created due to DDL syntax errors
- `loom query` always falling back to brute-force vector search
- Ambiguous names in `loom calls` failing with generic “Target not found”

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
