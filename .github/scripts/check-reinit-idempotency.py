#!/usr/bin/env python3
"""Re-init idempotency check (issue #4).

`/coograph-init` must not clobber a finished install on a second run. The State C
test fixture `examples/already-initialized/` represents such a finished install: by
definition it carries ZERO `_TBD_` / `<!-- FILL` markers (those are the only signal
the skill uses to tell a customized file from a template-untouched one).

This check asserts the fixture stays marker-free. If a future template change leaves
a marker behind, the fixture would silently stop representing State C and the
idempotency guarantee would rot unnoticed; this turns that into a loud CI failure.

The full "second init produces zero instruction-file diff" assertion is inherently
interactive (init asks questions), so it is a documented manual step in the change's
tasks.md, not automated here.

stdlib only. Run from anywhere:
    uv run .github/scripts/check-reinit-idempotency.py
    python .github/scripts/check-reinit-idempotency.py

Exit 0 when the fixture is marker-free, 1 on any marker or a missing fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Repo root = two levels up from this file (.github/scripts/check-reinit-idempotency.py).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

FIXTURE_DIR = "examples/already-initialized"
MARKERS = ("_TBD_", "<!-- FILL")


def find_markers(root: Path) -> list[str]:
    """Return 'path:line  marker' for every marker hit under root."""
    hits: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable; fixtures are text, skip noise
        for lineno, line in enumerate(text.splitlines(), start=1):
            for marker in MARKERS:
                if marker in line:
                    rel = path.relative_to(REPO_ROOT).as_posix()
                    hits.append(f"{rel}:{lineno}  contains {marker!r}")
    return hits


def main() -> int:
    fixture = REPO_ROOT / FIXTURE_DIR
    if not fixture.is_dir():
        print(f"FAIL {FIXTURE_DIR}  missing fixture directory")
        return 1

    hits = find_markers(fixture)
    if hits:
        for h in hits:
            print(f"FAIL {h}")
        print()
        print(f"{FIXTURE_DIR} must be a finished State C tree with zero markers; "
              f"found {len(hits)}.")
        return 1

    file_count = sum(1 for p in fixture.rglob("*") if p.is_file())
    print(f"PASS {FIXTURE_DIR}  marker-free ({file_count} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
