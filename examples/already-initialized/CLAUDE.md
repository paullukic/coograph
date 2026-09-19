# Claude Code Instructions — acme-web

Code-graph first for all navigation. OpenSpec for any change touching 2+ files or a
public interface. See `.github/copilot-instructions.md` for full conventions.

## Quick Reference

| Task | Command |
|------|---------|
| Dev server | `pnpm dev` |
| Build | `pnpm build` |
| Lint | `pnpm lint` |
| Type-check | `pnpm typecheck` |
| Format | `pnpm format` |
| Test | `pnpm test` |

## Branching Strategy

Trunk-based: short-lived `feat/*` and `fix/*` branches off `main`, squash-merged.

## Key Paths

- Source code: `src/`
- Shared components: `src/components/`
- API types: `src/lib/types.ts`
- Data layer: `src/lib/db.ts` (Prisma)
- Routes: `src/app/`

## Critical Rules

- Regenerate Prisma client with `pnpm prisma generate` after schema edits.
- Preserve all existing features unless the ticket says to remove them.
- No new dependencies without explicit approval.
