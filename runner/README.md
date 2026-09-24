# Self-hosted Renovate runner

The hosted Mend app stopped producing PRs for the org in July 2026 and needs a
human sign-in to recover, so Renovate runs here instead:
[`.github/workflows/renovate.yml`](../.github/workflows/renovate.yml) on a
schedule (hourly 14:00-22:00 UTC, the preset's 22:00-06:00 Hong Kong window,
plus 04:00 UTC) and on `workflow_dispatch`.

- **Scope**: `autodiscoverFilter` in [`config.json`](config.json) - the
  foundation repositories and the SylphxAI product repositories in the company
  portfolio. Archived repositories are skipped by autodiscover. `citra` and
  `kernox` are left out on purpose: Dependabot owns every ecosystem there, and
  one updater per ecosystem avoids duplicate PRs. Add a repository by adding it
  to the filter.
- **One updater per ecosystem**: the enforced org code security configuration
  turns on Dependabot security updates, so Dependabot opens vulnerability PRs
  and Renovate (`vulnerabilityAlerts.enabled: false` in the preset) opens
  version updates only.
- **Defaults**: every repository in scope gets `github>SylphxAI/renovate-config`
  without an onboarding PR; a repository's own Renovate config overrides it.
- **Auth**: a GitHub App installation token minted per run with
  `actions/create-github-app-token` for the whole org installation. The App id
  is the `renovate` environment variable `RENOVATE_APP_ID`, the key the
  environment secret `RENOVATE_APP_PRIVATE_KEY`; the environment deploys from
  `main` only. PRs opened with an App token trigger CI, so the preset's
  non-major automerge lands through each repository's merge queue.

## The App

Today the runner uses the org-owned **Sylphx Builder** App (id 2847814,
installed on all repositories): contents, pull requests, issues, checks and
statuses write. It has no `workflows` permission, so GitHub Actions updates are
disabled in `config.json` (GitHub rejects any App push that edits
`.github/workflows`).

The target is a dedicated **Sylphx Renovate** App. Creating an App needs the
GitHub web UI, so an org owner does it once:

1. <https://github.com/organizations/SylphxAI/settings/apps/new>: name
   `Sylphx Renovate`, homepage `https://github.com/SylphxAI/renovate-config`,
   webhook off. Repository permissions: Checks, Contents, Issues, Pull
   requests, Commit statuses, Workflows - read and write; Dependabot alerts -
   read; Administration - read. Organization: Members - read. Only on this
   account.
2. Generate a private key; install the App on SylphxAI, all repositories.
3. `gh variable set RENOVATE_APP_ID -R SylphxAI/renovate-config --env renovate --body <id>`
   and `gh secret set RENOVATE_APP_PRIVATE_KEY -R SylphxAI/renovate-config --env renovate < key.pem`.
4. Delete the `github-actions` block from `config.json`.
