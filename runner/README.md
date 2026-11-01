# Self-hosted Renovate runner

The hosted Mend app stopped producing PRs for the org in July 2026 and needs a
human sign-in to recover, so Renovate runs here instead:
[`.github/workflows/dependency-updates.yml`](../.github/workflows/dependency-updates.yml)
on a schedule (hourly 14:00-22:00 UTC, the preset's 22:00-06:00 Hong Kong
window, plus 04:00 UTC) and on `workflow_dispatch`.

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
  is the `renovate` environment variable `RENOVATE_APP_ID`, the key the
  environment secret `RENOVATE_APP_PRIVATE_KEY`; the environment deploys from
  `main` only and has no required reviewers, so it never waits for approval. The
  App is installed once on each org in `config.json` `orgs`; a repository under
  an org the App is not installed on fails its own job only. PRs opened with an
  App token trigger CI, so the preset's non-major automerge lands through each
  repository's merge queue.

  Why the file is not called `renovate.yml`: GitHub stopped creating jobs for
  that file's workflow registration on 2026-10-06 while its body stayed valid.
  From 2026-10-11 every dispatch and schedule sat `pending` with zero jobs and no
  runner was ever allocated. A byte-identical copy under another name queued a
  job in seconds when tested on 2026-10-15, so the workflow is carried under a
  new file name and the stale registration is dropped with the old path.

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
   `config.json` `orgs` (SylphxAI, Cubeage, EpiowAI, OzyrixLtd), all
   repositories. An org the App is missing is left out of
   scope until it is installed.
3. `gh variable set RENOVATE_APP_ID -R SylphxAI/renovate-config --env renovate --body <id>`
   and `gh secret set RENOVATE_APP_PRIVATE_KEY -R SylphxAI/renovate-config --env renovate < key.pem`.

## Adding an org

Installing the App on an org (step 2 above) is the only step that needs the
owner. Once it is installed and its repositories are in `repositories`, the next
scheduled run covers them.

## Delivered customer repositories

A repository whose `sylphx_delivery` custom property is `delivered` is a
finished customer project and never receives an automated PR. The plan job reads
the property for every repository in scope and drops the ones set to
`delivered`; the read fails closed so an unreadable property never opens PRs.
