# AGENTS.md

acme-web — a Next.js 14 (App Router) storefront in TypeScript, backed by Prisma on
PostgreSQL, tested with Vitest and Playwright.

## Structure

- `src/app/` — App Router routes and server components
- `src/components/` — shared React components
- `src/lib/` — data access (Prisma client, server actions)
- `prisma/` — schema and migrations
- `tests/` — Vitest unit tests and Playwright e2e

## Invocation

To set up Coograph in another project, follow `.github/skills/coograph-init/SKILL.md`
when the user types `/coograph-init` (Codex CLI: `$coograph-init`) or asks to
"initialize the project".
