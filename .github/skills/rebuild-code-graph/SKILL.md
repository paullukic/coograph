---
name: rebuild-code-graph
description: Rebuild or update the code-graph database. Use when the user wants to refresh the code graph, e.g. after major changes or when graph seems stale.
argument-hint: '"build" for full rebuild (default), "update" for incremental update.'
license: MIT
metadata:
  author: coograph
  version: "1.0"
---

Rebuild or incrementally update the `.code-graph/graph.db` SQLite database.

**IMPORTANT: This skill runs commands. Follow every step in order. Do not skip error handling.**

---

## Step 1: Locate the code-graph tooling

Find `server.py` — it could be in several locations depending on the project setup:

```
.github/code-graph/server.py          # standard location
coograph/.github/code-graph/server.py  # monorepo with template as submodule
```

Search for it:

```bash
find . -path "*/code-graph/server.py" -not -path "*/node_modules/*" 2>/dev/null | head -5
```

If **not found**: stop and tell the user:
> "No code-graph tooling found. Run the `initialize-project` skill to set it up, or copy `.github/code-graph/` from the coograph."

If **multiple found**: use the one closest to the current working directory (shortest path). Report which one you're using.

Store the resolved path as `$SERVER_PY`.

## Step 2: Check Python

```bash
python3 --version 2>/dev/null || python --version 2>/dev/null
```

If **neither works**: stop and tell the user Python 3.10+ is required.

If version is **below 3.10**: stop and tell the user Python 3.10+ is required.

Store the working Python command as `$PYTHON` (`python3` preferred over `python`).

## Step 3: Determine build mode

- If the user said "update" or "incremental" → use `--update`
- If the user said "build", "rebuild", "full", or gave no argument → use `--build`
- If `.code-graph/graph.db` does **not exist** → always use `--build` (update requires an existing db)

## Step 4: Run the build

Execute from the **project root** (the directory where `.code-graph/` should be created):

```bash
cd <project-root> && $PYTHON $SERVER_PY <--build or --update>
```

**Expected success output** includes lines like:
- `Detected stacks: java, structured`
- `Graph built: N files -> .code-graph/graph.db (X.XXs)`

or for update:
- `Graph updated: updated N, dependents M, deleted D`
- `Graph up to date — no changes detected.`

## Step 5: Verify

Confirm the database exists and has data:

```bash
$PYTHON -c "
import sqlite3, os
db = '<project-root>/.code-graph/graph.db'
if not os.path.exists(db):
    print('ERROR: graph.db was not created')
    exit(1)
conn = sqlite3.connect(db)
nodes = conn.execute('SELECT COUNT(*) FROM nodes').fetchone()[0]
edges = conn.execute('SELECT COUNT(*) FROM edges').fetchone()[0]
stacks = conn.execute(\"SELECT value FROM meta WHERE key='stacks'\").fetchone()
print(f'Graph OK: {nodes:,} nodes, {edges:,} edges')
if stacks: print(f'Stacks: {stacks[0]}')
conn.close()
"
```

If **nodes is 0**: warn the user — the builder may not have detected the tech stack. Ask them to check if the project has recognizable stack markers (pom.xml, package.json, go.mod, etc.).

## Step 6: Report

Tell the user:
- ✅ Graph rebuilt/updated successfully
- Node count, edge count, detected stacks
- File path of the database

## Error Handling

If the build command fails:

1. **`ModuleNotFoundError: No module named 'parsers'`** — the script was run from the wrong directory. Ensure `$PYTHON` runs `$SERVER_PY` with the server.py's parent directory containing `parsers/`. The `--build` flag does NOT require `mcp`.

2. **`FileNotFoundError` or permission errors** — check the project root path is correct and writable.

3. **Empty output / no files parsed** — the stack detection found no recognized files. Check that the project root is correct (not a subdirectory).

4. **Any other error** — show the full error output to the user and suggest running manually:
   ```
   cd <project-root> && uv run --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py --build
   ```
