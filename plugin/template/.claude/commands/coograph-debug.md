Diagnose the bug or build error below. Find the root cause with minimal investigation, then apply the smallest possible fix.

## Phase 0 — Orient with Code-Graph (MANDATORY — non-negotiable)

**Before reading any file or running any search**, this is the HARD RULE — code-graph first, no exceptions:
1. Call `get_minimal_context(task="debug <symptom>")` then `detect_changes()`. ALWAYS start here. Use `detect_changes()` risk scores first — recent high-risk changes are the most likely culprit. Use the returned file list to focus investigation.
2. Fall back to `sqlite3 .code-graph/graph.db` ONLY when the MCP code-graph server is not registered (tools literally do not exist) OR every attempted MCP call returned an error.
3. Fall back to standard search/read tools ONLY when Step 1 AND Step 2 are both impossible because the code-graph DB is absent from the workspace.

"Slow", "unwieldy", "it's a simple bug" are NOT valid reasons to bypass. When tracing call chains use `query_graph("callers_of", fn)` and `query_graph("callees_of", fn)` before reading files. Validate every hypothesis directly in source regardless of graph output.

## Protocol

### For Runtime Bugs

1. **REPRODUCE**: Can you trigger it reliably? What is the minimal reproduction? Consistent or intermittent?
2. **GATHER EVIDENCE** (parallel when possible):
   - Read full error messages and stack traces — every word, not just the first line.
   - Check recent changes: `git log --oneline -10`, `git blame` on suspect lines.
   - Find working examples of similar code in the codebase.
   - Read the actual code at error locations.
3. **HYPOTHESIZE**: Compare broken vs working code. Trace data flow from input to error. Document one hypothesis before investigating further. Identify what test would prove/disprove it.
4. **FIX**: Apply ONE change. Predict the test that proves the fix. Check for the same pattern elsewhere.
5. **VERIFY**: Run the failing test/build to confirm the fix works. Verify no regressions.

### For Build/Compilation Errors

1. Detect project type from manifest files (package.json, pom.xml, Cargo.toml, go.mod, pyproject.toml).
2. Collect ALL errors — run the full build command, not just the first file.
3. Categorize: type inference, missing definitions, import/export, configuration.
4. Fix each error with the minimal change. Verify after each.
5. Final verification: full build exits 0. Report "X/Y errors fixed" after each fix.

## Circuit Breaker

After 3 failed hypotheses, **STOP**. Report what was tried and ask for direction. Do not keep trying variations of the same approach.

## Rules

- Reproduce BEFORE investigating. If you cannot reproduce, find the conditions first.
- One hypothesis at a time. Do not bundle multiple fixes.
- No speculation — "seems like" and "probably" are not findings. Show evidence or drop the claim.
- Fix with minimal diff. Do not refactor, rename, optimize, or redesign while fixing.
- **Scope check after every fix**: review your diff before declaring done. Revert any change not directly related to the root cause.
- Follow all conventions in `.github/copilot-instructions.md`.

## Output Format

### Runtime Bug:
```
## Bug Report
**Symptom**: [What the user sees]
**Root Cause**: [The actual issue at file:line]
**Reproduction**: [Minimal steps to trigger]
**Fix**: [Minimal code change applied]
**Verification**: [How it was proven fixed]
**Similar Issues**: [Other places this pattern might exist]
```

### Build Error:
```
## Build Error Resolution
**Initial Errors**: X
**Errors Fixed**: Y
**Build Status**: PASSING / FAILING

### Errors Fixed
1. src/file.ts:45 — [error message] — Fix: [what was changed]

### Verification
- Build command: [command] → exit code 0
- No new errors introduced: confirmed
```

## Failure Modes to Avoid

- Symptom fixing: adding null checks everywhere instead of asking "why is it null?"
- Skipping reproduction: investigating before confirming the bug can be triggered.
- Hypothesis stacking: trying 3 fixes at once instead of one at a time.
- Refactoring while fixing: "while I'm fixing this, let me also rename…" — no.
- Infinite loop: same failed approach after 3 attempts. Stop and ask.

$ARGUMENTS
