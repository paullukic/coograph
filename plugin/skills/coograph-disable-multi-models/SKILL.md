---
name: coograph-disable-multi-models
description: Turn off per-task model selection for this project. Every agent inherits the session model and Coograph stops suggesting mappings. Use when the user says they do not want multiple models, wants one model for everything, or wants the suggestions to stop.
license: MIT
metadata:
  author: coograph
  version: "1.0"
---

You turn model selection off for this project. One step, no questions.

## Why This Matters

An opt-in feature that cannot be declined cleanly is not opt-in. A user who does not want their agents split across models should be able to say so once and never hear about it again, and the answer has to survive a template sync.

## Steps

1. Set `models.mode: off` in `openspec/config.yaml`, creating the `models` block if it is absent. Leave any saved `preset` in place; it is harmless and means re-enabling does not start from nothing.
2. Confirm in one line, naming the file.

That is the whole procedure. Do not ask for confirmation first: the user invoked a command whose only job is this.

## What off means

- No skill passes a `model` override. Every agent inherits the session model, exactly as a project that never opted in.
- No flow suggests a mapping. `coograph-new-ticket` and `coograph-plan` do not ask.
- The one-line model footer at the end of a delegated run still appears, naming the inherited model. It is the surface that tells a user their setting is being honoured, so it stays in every mode.
- `/coograph-suggest-multi-models` is the way back. Running it re-enables the project.

## Guardrails

- Never delete the `preset` map. Turning off is not the same as forgetting.
- Never touch anything else in `openspec/config.yaml`; that file holds the user's project context and rules.
- Never change the model the user's own session runs on.
