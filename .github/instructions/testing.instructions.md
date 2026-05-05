---
description: Conventions for test files — loaded only when editing tests.
applyTo: "**/*.{test,spec}.{ts,tsx,js,jsx}"
---

# Testing Conventions

> **Template guard:** This file is a stub — all rules are commented out. Uncomment and customize the rules that apply to your project before relying on this file, or delete it if the project does not need per-test-file guidance. Agents loading this file while it is still stubbed should flag it to the user.

<!-- FILL: Uncomment and customize the rules that apply to your project. Delete the rest. -->

<!--
## Framework
- Use [Vitest / Jest / Mocha / etc.] with [React Testing Library / Enzyme / etc.].
- Import test utilities from `@/test/utils` (or your shared test helpers).

## File Placement
- Colocate test files with source: `component.tsx` → `component.test.tsx`.
- Integration tests go in `__tests__/` at the feature root.

## Naming
- Describe behavior, not implementation: `'redirects unauthenticated users'` not `'calls navigate()'`.
- Use `describe` blocks for grouping. One `it`/`test` per behavior.

## Setup / Teardown
- Prefer `beforeEach` for per-test setup. Avoid shared mutable state across tests.
- Use factories or builders for test data — not copy-pasted object literals.

## Assertions
- Prefer explicit assertions over snapshot tests for logic.
- Test user-visible behavior (rendered text, navigation, form state) — not internal implementation details.
- Always assert the absence of errors/warnings in happy-path tests.

## Mocking
- Mock at the boundary (API calls, timers, navigation) — not internal functions.
- Reset mocks in `afterEach` to prevent test pollution.
- Use `msw` (Mock Service Worker) for API mocking when available.
-->
