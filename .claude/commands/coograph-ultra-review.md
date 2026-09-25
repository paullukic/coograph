Optional deep review for a big change: a multi-agent hostile review of a PR, a commit batch, a fix batch (delta) or a plan before code (plan) - one reviewer per dimension, every finding attacked by refuters, one report with a verdict. Costs about a million tokens and twenty minutes per run; `/coograph-review` stays the everyday review.

The full procedure is in `.github/skills/coograph-ultra-review/SKILL.md`. Follow it exactly: pick the mode, scope in the conversation, propose the model plan and ask, then run the saved workflow with the **absolute** `scriptPath` `<project>/.github/skills/coograph-ultra-review/workflow.js` and `args.repo` = the project's absolute path. Apply the stop rule in § 6 afterwards: blocking findings are fixed, adjacent follow-ups are recorded, at most two delta rounds, then a person.

$ARGUMENTS
