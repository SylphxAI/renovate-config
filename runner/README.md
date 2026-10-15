# Self-hosted Renovate runner

The hosted Mend app stopped producing PRs for the org in July 2026 and needs a
human sign-in to recover, so Renovate runs here instead:
[`.github/workflows/renovate.yml`](../.github/workflows/renovate.yml) on a
schedule (hourly 14:00-22:00 UTC, the preset's 22:00-06:00 Hong Kong window,
plus 04:00 UTC) and on `workflow_dispatch`.

- **Scope**: `repositories` in [`config.json`](config.json) - every repository
  in the company portfolio whose workflows pin the shared `SylphxAI/.github`
  actions and reusable workflows, across the five orgs in `orgs`; the workflow
  runs one Renovate job per entry, eight at a time. Renovate skips an archived
  repository. `citra` and `kernox` are left out on purpose: Dependabot owns
  every ecosystem there, and one updater per ecosystem avoids duplicate PRs.
  Add a repository by adding it to the list. A repository whose
  `sylphx_delivery` custom property is `delivered` (a finished customer
  project) is skipped at plan time, whatever the list says.
- **One updater per ecosystem**: the enforced org code security configuration
  turns on Dependabot security updates, so Dependabot opens vulnerability PRs
  and Renovate (`vulnerabilityAlerts.enabled: true` in the preset) opens
  version updates.
- **Defaults**: every repository in scope gets `github>SylphxAI/renovate-config`
  without an onboarding PR; a repository's own Renovate config overrides it.
- **Auth**: a GitHub App installation token minted per run with
  `actions/create-github-app-token`, one per matrix repository's org. The App id
  is the repository variable `RENOVATE_APP_ID`, the key the repository secret
  `RENOVATE_APP_PRIVATE_KEY`. The app is installed once on each org in
  `config.json` `orgs`; a repository under an org the App is not installed on
  fails its own job only. PRs opened with an App token trigger CI, so the
  preset's non-major automerge lands through each repository's merge queue.

  The jobs carry **no** `environment:`. An environment gate on this repository
  stopped creating deployments on 2026-10-06 while its configuration stayed
  correct, so from 2026-10-11 every scheduled run was `cancelled` with zero jobs
  and no runner was ever allocated. The credentials live in repository secrets,
  which a `schedule`/`workflow_dispatch` run on the default branch reads; a
  public repository never exposes them to a fork pull request, so the protection
  the `main`-only environment gave is kept without the gate.

## The App

Today the runner uses the org-owned **Sylphx Builder** App (id 2847814):
contents, pull requests, issues, checks and statuses write. It has no
`workflows` permission, so a push that edits `.github/workflows` is rejected and
a GitHub Actions pin (which always lives in a workflow file) cannot be carried.
`github-actions` is enabled in [`config.json`](config.json) so the manager
computes those updates, but each push is refused until the App can write
workflows.

The target is a dedicated **Sylphx Renovate** App with `workflows: write`. This
is a one-time org-owner step (creating an App and installing it needs the GitHub
web UI):

1. <https://github.com/organizations/SylphxAI/settings/apps/new>: name
   `Sylphx Renovate`, homepage `https://github.com/SylphxAI/renovate-config`,
   webhook off. Repository permissions: Checks, Contents, Issues, Pull
   requests, Commit statuses, Workflows - read and write; Dependabot alerts -
   read; Administration - read. Organization: Members - read. Only on this
   account.
2. Generate a private key; install the App on every org in
   `config.json` `orgs` (SylphxAI, Cubeage, Cubeage-limited, EpiowAI,
   OzyrixLtd), all repositories. An org the App is missing is left out of
   scope until it is installed.
3. `gh variable set RENOVATE_APP_ID -R SylphxAI/renovate-config --body <id>` and
   `gh secret set RENOVATE_APP_PRIVATE_KEY -R SylphxAI/renovate-config < key.pem`
   (repository scope, not an environment).

## Adding an org

Installing the App on an org (step 2 above) is the only step that needs the
owner. Once it is installed and its repositories are in `repositories`, the next
scheduled run covers them.

## Delivered customer repositories

A repository whose `sylphx_delivery` custom property is `delivered` is a
finished customer project and never receives an automated PR. The plan job reads
the property for every repository in scope and drops the ones set to
`delivered`; the read fails closed so an unreadable property never opens PRs.
