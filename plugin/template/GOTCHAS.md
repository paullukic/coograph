# Gotchas

Traps learned the hard way: one `##` entry per trap, short, current. Never
always-loaded. In Claude Code a hook shows an entry when you edit a file under
its `paths:` or run a command containing one of its `commands:`. Other tools
reach this file through the routing table in `AGENTS.md`.

Add an entry when a fix needed knowledge the code does not show (an environment
quirk, a deploy setting, an error message that points the wrong way). Keep each
entry under 800 bytes. Remove an entry when its `paths:` stop matching anything;
`/coograph-retro` proposes that for you.

Format (`Symptom`, `Cause`, `Fix / rule`, `paths`, `confirmed` are required;
`commands` is optional):

```markdown
## expo-export-ignores-shell-env
- **Symptom:** `expo export` builds with the old API URL after `export API_URL=...`
- **Cause:** `.env` wins over the shell for `expo export`.
- **Fix / rule:** change `.env.production`, never the shell.
- **paths:** `apps/mobile/**`, `app.config.ts`
- **commands:** `expo export`
- **confirmed:** 2026-10-01
```

<!-- Entries below this line. -->
