# Tasks: opencode-mcp-channel

- [x] `sync.py`: add `import os`, `UV_PINNED_ENV`, `_graph_launcher()` (project venv → uv with pinned env → plain python), `_write_opencode_config()` (write-if-missing; WSL paths skipped)
- [x] `sync.py`: `_rebuild_graph()` routes both `--build` and `--visualize` through the resolver with the pinned child env
- [x] `sync.py`: new OpenCode block in `sync_project()` — `opencode.json` (when `code_graph`), four `.opencode/commands/coograph-*.md`, `.opencode/plugin/log-bash.ts`
- [x] `.mcp.json`: `env` block with `UV_NO_MANAGED_PYTHON` + `UV_PYTHON_DOWNLOADS` (copied verbatim into projects by sync)
- [x] `coograph-init` SKILL.md: Q2 OpenCode bullet, Step 3 For-OpenCode file list, Step 6c App-Control note, Step 6e OpenCode config example + merge rule (`mcp` object / `skills.paths`)
- [x] `README.md`: OpenCode row in the tools matrix + audit-matrix row (propagation claim)
- [x] `SETUP.md`: OpenCode row in the per-tool config table
- [x] `.github/code-graph/README.md`: pinned-uv + system-Python-venv start options; env pins in the VS Code and Claude config examples; new OpenCode `opencode.json` example with `environment`/`timeout`/`cwd` notes
- [x] `MIGRATION.md`: 2026-10-05 top entry (auto-propagation scope + manual steps for hand-written configs)
- [x] Verification: `sync.py` compiles (AST); resolver unit checks (uv-on-PATH → pinned uv; venv present → venv python); `sync_project` end-to-end on a synthetic project — skills/retro/code-graph/.mcp.json copied, `opencode.json` generated, four command files + `log-bash.ts` copied, existing `opencode.json` untouched on re-sync, rebuild ran through the pinned uv launcher; MCP handshake spawned exactly as the generated `opencode.json` describes → `tools/list` lists code-graph tools against a graph fixture
