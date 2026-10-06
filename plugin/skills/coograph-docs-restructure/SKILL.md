---
name: coograph-docs-restructure
description: Bring a project's instruction and map files back under the tier budgets. Takes stock with layout.py, works out the project's shape, writes a project-specific OpenSpec (areas, layout.json, gotcha extraction), and after approval migrates one area per agent with every kept fact checked against the code. Use when layout.py --budget or a retro reports STRUCTURAL, or when maps have turned into changelogs.
argument-hint: Optional. An area name to migrate just that area of an already-approved restructure.
license: MIT
metadata:
  author: coograph
  version: "1.0"
---

Restructure the project's instruction files into the three tiers in
`.github/layout/README.md`: always-loaded root files (9K combined), workspace
routers (about 2K each), and on-demand feature docs (8K each), plus `GOTCHAS.md`.
Two phases with a hard stop between them: **Propose** writes an OpenSpec and
stops; **Apply** runs only after the user approves it.

Read `.github/layout/README.md` once before starting. It defines the tiers, the
config, the feature-doc frontmatter and the gotcha format.

The rule that matters most: **no current-state fact is lost, and no stale fact
survives.** Old map sections are often out of date. Every fact you keep is
checked against the code; every fact you drop is listed with a reason.

---

## Step 0: Resume or start

Look for a non-archived `openspec/changes/*-docs-restructure/`.

- **Found, not yet approved:** show it and ask whether to continue with it or discard it. Never start a second one alongside it.
- **Found and approved:** this is a resume. Go to Phase 2 and continue at the first unticked task in its `tasks.md`. Do not re-run Phase 1. Do not rewrite `notes/` or `.coograph/layout-before.json`: they hold the only record of the original facts and the before numbers.
- **An area name was given** (`/coograph-docs-restructure auth`): it applies only to an approved restructure. Run just that area's task. If no approved restructure exists, say so and stop.
- **Not found:** Phase 1.

---

## Phase 1: Propose

### Step 1: Take stock

```bash
python3 .github/layout/layout.py --budget
mkdir -p .coograph
[ -f .coograph/layout-before.json ] || python3 .github/layout/layout.py --json > .coograph/layout-before.json
```

If `.github/layout/layout.py` is missing, the project predates the layout
checker: tell the user to sync coograph (`git pull` in the coograph checkout) or
re-run `/coograph-init`, and stop.

From the JSON, record per file: tier, tokens, over budget, dated headings,
duplicate paragraphs, table padding. These are the "before" numbers for the
proposal; copy them, do not recompute.

Then list every instruction-like file the config does not know about yet, so
nothing is missed: `**/AGENTS.md`, `**/CLAUDE.md`, `**/*.instructions.md`,
`docs/**/*.md` that describe behaviour, `CONVENTIONS.md`, `.cursor/rules/*`.
Use the code-graph first (`get_minimal_context`), then `git ls-files` patterns.

### Step 2: Work out the shape

- **Workspaces.** From `package.json` `workspaces`, `pnpm-workspace.yaml`,
  `turbo.json`, `nx.json`, `go.work`, the `[workspace]` table of `Cargo.toml`,
  or top-level directories that hold their own manifest. None means a
  single-package repo: no routers.
- **Tools in use.** Which of `CLAUDE.md`, `AGENTS.md`,
  `.github/copilot-instructions.md`, `.cursor/`, `.windsurfrules`,
  `CONVENTIONS.md`, `.clinerules` exist. Every rule must stay reachable from
  each tool's entry file.
- **Product areas.** Group map sections by the feature they describe, not by
  the workspace they sit in: "auth" spans web, mobile, core and functions. Read
  the headings of every map; a dated heading (`## Login (openspec 2026-09-01)`)
  names an area and a change, so several dated headings collapse into one area.
  Aim for 5 to 15 areas. An area whose current state will not fit in 8K is two
  areas.
- **Hard rules.** Find every rule stated in more than one root file
  (`duplicate_paragraphs` lists the exact ones; also look for the same rule
  reworded). Each gets one home: hard rules and workflow in `AGENTS.md`, code
  conventions in `.github/copilot-instructions.md`, Claude-only extras in
  `CLAUDE.md`, which imports the other two with `@`.
- **Gotchas.** Every trap buried in a map: a symptom with a non-obvious cause
  (environment, deploy, tooling, an error message that points the wrong way).
  Each becomes a `GOTCHAS.md` entry with `paths:` (and `commands:` where a
  command triggers it).

### Step 3: Write the OpenSpec

`openspec/changes/<YYYY-MM-DD>-docs-restructure/` with the usual files:

- `proposal.md`: Why (the before numbers and the structural reasons, copied
  from Step 1), Goals (the after budgets), the area table, Decisions (where each
  hard rule lives; which files become routers; what happens to each old map),
  Risks.
- `layout.json` proposal in the Decisions section: `always_loaded`, `routers`
  (one glob per workspace), `docs`, `gotchas`, budgets. Keep the seed budgets
  unless the user asks otherwise.
- `notes/areas/<area>.md`, one per area: every fact the old files state about
  it, one line each, with its source (`apps/web/AGENTS.md § Login`). This is
  the fact list Apply ticks off.
- `notes/gotchas.md`: every gotcha candidate with its source.
- `notes/rules.md`: every rule in the root files, its current homes, and its
  one new home.
- `tasks.md`, in this order:
  1. one task per area (`docs/features/<area>.md`, every fact in
     `notes/areas/<area>.md` ticked or dropped with a reason);
  2. `GOTCHAS.md` (every candidate placed or dropped with a reason);
  3. routers (each workspace's `AGENTS.md` cut to commands, gotcha pointers and
     an area index, plus a one-line `<workspace>/CLAUDE.md` holding
     `@AGENTS.md` when Claude Code is in use);
  4. root files (rules de-duplicated per `notes/rules.md`, routing table
     filled);
  5. `.github/layout/layout.json`;
  6. verification: `layout.py --budget` exits 0, every `notes/areas/*.md` line
     is ticked or dropped, `/coograph-review` run.

**Stop.** Tell the user what the restructure will do in five lines (areas,
files removed, files created, before and after budgets) and wait for approval.
Do not edit any instruction file before approval.

---

## Phase 2: Apply (after approval)

Work through `tasks.md` in order.

### Areas: one agent each

For each area task, delegate to one subagent (the `@Explore` agent for reading,
then write the doc yourself, or one general agent per area where the tool
supports it). Give it:

- the area's `notes/areas/<area>.md` fact list;
- the source sections, quoted;
- the template below;
- the instruction: **check every fact against the code with the code-graph
  first** (`get_minimal_context`, `query_graph`), then by reading the files.
  Keep a fact only when the code confirms it. Mark it `[x]` with the confirming
  `file:line`, or `[dropped: <reason>]` (removed from the code, contradicted by
  the code, history rather than current state, duplicate of another area).

Feature doc template:

```markdown
---
paths:
  - <glob for every directory this area's code lives in, across workspaces>
---
# <Area>

<one paragraph: what this area does for the user>

## Core
- <current-state facts, bullets, no dates>
## Web
- ...
## Mobile
- ...
## Functions / backend
- ...
## Rules
- <constraints specific to this area>
```

Bullets, not wide tables (a table padded by a formatter costs more than its
text). No dated headings, no "added in", no "(openspec ...)": history lives in
`openspec/changes/archive/` and git. Keep each doc under 8K tokens
(`layout.py --budget` checks it).

### Gotchas, routers, root files

- `GOTCHAS.md`: entries in the format of `.github/layout/README.md`, each under
  800 bytes. A gotcha you cannot confirm is still current goes under
  `notes/gotchas.md` as dropped, with the reason.
- Routers: commands for that workspace, the gotcha pointer, and an area index
  (`auth → docs/features/auth.md`). Nothing else. About 2K tokens.
- Root files: apply `notes/rules.md`. Fill the routing table in `AGENTS.md`
  (`Touching <glob> → read docs/features/<area>.md`).

### Verify

```bash
python3 .github/layout/layout.py --budget
python3 .github/layout/layout.py --json > .coograph/layout-after.json
```

`--budget` must exit 0. Report before and after per tier from the two JSON
files. Every line in every `notes/areas/*.md` and `notes/gotchas.md` is ticked
or dropped with a reason; count both and report the counts. Then run
`/coograph-review` on the change.

If `--budget` still fails, the area split is wrong: split the over-budget doc,
update the OpenSpec, and say so. Do not trim facts to fit.

## Guardrails

- No instruction file is edited before the user approves the OpenSpec.
- No fact is kept without a code check, and no fact is dropped without a reason
  in the notes.
- No dated sections in any new file.
- Each rule is stated in exactly one file.
- `GOTCHAS.md` is never always-loaded: never `@`-import it.
- The project's `layout.json` is the user's: propose its contents in the
  OpenSpec, write it only in Apply.
