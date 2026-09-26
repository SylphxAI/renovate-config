# renovate-config

<p align="center">
  <img src="https://mark.sylphx.com/api/v1/mark/hero.svg?type=aurora&theme=grape&text=renovate-config&desc=A%20shared%20Renovate%20preset" alt="renovate-config" width="100%" />
</p>

A shared [Renovate](https://docs.renovatebot.com) preset: non-major dependency
updates merge on their own once CI passes, majors wait for a review, and
related packages arrive as one pull request instead of many.

## Use it

Add `renovate.json` (or `.github/renovate.json`) to your repository:

```json
{
  "extends": ["github>SylphxAI/renovate-config"]
}
```

Renovate reads [`default.json`](default.json) from this repository, so a change
here reaches every repository that extends it on its next run.

## What it does

| Setting | Value |
| --- | --- |
| Based on | `config:recommended`, dependency dashboard, semantic commit messages, monorepo and recommended grouping |
| Schedule | 10pm to 6am, Hong Kong time (`Asia/Hong_Kong`) |
| Minimum release age | 3 days; 7 days for majors and Android core libraries; 5 days for iOS |
| Automerge | minor, patch, digest and pin updates, `@types/*`, and weekly lock file maintenance (Monday before 6am) |
| Majors | labelled `breaking`, never automerged |
| Limits | 4 new pull requests per hour, 8 open at once |
| Automerge method | the platform's own auto-merge, so a merge queue or required checks still apply |
| Security fixes | off in Renovate (`vulnerabilityAlerts`), because Dependabot security updates open them; one tool per fix avoids duplicate pull requests |
| GitHub Actions | pinned to commit digests |
| Docker images | pinned to digests, labelled `docker-update` |
| Ignored paths | `node_modules`, `vendor`, `dist`, `build`, `.cache`, `ios/Pods`, `android/.gradle` |

Grouped into one pull request each, with a label:

| Group | Matches |
| --- | --- |
| TypeScript type definitions | `@types/*` |
| React packages | `react`, `react-*`, `@react/*`, `@types/react*` |
| Effect packages | `effect`, `@effect/*` |
| Linting packages | names containing `biome`, `eslint` or `prettier` |
| Bun runtime | `bun`, `@types/bun`, `bun-types` |
| Android dependencies | Gradle and the Gradle wrapper |
| iOS dependencies | Swift packages and CocoaPods |
| Flutter dependencies | pub (Dart) packages |
| Python dependencies | pip requirements, `setup.py`, Pipenv, Poetry, PEP 621 |

Composer (PHP) updates get the `php` label but are not grouped. Everything else
uses Renovate's defaults for its package manager.

## Override it

Settings in your own config win over the preset:

```json
{
  "extends": ["github>SylphxAI/renovate-config"],
  "schedule": ["every weekend"],
  "packageRules": [
    { "matchPackageNames": ["critical-package"], "automerge": false }
  ]
}
```

## Running Renovate yourself

The SylphxAI organization runs Renovate from a GitHub Actions workflow in this
repository instead of the hosted app. How it works, which repositories it
covers and how it authenticates are in [runner/README.md](runner/README.md).

## Contributing

Change [`default.json`](default.json) and update the tables above in the same
pull request. CI checks that the preset is valid JSON.

## License

MIT
