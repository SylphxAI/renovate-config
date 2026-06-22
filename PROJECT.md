# Renovate Config Project

Renovate Config is the shared dependency-update policy for repositories that
extend `github>SylphxAI/renovate-config`. It owns the default Renovate rules,
stack detection assumptions, grouping, scheduling, automerge defaults, labels,
rate limits, and documentation for consumers.

## Lifecycle

- Lifecycle: `production`
- Layer: `tooling`
- Doctrine source of truth: [SylphxAI/doctrine](https://github.com/SylphxAI/doctrine)
- Machine manifest: `.doctrine/project.json`

## Goals

- Provide one default Renovate policy for multi-stack repositories.
- Reduce duplicated dependency-update configuration across the organization.
- Keep dependency-update behavior predictable, low-noise, and safe for CI
  capacity.

## Non-Goals

- Do not own project-specific dependency exceptions, release policies, or private
  registry credentials.
- Do not become a general CI/admission policy repository.
- Do not make broad automerge or schedule changes without fleet impact analysis.

## Boundaries

This repository owns `default.json` and the public README usage contract. Each
consuming repository owns local overrides, credentials, package-manager lockfiles,
and project-specific dependency risk decisions.

## Delivery

There is no repo-local GitHub Actions workflow at adoption time. Changes are
config/docs-only and become production behavior when merged to `main` because
consuming Renovate runs resolve the shared config from GitHub.
