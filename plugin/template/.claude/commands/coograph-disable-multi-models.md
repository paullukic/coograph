Turn off per-task model selection for this project. Every agent inherits the session model and Coograph stops suggesting mappings.

The full procedure lives in `.github/skills/coograph-disable-multi-models/SKILL.md`. Follow it exactly.

## Steps (summary)

1. Set `models.mode: off` in `openspec/config.yaml`, creating the block if absent. Leave any saved `preset` in place.
2. Confirm in one line, naming the file.

Do not ask for confirmation first; the command's only job is this.

## What off means

Every agent inherits the session model, no flow suggests a mapping, and the one-line model footer still appears at the end of a delegated run naming the inherited model. `/coograph-suggest-multi-models` is the way back.
