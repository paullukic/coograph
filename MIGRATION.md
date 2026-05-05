# Migration Notes

`sync.py` never overwrites user-owned files (`CLAUDE.md`, `.github/copilot-instructions.md`, `openspec/config.yaml` — see `SKIP_FILES` in `.github/sync.py`). When the template gains rules that must live in those files, existing users have to apply them by hand. Entries below are in reverse chronological order — apply any you haven't yet.

---

## 2026-04-15 — HARD RULE banners (code-graph + OpenSpec)

Two non-negotiable rules were added to the template's `CLAUDE.md` and `.github/copilot-instructions.md`. Paste both banners verbatim near the top of each file in your project (above the first `##` heading). Keep the exact wording — agents are trained to look for these literal strings.

```markdown
> **🛑 HARD RULE — CODE-GRAPH FIRST.** Before any codebase search, navigation, tracing, or exploration you MUST use the code-graph MCP tools first (`mcp__code-graph__*`). Only fall back to `sqlite3 .code-graph/graph.db`, and only then to `Glob`/`Grep`/`Read`, if the code-graph DB is genuinely NOT present in the workspace. Convenience is not a valid reason to skip.

> **🛑 HARD RULE — OPENSPEC OR STOP.** For any change that modifies 2+ files, touches a spec, alters a public interface, or adds new behavior, you MUST create an OpenSpec in `openspec/changes/<date>-<slug>/` and WAIT for user approval BEFORE writing code. Exemptions are narrow and literal:
> - Typo fix in a single file
> - Comment/docstring-only edit
> - Config-value bump the user explicitly dictates (e.g., "set X=2")
> - Follow-up fix for an already-approved, in-progress OpenSpec
>
> "Trivial," "obvious," "I already know what to do," "small," and "just one tweak" are NOT exemptions. If in doubt → propose, don't code.
```

Also update two phrases elsewhere in those same files so nothing contradicts the banners:

- In the **"When the workflow does NOT apply"** list: replace the bullet `Single-file fixes, typos, trivial changes — just do it.` with `Exempt changes (narrow literal list from the OPENSPEC OR STOP HARD RULE above): typo fix in a single file, comment/docstring-only edit, user-dictated config-value bump, follow-up for an already-approved in-progress OpenSpec. "Trivial", "obvious", "small", "just one tweak" are NOT exemptions — when in doubt, propose.`
- In the **Bug reports** bullet: replace `If fix is trivial, just fix it.` with `If the fix is a one-line exempt change (per literal list above), apply it.`

Verify:

```bash
grep -l "HARD RULE — CODE-GRAPH FIRST" CLAUDE.md .github/copilot-instructions.md
grep -l "HARD RULE — OPENSPEC OR STOP" CLAUDE.md .github/copilot-instructions.md
```

Both files should appear in each output.
