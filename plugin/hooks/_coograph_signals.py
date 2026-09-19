"""Shim: loads the canonical Retro signal store from .github/retro/.

The real module is .github/retro/_coograph_signals.py, so that the analyzer
(retro.py) and every hook share one file, and so projects set up for tools
other than Claude Code still have the analyzer. This shim exists because the
hooks import by bare name from their own directory.

Resolution order for the project root:
  1. CLAUDE_PROJECT_DIR (set by Claude Code for every hook, in plugin mode too)
  2. the parent of .claude/hooks/ (project-level hook copy)
  3. the current working directory

On success this module replaces itself in sys.modules with the canonical
one, so `import _coograph_signals as signals` yields the real module.
Raises ImportError when .github/retro/ is not installed; hooks catch that
and run without Retro.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_REL = Path(".github") / "retro" / "_coograph_signals.py"


def _locate() -> Path | None:
    roots: list[Path] = []
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        roots.append(Path(env))
    here = Path(__file__).resolve().parent
    roots.append(here.parent.parent)
    roots.append(Path.cwd())
    for root in roots:
        candidate = root / _REL
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


_path = _locate()
if _path is None:
    raise ImportError("Retro is not installed here: .github/retro/_coograph_signals.py is missing")

_spec = importlib.util.spec_from_file_location(__name__, _path)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot load {_path}")
_module = importlib.util.module_from_spec(_spec)
sys.modules[__name__] = _module
_spec.loader.exec_module(_module)
