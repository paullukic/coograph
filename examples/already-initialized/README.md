# Fixture: already-initialized (State C)

A finished Coograph install for a fictional project (`acme-web`, Next.js + TypeScript
+ Prisma + Vitest), used as a test fixture for idempotent re-init (issue #4).

**Invariant:** every file here is a *customized* State C file — zero placeholder
markers (the TBD and FILL sentinels the init skill keys off). `check-reinit-idempotency.py`
asserts this; if a template change leaves a marker behind, the check fails loudly
instead of silently passing.

**What it proves:** running `/coograph-init` against a copy of this tree (same tool
selection) must classify it State C and produce zero diff to the instruction files
(`.github/copilot-instructions.md`, `CLAUDE.md`, `AGENTS.md`, `openspec/config.yaml`).

This is the single fixture issue #4 needs. The broader finished-sample set
(Next.js / Django / Go) is issue #5.
