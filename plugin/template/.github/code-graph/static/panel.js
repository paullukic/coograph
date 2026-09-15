/* ================================================================
   Code Graph — panel.js
   Manages the side-panel: connection list, node info, symbol list,
   extension filters, search, and back navigation.

   Depends on: graphData (global), graph.js providing:
     renderFileView(), renderServiceView(), renderSymbolView(),
     selectService(), selectFile(), deselect()
   ================================================================ */

/* ----------------------------------------------------------------
   Connection list — ASCII-art clickable edges
   Shows "service ──42 deps──▶ target" lines that navigate on click.
   ---------------------------------------------------------------- */

const Panel = (() => {

  const $ = id => document.getElementById(id);

  /* ---- Build the clickable connection list for a service node ---- */
  function showServiceConnections(d) {
    const wrap = $("conn-list");
    wrap.style.display = "";
    wrap.innerHTML = "";

    const outE = Graph.svcAdj.out.get(d.id) || [];
    const inE  = Graph.svcAdj.in.get(d.id)  || [];

    // Group outbound edges by type
    const outByTarget = new Map();
    for (const e of outE) {
      if (!outByTarget.has(e.id)) outByTarget.set(e.id, []);
      if (e.depends_on) outByTarget.get(e.id).push({ kind: "depends_on", n: e.depends_on });
      if (e.tests_for)  outByTarget.get(e.id).push({ kind: "tests_for",  n: e.tests_for });
      if (e.inherits)   outByTarget.get(e.id).push({ kind: "inherits",   n: e.inherits });
      if (e.implements) outByTarget.get(e.id).push({ kind: "implements", n: e.implements });
      if (e.calls)      outByTarget.get(e.id).push({ kind: "calls",      n: e.calls });
    }

    const inBySource = new Map();
    for (const e of inE) {
      if (!inBySource.has(e.id)) inBySource.set(e.id, []);
      if (e.depends_on) inBySource.get(e.id).push({ kind: "depends_on", n: e.depends_on });
      if (e.tests_for)  inBySource.get(e.id).push({ kind: "tests_for",  n: e.tests_for });
      if (e.inherits)   inBySource.get(e.id).push({ kind: "inherits",   n: e.inherits });
      if (e.implements) inBySource.get(e.id).push({ kind: "implements", n: e.implements });
      if (e.calls)      inBySource.get(e.id).push({ kind: "calls",      n: e.calls });
    }

    // Render outbound section
    if (outByTarget.size) {
      const title = document.createElement("div");
      title.className = "conn-section-title";
      title.textContent = "OUTBOUND (" + outByTarget.size + " services)";
      wrap.appendChild(title);

      // Sort by total edge count descending
      const sorted = [...outByTarget.entries()].sort((a, b) => {
        const sumA = a[1].reduce((s, e) => s + e.n, 0);
        const sumB = b[1].reduce((s, e) => s + e.n, 0);
        return sumB - sumA;
      });

      for (const [targetId, edges] of sorted) {
        for (const edge of edges) {
          _appendConnRow(wrap, {
            direction: "out",
            count: edge.n,
            kind: edge.kind,
            target: targetId,
            onClick: () => Graph.renderFileView(targetId),
          });
        }
      }
    }

    // Render inbound section
    if (inBySource.size) {
      const title = document.createElement("div");
      title.className = "conn-section-title";
      title.textContent = "INBOUND (" + inBySource.size + " services)";
      wrap.appendChild(title);

      const sorted = [...inBySource.entries()].sort((a, b) => {
        const sumA = a[1].reduce((s, e) => s + e.n, 0);
        const sumB = b[1].reduce((s, e) => s + e.n, 0);
        return sumB - sumA;
      });

      for (const [sourceId, edges] of sorted) {
        for (const edge of edges) {
          _appendConnRow(wrap, {
            direction: "in",
            count: edge.n,
            kind: edge.kind,
            target: sourceId,
            onClick: () => Graph.renderFileView(sourceId),
          });
        }
      }
    }

    if (!outByTarget.size && !inBySource.size) {
      const empty = document.createElement("div");
      empty.style.cssText = "color:#334;font-size:11px;padding:4px 0";
      empty.textContent = "No cross-service connections";
      wrap.appendChild(empty);
    }
  }

  /* ---- Build clickable connection list for a file node ---- */
  function showFileConnections(d) {
    const wrap = $("conn-list");
    wrap.style.display = "";
    wrap.innerHTML = "";

    const types = Graph.activeTypes();
    let hasAny = false;

    for (const kind of types) {
      const outIds = Graph.adj[kind]?.out.get(d.id) || [];
      const inIds  = Graph.adj[kind]?.in.get(d.id)  || [];

      if (!outIds.length && !inIds.length) continue;
      hasAny = true;

      // Outbound
      for (const t of outIds) {
        const f = Graph.fileById.get(t);
        _appendConnRow(wrap, {
          direction: "out",
          count: 1,
          kind: kind,
          target: f?.label ?? t,
          targetSvc: f ? f.file.split("/")[0] : "",
          onClick: () => {
            if (f) {
              // Navigate to that file's service file view
              const svc = f.file.split("/")[0];
              if (!Graph.view.startsWith("files:" + svc)) {
                Graph.renderFileView(svc);
              }
              // Delay to let simulation settle, then select the file
              setTimeout(() => {
                const node = Graph.curNodes.find(n => n.id === t);
                if (node) Graph.selectFile(node);
              }, 600);
            }
          },
        });
      }

      // Inbound
      for (const s of inIds) {
        const f = Graph.fileById.get(s);
        _appendConnRow(wrap, {
          direction: "in",
          count: 1,
          kind: kind,
          target: f?.label ?? s,
          targetSvc: f ? f.file.split("/")[0] : "",
          onClick: () => {
            if (f) {
              const svc = f.file.split("/")[0];
              if (!Graph.view.startsWith("files:" + svc)) {
                Graph.renderFileView(svc);
              }
              setTimeout(() => {
                const node = Graph.curNodes.find(n => n.id === s);
                if (node) Graph.selectFile(node);
              }, 600);
            }
          },
        });
      }
    }

    if (!hasAny) {
      const empty = document.createElement("div");
      empty.style.cssText = "color:#334;font-size:11px;padding:4px 0";
      empty.textContent = "Enable edge types above to see connections";
      wrap.appendChild(empty);
    }
  }

  /* ---- Append one connection row ---- */
  function _appendConnRow(container, { direction, count, kind, target, targetSvc, onClick }) {
    const row = document.createElement("div");
    row.className = "conn-item";
    row.title = (direction === "out" ? "→ " : "← ") + target + (targetSvc ? " (" + targetSvc + ")" : "");

    // Arrow
    const arrow = document.createElement("span");
    arrow.className = "conn-arrow " + direction;
    arrow.textContent = direction === "out" ? "──" : "◄─";

    // Count
    const cnt = document.createElement("span");
    cnt.className = "conn-count " + kind;
    cnt.textContent = count > 1 ? String(count).padStart(3) : " ";

    // Kind badge
    const badge = document.createElement("span");
    badge.className = "conn-kind " + kind;
    badge.textContent = _shortKind(kind);

    // Arrow tip
    const tip = document.createElement("span");
    tip.className = "conn-arrow " + direction;
    tip.textContent = direction === "out" ? "─▶ " : "── ";

    // Target name
    const tgt = document.createElement("span");
    tgt.className = "conn-target";
    tgt.textContent = target;

    if (direction === "out") {
      row.append(arrow, cnt, badge, tip, tgt);
    } else {
      row.append(arrow, cnt, badge, tip, tgt);
    }

    row.addEventListener("click", onClick);
    container.appendChild(row);
  }

  function _shortKind(kind) {
    const m = { depends_on: "dep", tests_for: "test", inherits: "ext", implements: "impl" };
    return m[kind] || kind;
  }

  /* ---- Node info (name + path) ---- */
  function showNodeInfo(name, path) {
    $("node-info").style.display = "";
    $("ni-name").textContent = name;
    $("ni-path").textContent = path || "";
  }

  function hideNodeInfo() {
    $("node-info").style.display = "none";
    $("symbol-list").style.display = "none";
    $("conn-list").style.display = "none";
  }

  /* ---- Symbol list ---- */
  function showSymbolList(fileId) {
    const syms = graphData.symbolsByFile[fileId] || [];
    if (!syms.length) return;

    const el = $("sym-items");
    const wrap = $("symbol-list");
    wrap.style.display = "";
    el.innerHTML = "";

    const grouped = {};
    syms.forEach(s => { (grouped[s.kind] = grouped[s.kind] || []).push(s); });

    for (const [kind, items] of Object.entries(grouped)) {
      items.slice(0, 30).forEach(s => {
        const d = document.createElement("div");
        d.className = "sym-item";
        d.innerHTML = '<span class="sym-kind ' + kind + '">' + kind + '</span>' +
          _escHtml(s.name);
        if (s.line) d.title = "Line " + s.line;
        el.appendChild(d);
      });
      if (items.length > 30) {
        const d = document.createElement("div");
        d.className = "sym-item"; d.style.color = "#334";
        d.textContent = "… and " + (items.length - 30) + " more " + kind;
        el.appendChild(d);
      }
    }
  }

  function _escHtml(s) {
    const d = document.createElement("span");
    d.textContent = s;
    return d.innerHTML;
  }

  /* ---- Node list (folder tree) ---- */
  function buildNodeList(nodes, { colorFn, labelFn, subFn, onClickFn, pathFn }) {
    const section = $("node-list-section");
    const container = $("node-list");
    const countEl = $("node-list-count");
    container.innerHTML = "";

    if (!nodes.length) { section.classList.remove("visible"); return; }
    section.classList.add("visible");
    countEl.textContent = "(" + nodes.length + ")";

    // If pathFn is provided, build a folder tree; otherwise flat list
    if (pathFn) {
      _buildTree(container, nodes, { colorFn, labelFn, pathFn, onClickFn });
    } else {
      _buildFlat(container, nodes, { colorFn, labelFn, subFn, onClickFn });
    }
  }

  function _buildFlat(container, nodes, { colorFn, labelFn, subFn, onClickFn }) {
    const sorted = [...nodes].sort((a, b) => {
      const la = labelFn(a).toLowerCase(), lb = labelFn(b).toLowerCase();
      return la < lb ? -1 : la > lb ? 1 : 0;
    });

    for (const node of sorted) {
      _appendNodeItem(container, node, { colorFn, labelFn, subFn, onClickFn });
    }
  }

  function _buildTree(container, nodes, { colorFn, labelFn, pathFn, onClickFn }) {
    // Build folder structure
    const tree = {};
    for (const node of nodes) {
      const fullPath = pathFn(node) || labelFn(node);
      const parts = fullPath.replace(/\\/g, "/").split("/");
      let cursor = tree;
      for (let i = 0; i < parts.length - 1; i++) {
        const dir = parts[i];
        if (!cursor[dir]) cursor[dir] = { _children: {}, _files: [] };
        cursor = cursor[dir]._children;
      }
      // Leaf node
      const dirKey = parts.length > 1 ? parts[parts.length - 2] : "_root";
      if (!cursor._files) {
        // We're at a level that didn't have a folder entry yet
        cursor._files = [];
        cursor._children = cursor._children || {};
      }
      // Store at current level
      const parentPath = parts.slice(0, -1).join("/");
      if (!tree._byDir) tree._byDir = {};
      if (!tree._byDir[parentPath]) tree._byDir[parentPath] = [];
      tree._byDir[parentPath].push(node);
    }

    // Simpler approach: group by directory, sort dirs, render collapsible
    const byDir = {};
    for (const node of nodes) {
      const fullPath = (pathFn(node) || "").replace(/\\/g, "/");
      const lastSlash = fullPath.lastIndexOf("/");
      const dir = lastSlash >= 0 ? fullPath.substring(0, lastSlash) : "";
      if (!byDir[dir]) byDir[dir] = [];
      byDir[dir].push(node);
    }

    const sortedDirs = Object.keys(byDir).sort();

    // Find common prefix to trim
    let commonPrefix = "";
    if (sortedDirs.length > 1) {
      const first = sortedDirs[0], last = sortedDirs[sortedDirs.length - 1];
      let i = 0;
      while (i < first.length && i < last.length && first[i] === last[i]) i++;
      commonPrefix = first.substring(0, first.lastIndexOf("/", i) + 1);
    } else if (sortedDirs.length === 1 && sortedDirs[0].includes("/")) {
      commonPrefix = sortedDirs[0].substring(0, sortedDirs[0].lastIndexOf("/") + 1);
    }

    for (const dir of sortedDirs) {
      const displayDir = dir.substring(commonPrefix.length) || "/";
      const files = byDir[dir].sort((a, b) => {
        const la = labelFn(a).toLowerCase(), lb = labelFn(b).toLowerCase();
        return la < lb ? -1 : la > lb ? 1 : 0;
      });

      // Folder header
      const folder = document.createElement("div");
      folder.className = "nl-folder";

      const header = document.createElement("div");
      header.className = "nl-folder-header";

      const chevron = document.createElement("span");
      chevron.className = "nl-chevron open";
      chevron.textContent = "";

      const dirName = document.createElement("span");
      dirName.className = "nl-folder-name";
      dirName.textContent = displayDir;
      dirName.title = dir;

      const fileCount = document.createElement("span");
      fileCount.className = "nl-folder-count";
      fileCount.textContent = files.length;

      header.appendChild(chevron);
      header.appendChild(dirName);
      header.appendChild(fileCount);

      const contents = document.createElement("div");
      contents.className = "nl-folder-contents";

      // Collapse/expand
      header.addEventListener("click", () => {
        const isOpen = chevron.classList.toggle("open");
        contents.style.display = isOpen ? "" : "none";
      });

      for (const node of files) {
        _appendNodeItem(contents, node, {
          colorFn, labelFn,
          subFn: () => null, // path already shown via folder
          onClickFn,
        });
      }

      folder.appendChild(header);
      folder.appendChild(contents);
      container.appendChild(folder);
    }
  }

  /* ---- Nested checkbox folder tree ---- */
  let _treeCallbacks = {};
  let _allTreeFiles = [];

  function buildCheckboxTree(nodes, { colorFn, labelFn, pathFn, onClickFn, onCheckChange }) {
    const section = $("node-list-section"), container = $("node-list"), countEl = $("node-list-count");
    container.innerHTML = "";
    if (!nodes.length) { section.classList.remove("visible"); return; }
    section.classList.add("visible");
    countEl.textContent = "(" + nodes.length + ")";
    _allTreeFiles = nodes;
    _treeCallbacks = { onCheckChange, colorFn, labelFn, onClickFn, pathFn };

    // 1. Build raw tree
    const root = { ch: {}, files: [] };
    const mkNode = () => ({ ch: {}, files: [] });
    for (const node of nodes) {
      const fp = (pathFn(node) || "").replace(/\\/g, "/");
      const parts = fp.split("/");
      parts.pop(); // remove filename
      let cur = root;
      for (const p of parts) {
        if (!p) continue; // skip empty segments
        if (!cur.ch[p]) cur.ch[p] = mkNode();
        cur = cur.ch[p];
        // Defensive: ensure cur always has files array
        if (!cur.files) cur.files = [];
        if (!cur.ch) cur.ch = {};
      }
      cur.files.push(node);
    }

    // 2. Collapse single-child-no-files chains
    function collapse(node) {
      const result = { ch: {}, files: node.files || [] };
      for (let [name, child] of Object.entries(node.ch || {})) {
        let cur = child;
        while (cur && Object.keys(cur.ch || {}).length === 1 && (cur.files || []).length === 0) {
          const [k, v] = Object.entries(cur.ch)[0];
          name += "/" + k;
          cur = v;
        }
        if (cur) result.ch[name] = collapse(cur);
      }
      return result;
    }
    const tree = collapse(root);

    // 3. Toolbar
    const toolbar = document.createElement("div");
    toolbar.style.cssText = "display:flex;gap:6px;margin-bottom:6px;";
    const mkBtn = (txt, checked) => {
      const b = document.createElement("button"); b.textContent = txt; b.className = "tree-btn";
      b.addEventListener("click", () => {
        container.querySelectorAll(".nl-folder").forEach(f => {
          if (f.style.display !== "none") { const cb = f.querySelector(":scope > .nl-folder-header > .folder-cb"); if (cb) cb.checked = checked; }
        });
        _fireCheck(container);
      });
      return b;
    };
    toolbar.appendChild(mkBtn("All", true));
    toolbar.appendChild(mkBtn("None", false));
    container.appendChild(toolbar);

    // 4. Render
    _renderTree(container, tree, colorFn, labelFn, onClickFn, container);
  }

  function _renderTree(parent, node, colorFn, labelFn, onClickFn, rootContainer) {
    for (const key of Object.keys(node.ch).sort()) {
      const child = node.ch[key];
      const total = _countAll(child);

      const folder = document.createElement("div"); folder.className = "nl-folder";
      const header = document.createElement("div"); header.className = "nl-folder-header";

      const cb = document.createElement("input"); cb.type = "checkbox"; cb.className = "folder-cb";
      cb.addEventListener("change", () => {
        // Propagate to ALL descendant checkboxes
        folder.querySelectorAll(".folder-cb").forEach(c => { c.checked = cb.checked; });
        _fireCheck(rootContainer);
      });
      cb.addEventListener("click", e => e.stopPropagation());

      const chevron = document.createElement("span"); chevron.className = "nl-chevron";
      const name = document.createElement("span"); name.className = "nl-folder-name"; name.textContent = key;
      const count = document.createElement("span"); count.className = "nl-folder-count"; count.textContent = total;
      header.append(cb, chevron, name, count);

      const contents = document.createElement("div"); contents.className = "nl-folder-contents"; contents.style.display = "none";
      header.addEventListener("click", e => {
        if (e.target === cb) return;
        chevron.classList.toggle("open");
        contents.style.display = chevron.classList.contains("open") ? "" : "none";
      });

      // Nested folders first (IDE order)
      _renderTree(contents, child, colorFn, labelFn, onClickFn, rootContainer);

      // Files at bottom
      for (const file of [...(child.files||[])].sort((a, b) => labelFn(a).toLowerCase() < labelFn(b).toLowerCase() ? -1 : 1)) {
        const item = document.createElement("div"); item.className = "nl-item"; item.dataset.nodeId = file.id;
        const dot = document.createElement("span"); dot.className = "nl-dot"; dot.style.background = colorFn(file);
        const nameEl = document.createElement("div"); nameEl.className = "nl-name";
        nameEl.appendChild(dot); nameEl.appendChild(document.createTextNode(labelFn(file)));
        item.appendChild(nameEl);
        item.addEventListener("click", e => { e.stopPropagation(); onClickFn(file); });
        contents.appendChild(item);
      }

      folder.appendChild(header);
      folder.appendChild(contents);
      parent.appendChild(folder);
    }
  }

  function _countAll(node) {
    let c = node.files.length;
    for (const v of Object.values(node.ch)) c += _countAll(v);
    return c;
  }

  function _fireCheck(rootContainer) {
    // For each checked folder, collect file IDs from its direct .nl-item children
    // (not from nested sub-folders — those have their own checkbox)
    const selectedIds = new Set();
    rootContainer.querySelectorAll(".folder-cb:checked").forEach(cb => {
      const folder = cb.closest(".nl-folder");
      if (!folder) return;
      const contents = folder.querySelector(":scope > .nl-folder-contents");
      if (!contents) return;
      contents.querySelectorAll(":scope > .nl-item[data-node-id]").forEach(item => {
        selectedIds.add(item.dataset.nodeId);
      });
    });
    if (_treeCallbacks.onCheckChange) _treeCallbacks.onCheckChange(selectedIds);
  }

  /** Reveal a node in the tree: expand parent folders, scroll into view, highlight */
  function revealAndHighlight(nodeId) {
    const container = $("node-list");
    container.querySelectorAll(".nl-item.active").forEach(el => el.classList.remove("active"));
    if (!nodeId) return;
    const item = container.querySelector('[data-node-id="' + nodeId + '"]');
    if (!item) return;
    let el = item.parentElement;
    while (el && el !== container) {
      if (el.classList.contains("nl-folder-contents")) {
        el.style.display = "";
        const chevron = el.previousElementSibling?.querySelector(".nl-chevron");
        if (chevron) chevron.classList.add("open");
      }
      el = el.parentElement;
    }
    item.classList.add("active");
    item.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function _appendNodeItem(container, node, { colorFn, labelFn, subFn, onClickFn }) {
    const item = document.createElement("div");
    item.className = "nl-item";
    item.dataset.nodeId = node.id;

    const dot = document.createElement("span");
    dot.className = "nl-dot";
    dot.style.background = colorFn(node);

    const nameEl = document.createElement("div");
    nameEl.className = "nl-name";
    nameEl.appendChild(dot);
    nameEl.appendChild(document.createTextNode(labelFn(node)));

    item.appendChild(nameEl);

    if (subFn) {
      const sub = subFn(node);
      if (sub) {
        const pathEl = document.createElement("div");
        pathEl.className = "nl-path";
        pathEl.textContent = sub;
        item.appendChild(pathEl);
      }
    }

    item.addEventListener("click", (e) => {
      e.stopPropagation();
      container.closest("#node-list").querySelectorAll(".nl-item.active").forEach(el => el.classList.remove("active"));
      item.classList.add("active");
      onClickFn(node);
    });

    container.appendChild(item);
  }

  function highlightNodeListItem(nodeId) {
    const container = $("node-list");
    container.querySelectorAll(".nl-item.active").forEach(el => el.classList.remove("active"));
    if (nodeId) {
      const item = container.querySelector('[data-node-id="' + nodeId + '"]');
      if (item) { item.classList.add("active"); item.scrollIntoView({ block: "nearest" }); }
    }
  }

  function hideNodeList() {
    $("node-list-section").classList.remove("visible");
  }

  /* ---- Extension filters ---- */
  let activeExts = new Set();

  function buildExtFilters() {
    const container = $("ext-filters");
    container.innerHTML = "";
    graphData.topExts.forEach(ext => {
      const pill = document.createElement("span");
      pill.className = "ext-pill active";
      pill.textContent = "." + ext + " (" + graphData.extCounts[ext] + ")";
      pill.dataset.ext = ext;
      pill.addEventListener("click", () => {
        pill.classList.toggle("active");
        _updateActiveExts();
        Graph.filterCurrentView();
      });
      container.appendChild(pill);
    });
    _updateActiveExts();
  }

  function _updateActiveExts() {
    activeExts = new Set();
    document.querySelectorAll(".ext-pill.active").forEach(p => activeExts.add(p.dataset.ext));
  }

  function getActiveExts() { return activeExts; }

  /* ---- Search: filter sidebar + dim graph ---- */
  function _filterSidebar(q) {
    const container = $("node-list");
    if (!q) {
      // Show everything
      container.querySelectorAll(".nl-folder, .nl-item").forEach(el => { el.style.display = ""; });
      return;
    }
    // Mark each file item as match/no-match
    container.querySelectorAll(".nl-item").forEach(item => {
      const text = (item.querySelector(".nl-name")?.textContent || "").toLowerCase();
      item.style.display = text.includes(q) ? "" : "none";
      item.dataset.match = text.includes(q) ? "1" : "";
    });
    // For each folder (bottom-up): show if folder name matches OR any child matches
    // Process deepest first by reversing the NodeList
    const allFolders = [...container.querySelectorAll(".nl-folder")].reverse();
    for (const folder of allFolders) {
      const folderName = (folder.querySelector(":scope > .nl-folder-header .nl-folder-name")?.textContent || "").toLowerCase();
      const nameMatch = folderName.includes(q);
      const contents = folder.querySelector(":scope > .nl-folder-contents");
      // Check if any direct child items or child folders are visible
      let hasVisibleChild = false;
      if (contents) {
        for (const child of contents.children) {
          if (child.style.display !== "none") { hasVisibleChild = true; break; }
        }
      }
      if (nameMatch) {
        // Folder name matches — show folder and all its contents
        folder.style.display = "";
        if (contents) contents.querySelectorAll(".nl-item, .nl-folder").forEach(el => { el.style.display = ""; });
      } else if (hasVisibleChild) {
        // Child matches — show folder, expand it
        folder.style.display = "";
        if (contents) { contents.style.display = ""; const chev = folder.querySelector(":scope > .nl-folder-header .nl-chevron"); if (chev) chev.classList.add("open"); }
      } else {
        folder.style.display = "none";
      }
    }
    // Also filter flat list items (service view)
    container.querySelectorAll(":scope > .nl-item").forEach(item => {
      const text = ((item.querySelector(".nl-name")?.textContent || "") + " " + (item.querySelector(".nl-path")?.textContent || "")).toLowerCase();
      item.style.display = text.includes(q) ? "" : "none";
    });
  }
  $("search").addEventListener("input", e => {
    const q = e.target.value.toLowerCase().trim();
    Graph.applySearch(q);
    _filterSidebar(q);
  });

  /* ---- Back ---- */
  $("back-btn").addEventListener("click", () => {
    if (Graph.view.startsWith("symbols:")) {
      const fileId = Graph.view.split(":")[1];
      const f = Graph.fileById.get(fileId);
      if (f) {
        Graph.renderFileView(f.file.split("/")[0]);
      } else {
        Graph.renderServiceView();
      }
    } else {
      Graph.renderServiceView();
    }
  });

  /* ---- Edge type checkboxes ---- */
  document.querySelectorAll("[data-etype]").forEach(cb => {
    cb.addEventListener("change", () => Graph.onEdgeFilterChange());
  });

  $("show-all-cb").addEventListener("change", e => {
    if (e.target.checked) { Graph.drawAllEdgesInView(); }
    else { Graph.onEdgeFilterChange(); }
  });

  /* ---- Public API ---- */
  return {
    showServiceConnections,
    showFileConnections,
    showNodeInfo,
    hideNodeInfo,
    showSymbolList,
    buildExtFilters,
    getActiveExts,
    buildNodeList,
    buildCheckboxTree,
    highlightNodeListItem,
    revealAndHighlight,
    hideNodeList,
  };

})();
