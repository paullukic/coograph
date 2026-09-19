# Copilot Instructions — acme-web

## Stack

| Layer | Technology |
|-------|------------|
| Language | TypeScript 5.4 |
| Framework | Next.js 14 (App Router) |
| Data layer | Prisma 5 on PostgreSQL |
| Testing | Vitest (unit), Playwright (e2e) |
| Build | Next.js / Turbopack |
| Linter/Formatter | ESLint + Prettier |
| Package manager | pnpm |

## Commands

| Task | Command |
|------|---------|
| Dev | `pnpm dev` |
| Build | `pnpm build` |
| Lint | `pnpm lint` |
| Type-check | `pnpm typecheck` |
| Format | `pnpm format` |
| Test | `pnpm test` |

## Project Structure

| Path | Purpose |
|------|---------|
| `src/app/` | App Router routes, layouts, server components |
| `src/components/` | Shared React components |
| `src/lib/` | Prisma client, server actions, types |
| `prisma/` | Schema and migrations |
| `tests/` | Vitest and Playwright suites |

## Code Style

- Functional React components, server components by default; `'use client'` only when
  interactivity requires it.
- Data access lives in `src/lib/` — never query Prisma directly from a component.
- Prefer server actions over route handlers for mutations.

## Naming Conventions

- Components `PascalCase`, hooks `useCamelCase`, files kebab-case.
- Prisma models singular `PascalCase`; table names plural snake_case via `@@map`.

## Testing

- Unit tests colocated under `tests/unit/`; e2e under `tests/e2e/`.
- Every server action has at least one Vitest test.

## Errors and Logging

- Throw typed errors from `src/lib/errors.ts`; never swallow.
- Log via `src/lib/logger.ts` (pino); no `console.log` in committed code.
