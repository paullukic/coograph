# Layout: instruction files by tier

An agent reads its instruction files before it reads any code, so every byte in
them is paid on every task. Left alone they grow: maps turn into changelogs, one
feature is described in several files, hard rules are copied into every root
file. `layout.py` holds them to a declared layout and fails loudly when they
drift.

## The three tiers, plus gotchas

| tier | what | default budget | loaded |
|---|---|---|---|
| always-loaded | root `CLAUDE.md`, `AGENTS.md`, `.github/copilot-instructions.md`, plus every file they pull in with `@path` | 9000 tokens combined | every session |
| router | `<workspace>/AGENTS.md`: commands, gotcha pointers, an area index. Pair it with a one-line `<workspace>/CLAUDE.md` holding `@AGENTS.md`; Claude Code loads nested `CLAUDE.md` only when it touches files in that folder | 2000 each | on entering the workspace |
| doc | `docs/features/<area>.md`, one per product area, current state only, with `paths:` frontmatter | 8000 each | on demand |
| gotchas | `GOTCHAS.md` entries, never always-loaded | 8000 per file, 800 bytes per entry | by the gotcha hook, when an entry's `paths:` or `commands:` match |

Content rules: no dated sections (history lives in OpenSpec and git), bullet
lists over wide tables, each rule stated in one file only.

Tokens are `bytes // 4`, the same estimate Retro uses. `@` imports are followed
relative to the importing file, at most 4 hops (Claude Code's limit), each file
counted once; `@` inside code spans and fences is not an import.

## The config

`.github/layout/layout.json` is the project's. It is created from
`layout.seed.json` the first time (init, sync, or `--merge-seed`) and never
overwritten; new seed keys are added without touching existing values.

```json
{
  "always_loaded": ["CLAUDE.md", "AGENTS.md", ".github/copilot-instructions.md"],
  "routers": ["*/AGENTS.md", "*/*/AGENTS.md"],
  "docs": ["docs/features/*.md"],
  "gotchas": ["GOTCHAS.md", "*/GOTCHAS.md", "*/*/GOTCHAS.md"],
  "budgets": {"always_loaded": 9000, "router": 2000, "doc": 8000, "gotchas": 8000},
  "guard": {"ignore": ["**/*.lock", "openspec/**", "**/*.md"], "skip_marker": "[skip docs]"},
  "structural_factor": 1.25
}
```

Optional, not in the seed: `"guard": {"roots": ["apps/web/src/", "packages/core/src/"], ...}`
(see `--guard` below).

Globs are anchored at the repo root: `**` crosses directories, `*` and `?` do
not. In a doc's or gotcha's `paths:`, a pattern without `/` also matches a file
name at any depth. A single-package repo sets `routers` to `[]`; a monorepo
lists its workspaces.

## Feature docs

```markdown
---
paths:
  - apps/web/src/auth/**
  - packages/core/auth/**
---
# Auth

## Core
- ...
## Web
- ...
```

One file per product area, covering every workspace. Describe what is true now.

## Gotchas

`GOTCHAS.md` holds traps learned the hard way, one `##` entry each:

```markdown
## expo-export-ignores-shell-env
- **Symptom:** `expo export` builds with the old API URL after `export API_URL=...`
- **Cause:** `.env` wins over the shell for `expo export`.
- **Fix / rule:** change `.env.production`, never the shell.
- **paths:** `apps/mobile/**`, `app.config.ts`
- **commands:** `expo export`
- **confirmed:** 2026-10-01
```

`Symptom`, `Cause`, `Fix / rule`, `paths` and `confirmed` are required;
`commands` is optional (substrings of a shell command). In Claude Code,
`.claude/hooks/gotcha-surface.py` puts a matching entry in front of the model
once per session, just before the edit or command it applies to. Other tools
reach the file through the routing table in `AGENTS.md`.

An entry whose `paths:` match no file is reported as stale; `/coograph-retro`
proposes pruning it.

## Commands

```bash
python3 .github/layout/layout.py --budget            # one line per tier; exit 1 when anything is over
python3 .github/layout/layout.py --json              # full measurement (what Retro reads)
python3 .github/layout/layout.py --guard BASE HEAD   # exit 1 when covered code changed but its doc did not
python3 .github/layout/layout.py --guard BASE HEAD --strict  # also exit 1 on changed code no doc covers
python3 .github/layout/layout.py --merge-seed        # create layout.json, or add new seed keys
python -m unittest discover -s .github/layout/tests  # tests (coograph repo only)
```

`--budget` also fails on a missing `@` import (Claude Code skips it without a
word) and on an invalid or duplicate-id gotcha (the hook never shows it), and
prints a **structural** verdict: the always-loaded tier is over budget times
`structural_factor`, a router or doc is over twice its budget, or a file has
three or more dated headings. A structural project needs
`/coograph-docs-restructure`, not small edits.

`--guard` maps each changed source path to the feature docs whose `paths:`
cover it, and fails when none of them changed in the same diff. Paths no doc
covers are listed as `uncovered` and never fail, unless `--strict` is given:
then each is printed as `UNCOVERED  <path>` and the guard exits 1, so coverage
cannot shrink silently. A path deleted between BASE and HEAD is never reported
uncovered (a deleted covered path still needs its doc updated). Skip it for one
PR with the skip marker in the PR title (CI passes the title as
`COOGRAPH_PR_TITLE`), or set `COOGRAPH_LAYOUT_SKIP=1`.

`guard.roots` (optional, absent by default) limits the guard to the parts of the
repo it should watch, for example a monorepo's `apps/web/src/` and
`packages/core/src/`. A changed path counts only when it equals a root or lies
under it (a trailing `/` is optional; a root is a plain repo-relative path as
git prints it, no globs, no leading `./`); everything else is neither a failure nor
uncovered, even when a doc's `paths:` covers it. Without `roots` the whole repo
is checked, as before.

## CI and pre-commit (opt-in)

`/coograph-init` offers both:

- `coograph-layout.yml` goes to `.github/workflows/`. It runs `--budget` and
  `--guard` on every pull request, and again when the PR title is edited (so
  adding the skip marker takes effect). Sync refreshes it only while its first
  line carries `coograph:managed`; delete that line to keep your own edits.
- `pre-commit` goes to `.git/hooks/` and runs `--budget`. Bypass once with
  `git commit --no-verify`.
