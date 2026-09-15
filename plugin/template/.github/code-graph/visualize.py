"""Graph visualization generator.

Assembles a self-contained HTML file from:
  - static/styles.css   → inlined <style>
  - static/panel.js     → inlined <script> (side-panel + connection list)
  - static/graph.js     → inlined <script> (D3 force graph + views)
  - node_modules/d3/…   → inlined <script>
  - graph data from SQLite → inlined JSON

No external Python dependencies required.

Usage:
    from visualize import generate_html
    generate_html(Path("graph.db"), Path("graph.html"))
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path


_STATIC = Path(__file__).parent / "static"


def _read_static(name: str) -> str:
    p = _STATIC / name
    if not p.exists():
        raise FileNotFoundError(f"Missing {p}")
    return p.read_text(encoding="utf-8")


def generate_html(db_path: Path, output_path: Path) -> Path:
    """Read *db_path* and write a self-contained interactive HTML graph."""
    graph_data = _extract_data(db_path)

    d3_path = Path(__file__).parent / "node_modules" / "d3" / "dist" / "d3.min.js"
    if not d3_path.exists():
        raise FileNotFoundError(
            f"d3.min.js not found at {d3_path}. "
            "Run 'npm install' in .github/code-graph/ first."
        )
    d3_script = d3_path.read_text(encoding="utf-8")
    css       = _read_static("styles.css")
    panel_js  = _read_static("panel.js")
    graph_js  = _read_static("graph.js")

    html = _SHELL.replace("/*CSS*/", css)
    html = html.replace("/*D3_INLINE*/", d3_script)
    html = html.replace("/*GRAPH_DATA*/", f"const graphData = {json.dumps(graph_data)};")
    html = html.replace("/*PANEL_JS*/", panel_js)
    html = html.replace("/*GRAPH_JS*/", graph_js)

    output_path.write_text(html, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# Data extraction (DB → JSON dict)
# ---------------------------------------------------------------------------

def _assign_group(parts: tuple[str, ...]) -> str:
    """Assign a file to a logical group based on its path parts.

    For multi-service repos (Java microservices, monorepos), returns parts[0].
    Called only when smart grouping is active (single dominant top-level dir).
    Produces groups like: (public), (system), components, hooks, features/calc, api, lib.
    """
    # Skip the dominant root dir (e.g. "src") and optional "app" dir
    skip = 1
    if len(parts) > skip and parts[skip] in ("app", "pages", "views"):
        skip += 1

    rest = parts[skip:]
    if not rest:
        return parts[0] if parts else "_root"

    first = rest[0]

    # Next.js route groups: (public), (system), (admin), etc.
    if first.startswith("(") and first.endswith(")"):
        # Use deeper segment if available: (system)/admin-profile -> admin-profile
        if len(rest) > 1:
            return rest[1]
        return first

    # api routes
    if first == "api":
        return "api"

    # Common patterns: common/components, common/hooks, common/context, etc.
    if first in ("common", "shared", "core"):
        if len(rest) > 1:
            return rest[1]  # components, hooks, context, utils, etc.
        return first

    # Features directory: features/calculator -> calculator
    if first in ("features", "modules", "domains"):
        if len(rest) > 1:
            return rest[1]
        return first

    # lib, utils, helpers, config, styles, types at app level
    if first in ("lib", "utils", "helpers", "config", "styles", "types",
                 "services", "store", "state", "i18n", "messages"):
        return first

    # Fallback: use the first meaningful segment
    return first


def _extract_data(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)

    # ---- File nodes (initial grouping by top-level dir) ----
    file_nodes: dict[str, dict] = {}
    for nid, name, file in conn.execute(
        "SELECT id, name, file FROM nodes WHERE kind='file'"
    ):
        parts = Path(file).parts
        service = parts[0] if parts else "_root"
        file_nodes[nid] = {
            "id": nid, "label": Path(file).name,
            "file": file, "service": service,
            "ext": Path(file).suffix.lstrip(".").lower(),
        }

    # ---- Smart grouping: split dominant single-service into sub-groups ----
    if file_nodes:
        svc_counts: dict[str, int] = defaultdict(int)
        for node in file_nodes.values():
            svc_counts[node["service"]] += 1
        total = len(file_nodes)
        top_svc = max(svc_counts, key=svc_counts.get)  # type: ignore[arg-type]
        # If one dir has >75% of files, re-group into logical sub-groups
        if svc_counts[top_svc] / total > 0.75 and total > 20:
            for node in file_nodes.values():
                parts = Path(node["file"]).parts
                if parts and parts[0] == top_svc:
                    node["service"] = _assign_group(parts)

            # Collapse tiny groups (<=2 files) into "_root"
            grp_counts: dict[str, int] = defaultdict(int)
            for node in file_nodes.values():
                grp_counts[node["service"]] += 1
            tiny = {g for g, c in grp_counts.items() if c <= 2}
            # Don't collapse groups that have meaningful names
            _keep = {"api", "i18n", "context", "store", "state", "styles", "types", "messages"}
            tiny -= _keep
            if tiny:
                for node in file_nodes.values():
                    if node["service"] in tiny:
                        node["service"] = "_root"

    # ---- Reverse index: filepath → file-node ID ----
    file_to_fid: dict[str, str] = {v["file"]: k for k, v in file_nodes.items()}

    # ---- Symbol nodes ----
    symbol_nodes: dict[str, dict] = {}
    symbols_by_file: dict[str, list] = defaultdict(list)
    for nid, kind, name, file, start_line in conn.execute(
        "SELECT id, kind, name, file, start_line FROM nodes "
        "WHERE kind IN ('class','interface','enum','function','method','annotation','table','endpoint')"
    ):
        symbol_nodes[nid] = {"id": nid, "kind": kind, "name": name, "file": file, "line": start_line}
        fid = file_to_fid.get(file)
        if fid:
            symbols_by_file[fid].append({"id": nid, "kind": kind, "name": name, "line": start_line})

    all_node_ids = set(file_nodes) | set(symbol_nodes)

    # ---- Smart labels: use primary symbol name for generic filenames ----
    _GENERIC_NAMES = frozenset({
        "index.tsx", "index.ts", "index.jsx", "index.js",
        "page.tsx", "page.ts", "page.jsx", "page.js",
        "layout.tsx", "layout.ts", "route.tsx", "route.ts",
        "mod.rs", "__init__.py",
    })
    # Priority: class/interface > PascalCase function > first function > parent dir
    for fid, node in file_nodes.items():
        basename = node["label"]
        syms = symbols_by_file.get(fid, [])
        if not syms and basename in _GENERIC_NAMES:
            # No symbols — use parent directory name
            parent = Path(node["file"]).parent.name
            if parent and parent not in (".", ""):
                node["label"] = parent
            continue
        if not syms:
            continue
        # Find best symbol to use as label
        best = None
        for s in syms:
            if s["kind"] in ("class", "interface", "enum"):
                best = s["name"]
                break
        if not best:
            # PascalCase function = likely a component
            for s in syms:
                if s["kind"] in ("function", "method") and s["name"][0:1].isupper():
                    best = s["name"]
                    break
        if best and basename in _GENERIC_NAMES:
            node["label"] = best
        elif best and basename.endswith((".tsx", ".jsx")):
            # Even non-generic .tsx files benefit from component name
            # Only override if the symbol name is more descriptive
            stem = Path(basename).stem.replace("-", "").replace("_", "").lower()
            sym_lower = best.lower()
            # If filename is just a kebab-case version of the symbol, keep symbol
            if stem != sym_lower:
                node["label"] = best

    # ---- File-level edges ----
    FILE_EDGE_TYPES = ("depends_on", "tests_for", "inherits", "implements", "calls")
    edges_by_type: dict[str, list] = {}
    for kind in FILE_EDGE_TYPES:
        edges_by_type[kind] = [
            {"s": src, "t": dst}
            for src, dst in conn.execute("SELECT src, dst FROM edges WHERE kind=?", (kind,))
            if src in file_nodes and dst in file_nodes
        ]

    # ---- Symbol-level edges ----
    symbol_edges: dict[str, list] = {}
    for kind in ("contains", "inherits", "implements", "calls"):
        symbol_edges[kind] = [
            {"s": src, "t": dst}
            for src, dst in conn.execute("SELECT src, dst FROM edges WHERE kind=?", (kind,))
            if src in all_node_ids and dst in all_node_ids
            and not (src in file_nodes and dst in file_nodes)
        ]

    conn.close()

    # ---- Service summaries ----
    services: dict[str, dict] = {}
    for node in file_nodes.values():
        svc = node["service"]
        if svc not in services:
            services[svc] = {"files": 0, "classes": 0, "functions": 0}
        services[svc]["files"] += 1

    for fid, syms in symbols_by_file.items():
        svc = file_nodes[fid]["service"]
        for s in syms:
            if s["kind"] in ("class", "interface", "enum"):
                services[svc]["classes"] += 1
            elif s["kind"] in ("function", "method"):
                services[svc]["functions"] += 1

    # ---- Service-level aggregated edges ----
    svc_pair: dict[tuple[str, str], dict] = {}
    for etype, elist in edges_by_type.items():
        for e in elist:
            s = file_nodes[e["s"]]["service"]
            t = file_nodes[e["t"]]["service"]
            if s != t:
                key = (s, t)
                if key not in svc_pair:
                    svc_pair[key] = {k: 0 for k in FILE_EDGE_TYPES}
                svc_pair[key][etype] += 1

    # ---- Files grouped by service ----
    files_by_service: dict[str, list] = {}
    for nid, node in file_nodes.items():
        files_by_service.setdefault(node["service"], []).append({
            "id": nid, "label": node["label"], "file": node["file"], "ext": node["ext"],
        })

    # ---- Extension stats ----
    ext_counts: dict[str, int] = defaultdict(int)
    for node in file_nodes.values():
        ext_counts[node["ext"]] += 1
    top_exts = sorted(ext_counts.keys(), key=lambda e: -ext_counts[e])[:12]

    return {
        "services":       [{"id": k, "label": k, **v} for k, v in sorted(services.items())],
        "serviceEdges":   [{"s": s, "t": t, **c} for (s, t), c in svc_pair.items()],
        "filesByService": files_by_service,
        "symbolsByFile":  dict(symbols_by_file),
        "edges":          edges_by_type,
        "symbolEdges":    symbol_edges,
        "topExts":        top_exts,
        "extCounts":      dict(ext_counts),
        "edgeStats":      {k: len(v) for k, v in edges_by_type.items()},
        "totalFiles":     len(file_nodes),
        "totalSymbols":   len(symbol_nodes),
    }


# ---------------------------------------------------------------------------
# HTML shell — all logic lives in static/*.js, only placeholders here
# ---------------------------------------------------------------------------

_SHELL = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Code Graph</title>
<style>/*CSS*/</style>
</head>
<body>

<div id="panel">
  <div id="panel-resize"></div>
  <div id="panel-header">
    <div id="breadcrumb">
      <button id="back-btn">&#x2190; Back</button>
      <span id="crumb-text">Services</span>
    </div>
    <input id="search" type="text" placeholder="Search…" autocomplete="off">
  </div>

  <div id="panel-body">
    <div id="node-info">
      <div class="sec-title">Selected</div>
      <div id="ni-name"></div>
      <div id="ni-path"></div>
    </div>

    <div id="conn-list"></div>

    <div id="symbol-list">
      <div class="sec-title">Symbols</div>
      <div id="sym-items"></div>
    </div>

    <div id="node-list-section">
      <div class="sec-title">Nodes <span id="node-list-count"></span></div>
      <div id="node-list"></div>
    </div>

    <div class="sec-title">Edges</div>
    <label class="filter-row">
      <input type="checkbox" data-etype="depends_on" checked>
      <span class="swatch" style="background:#c8851a"></span>
      <span class="filter-label">depends_on</span>
      <span class="filter-count" id="cnt-depends_on"></span>
    </label>
    <label class="filter-row">
      <input type="checkbox" data-etype="tests_for">
      <span class="swatch" style="background:#2a9d5c"></span>
      <span class="filter-label">tests_for</span>
      <span class="filter-count" id="cnt-tests_for"></span>
    </label>
    <label class="filter-row">
      <input type="checkbox" data-etype="inherits" checked>
      <span class="swatch" style="background:#e74c3c"></span>
      <span class="filter-label">inherits</span>
      <span class="filter-count" id="cnt-inherits"></span>
    </label>
    <label class="filter-row">
      <input type="checkbox" data-etype="implements" checked>
      <span class="swatch" style="background:#1abc9c"></span>
      <span class="filter-label">implements</span>
      <span class="filter-count" id="cnt-implements"></span>
    </label>
    <label class="filter-row">
      <input type="checkbox" data-etype="calls">
      <span class="swatch" style="background:#3498db"></span>
      <span class="filter-label">calls</span>
      <span class="filter-count" id="cnt-calls"></span>
    </label>
    <label class="filter-row">
      <input type="checkbox" data-etype="contains">
      <span class="swatch" style="background:#d4b43a"></span>
      <span class="filter-label">contains (file→symbol)</span>
      <span class="filter-count" id="cnt-contains"></span>
    </label>

    <div id="show-all-row">
      <label class="filter-row">
        <input type="checkbox" id="show-all-cb">
        <span class="filter-label">Show all edges in view</span>
      </label>
    </div>

    <div id="exclude-tests-row" style="display:none">
      <label class="filter-row">
        <input type="checkbox" id="exclude-tests-cb" checked onchange="Graph.onExcludeTestsChange()">
        <span class="filter-label">Exclude test files</span>
      </label>
      <label class="filter-row">
        <input type="checkbox" id="exclude-pomspec-cb" checked onchange="Graph.onExcludePomSpecChange()">
        <span class="filter-label">Exclude pom / specs / package-info</span>
      </label>
    </div>

    <div id="sym-type-filters" style="display:none">
      <div class="sec-title">Show Symbols</div>
      <label class="filter-row"><input type="checkbox" class="sym-type-cb" data-symtype="class" onchange="Graph.onSymTypeChange()"><span class="dot-swatch" style="background:#2980b9"></span><span class="filter-label">Classes</span></label>
      <label class="filter-row"><input type="checkbox" class="sym-type-cb" data-symtype="interface" onchange="Graph.onSymTypeChange()"><span class="dot-swatch" style="background:#8e44ad"></span><span class="filter-label">Interfaces</span></label>
      <label class="filter-row"><input type="checkbox" class="sym-type-cb" data-symtype="enum" onchange="Graph.onSymTypeChange()"><span class="dot-swatch" style="background:#27ae60"></span><span class="filter-label">Enums</span></label>
      <label class="filter-row"><input type="checkbox" class="sym-type-cb" data-symtype="function" onchange="Graph.onSymTypeChange()"><span class="dot-swatch" style="background:#e67e22"></span><span class="filter-label">Functions / Methods</span></label>
      <label class="filter-row"><input type="checkbox" class="sym-type-cb" data-symtype="annotation" onchange="Graph.onSymTypeChange()"><span class="dot-swatch" style="background:#c0392b"></span><span class="filter-label">Annotations</span></label>
    </div>

    <div class="sec-title" id="ext-title" style="display:none">File types</div>
    <div id="ext-filters"></div>

    <div id="svc-legend">
      <div class="sec-title">Groups</div>
      <div id="svc-legend-items"></div>
    </div>

    <div id="file-legend" style="display:none">
      <div class="sec-title">Files by Type</div>
      <div class="filter-row"><span class="dot-swatch" style="background:#4a7fa5"></span><span class="filter-label">.java</span></div>
      <div class="filter-row"><span class="dot-swatch" style="background:#7b68ee"></span><span class="filter-label">.kt</span></div>
      <div class="filter-row"><span class="dot-swatch" style="background:#e07b39"></span><span class="filter-label">.xml</span></div>
      <div class="filter-row"><span class="dot-swatch" style="background:#d4b43a"></span><span class="filter-label">.yaml / .yml</span></div>
      <div class="filter-row"><span class="dot-swatch" style="background:#c0392b"></span><span class="filter-label">.sql</span></div>
      <div class="filter-row"><span class="dot-swatch" style="background:#2a9d5c"></span><span class="filter-label">.json</span></div>
      <div class="filter-row"><span class="dot-swatch" style="background:#3498db"></span><span class="filter-label">.py</span></div>
      <div class="filter-row"><span class="dot-swatch" style="background:#e67e22"></span><span class="filter-label">.ts / .tsx</span></div>
      <div class="filter-row"><span class="dot-swatch" style="background:#95a5a6"></span><span class="filter-label">.properties</span></div>
      <div class="filter-row"><span class="dot-swatch" style="background:#556"></span><span class="filter-label">other</span></div>
    </div>

    <div id="sym-legend" style="display:none">
      <div class="sec-title">Symbol Kinds</div>
      <div class="filter-row"><span class="dot-swatch" style="background:#2980b9"></span><span class="filter-label">class</span></div>
      <div class="filter-row"><span class="dot-swatch" style="background:#8e44ad"></span><span class="filter-label">interface</span></div>
      <div class="filter-row"><span class="dot-swatch" style="background:#27ae60"></span><span class="filter-label">enum</span></div>
      <div class="filter-row"><span class="dot-swatch" style="background:#e67e22"></span><span class="filter-label">function / method</span></div>
      <div class="filter-row"><span class="dot-swatch" style="background:#c0392b"></span><span class="filter-label">annotation</span></div>
      <div class="filter-row"><span class="dot-swatch" style="background:#16a085"></span><span class="filter-label">table</span></div>
      <div class="filter-row"><span class="dot-swatch" style="background:#2c3e50"></span><span class="filter-label">endpoint</span></div>
    </div>

  </div>
</div>

<div id="tooltip"><div id="tt-title"></div><div id="tt-sub"></div><div id="tt-extra"></div></div>
<div id="stats"></div>
<div id="help-hint"><b>Click</b> node = select + connections<br><b>Double-click</b> = drill down<br><b>Scroll</b> = zoom<br><b>Click connection</b> = navigate</div>
<canvas id="graph"></canvas>

<script>/*D3_INLINE*/</script>
<script>/*GRAPH_DATA*/</script>
<script>/*PANEL_JS*/</script>
<script>/*GRAPH_JS*/</script>

</body>
</html>
"""
