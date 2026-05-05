---
description: Conventions for CSS/styling files — loaded only when editing styles.
applyTo: "**/*.{css,scss,module.css,module.scss}"
---

# Styling Conventions

> **Template guard:** This file is a stub — all rules are commented out. Uncomment and customize the rules that apply to your project before relying on this file, or delete it if the project does not use styling conventions. Agents loading this file while it is still stubbed should flag it to the user.

<!-- FILL: Uncomment and customize the rules that apply to your project. Delete the rest. -->

<!--
## Methodology
- Use [BEM / CSS Modules / Tailwind / styled-components / etc.].
- Class naming: `.block__element--modifier` (BEM) or camelCase (CSS Modules).

## Custom Properties
- Use CSS custom properties (`var(--color-primary)`) for shared values (colors, spacing, typography).
- Define custom properties in a global file (e.g., `globals.css` or `:root`).

## Specificity
- Avoid `!important` — fix specificity conflicts at the source.
- Prefer scoped selectors (CSS Modules or component-level classes) over global overrides.
- When modifying a shared class, search for all usages first to avoid regressions.

## Responsive
- Use mobile-first media queries.
- Breakpoints defined as custom properties or shared constants.

## No Inline Styles
- Never use `style={{}}` in JSX — always use CSS classes.
- Move any inline styles discovered during changes to a class.
-->
