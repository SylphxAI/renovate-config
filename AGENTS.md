# Renovate Config Agent Instructions

## Scope

This file is the repo-local operating policy for agents working in
`SylphxAI/renovate-config`. Organization-wide engineering doctrine is owned by
`SylphxAI/doctrine`; `PROJECT.md` and `.doctrine/project.json` own this
repository's local identity, lifecycle, boundary, and delivery facts.

This repository owns the shared Renovate configuration consumed by other
repositories through `github>SylphxAI/renovate-config`.

## Read First

1. `PROJECT.md` and `.doctrine/project.json` for project goals, boundaries, and
   adoption state.
2. `README.md` for the supported stack matrix and public usage contract.
3. `default.json` before changing update grouping, schedules, automerge,
   package rules, or security behavior.

## Non-Negotiables

- Keep this repository generic. Project-specific dependency policy belongs in
  the consuming repo's local Renovate config.
- Treat `default.json` as the public contract for all repositories extending
  this config.
- Do not enable broad automerge, schedule, or grouping changes without evidence
  that they reduce fleet risk and CI load.
- Do not encode secrets, private registry credentials, or repo-specific tokens.

## Validation

Docs/config-only changes should be validated by:

- JSON parse validation for `default.json`
- diff review against README behavior
- central project manifest audit

For policy changes, include representative consuming-repo impact analysis before
merging.
