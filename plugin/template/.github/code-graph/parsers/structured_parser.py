"""Structured file parser — XML, YAML, SQL, JSON, properties.

Extracted from the original builder.py without changes to behavior.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import register, nid

STACK = "structured"
EXTENSIONS = frozenset({".xml", ".yaml", ".yml", ".sql", ".properties", ".json"})


@register(STACK, EXTENSIONS)
def parse(path: Path, rel: str, nodes: list, edges: list) -> None:
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    ext = path.suffix.lower()
    if ext == ".xml":
        _parse_xml(path, rel, fid, nodes, edges)
    elif ext in (".yaml", ".yml"):
        _parse_yaml(path, rel, fid, nodes, edges)
    elif ext == ".sql":
        _parse_sql(path, rel, fid, nodes, edges)
    # .json and .properties: file node only (no internal structure extraction)


def _parse_xml(path: Path, rel: str, fid: str, nodes: list, edges: list) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return

    # Liquibase: extract table names from changeSets
    for m in re.finditer(r'tableName="(\w+)"', text):
        table = m.group(1)
        tid = nid("table", rel, table)
        nodes.append((tid, "table", table, rel, None, None))
        edges.append((fid, tid, "contains"))

    # Spring beans: class references
    for m in re.finditer(r'class="([\w.]+)"', text):
        edges.append((fid, m.group(1), "imports"))


def _parse_yaml(path: Path, rel: str, fid: str, nodes: list, edges: list) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return

    # OpenAPI: extract path definitions
    for m in re.finditer(r"^  (/[\w/{}\-]+):", text, re.MULTILINE):
        epath = m.group(1)
        eid = nid("endpoint", rel, epath)
        nodes.append((eid, "endpoint", epath, rel, None, None))
        edges.append((fid, eid, "contains"))

    # $ref references to other files
    for m in re.finditer(r"\$ref:\s*['\"]?([^'\"#\s]+)", text):
        ref = m.group(1).strip()
        if ref and not ref.startswith("#"):
            edges.append((fid, ref, "imports"))


def _parse_sql(path: Path, rel: str, fid: str, nodes: list, edges: list) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return

    for m in re.finditer(
        r'(?:CREATE\s+TABLE|ALTER\s+TABLE|INSERT\s+INTO|FROM|JOIN)\s+'
        r'(?:IF\s+NOT\s+EXISTS\s+)?(\w+)',
        text, re.IGNORECASE,
    ):
        table = m.group(1).lower()
        if table not in ('select', 'where', 'set', 'values', 'into', 'table'):
            tid = nid("table", rel, table)
            nodes.append((tid, "table", table, rel, None, None))
            edges.append((fid, tid, "contains"))
