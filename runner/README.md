# Shared CI pin pass

Renovate propagates shared `SylphxAI/.github` action and workflow pins from a
GitOps-supervised desk process, not from an Actions App writer. The previous
`dependency-updates.yml` writer and its static repository/App scope are removed.
The shared package is disabled in the public preset so a second Renovate
installation cannot create competing shared-pin branches. Other dependency
preset settings are unchanged; this process updates shared CI pins only.

## Scope, cadence and cost

Each pass reads the current `SylphxAI/owner` main `company/portfolio.md`.
Only Repository cells in its Drive/Maintain tables are eligible; paused, parked,
retired, archived and delivered entries are excluded. Foundation support repos
belong in that same file, not in a code exception list. An archived GitHub repo
is skipped even if the portfolio has not caught up.

- Regular: one stable assigned weekday Monday–Friday, beginning **04:17 UTC**,
  one grouped immutable PR per consumer per ISO week. The first eight bytes of
  SHA256(casefold(repo)), big-endian, modulo five choose the weekday. Hourly
  checks on that day can catch up after capacity frees. All shared pins in that
  repo are one change, not one PR per action. A roll is eligible only after a
  consumed action/workflow directory or a reached script/helper directory tree
  changed since a current pin. Precise import tracing may only add paths to
  these coarse trees; unrelated action directories stay excluded.
  At most **15 roll PRs** may be open across the active roster before regular
  admission pauses; the next eligible pass re-evaluates capacity. Every known
  open roll counts even if consumer/source discovery later fails. If any
  active consumer's open-PR inventory is unreadable, capacity is unknown and
  no new regular or expedited roll opens.
- Expedited: label a source PR **`shared-action-fix`** before or after its merge.
  A merged labelled PR qualifies only where its changed action/workflow path is
  consumed and the old pin is proven behind its merge SHA. The consumed closure
  includes the whole used action tree, every directory
  reached by executable script/local-uses paths, and transitive shared-helper
  trees, including package-relative imports and package initializers, at both
  the existing pin and target revision. Unresolvable consumption is unknown,
  never known-empty or blanket whole-source eligibility. Fix rolls
  bypass the weekday and open-PR cap. The full merge SHA is the idempotency key.
  The latest missing qualifying fix in a pass groups the pending fixes.
- Read-only lag report: hourly at minute 17, alert for a missing marked fix after
  **more than 24 hours**, or an ordinary consumed change after **more than
  8 days**. Equal SHAs or included fixes do not lag; unknown ancestry/unsupported
  refs/incomplete reads alert separately rather than claiming a healthy fleet.

Branches are `renovate/shared-ci-week-YYYY-NN` or
`renovate/shared-ci-fix-<40-character merge SHA>`. Existing keys are never
rebased, force-pushed, recreated or retargeted. A blocked immutable PR requires
operator review; its continued lag stays visible. No emergency or older pin PR
is edited or closed. An unreadable repository or historical source dependency
tree/blob is excluded from writes and reported unknown, never green.
A non-ancestor pin can be proposed but cannot auto-arm; its PR body names the
ancestry failure and the report retains it for operator review.
The report includes per-repo static PR job expansion (finite matrices and local
reusable workflows); dynamic or external reusable expansion is explicitly
unknown. These are job estimates, not executed jobs or runner minutes.

## Identity, credentials and publication

The service inherits the desk's existing connected `gh` delegation. The runner
uses the installed unwrapped CLI for the local `gh auth token` read only,
then uses the metered wrapper for every API/merge call. It captures the token only in process memory; each pass verifies `/user` is
User **shtse8** with **repo + workflow** OAuth scopes, failing closed with no App
fallback. There is no new repository, Actions environment or on-disk token.
This uses owner `company/github-apps.md`'s connected-user mode (installation
mode is infrastructure/review only) and `company/credentials.md` preference #4:
read authorized existing custody in-process instead of duplicating a secret.

Renovate and Node are integrity-locked by `package-lock.json`. The native custom
regex manager extracts, resolves, edits and commits the full SHA uses scalars
and checkout `repository: SylphxAI/.github` / `ref:` scalars (either field order).
The discovery/proof code does not implement a second dependency updater.
Non-immutable refs are reported and never invented into a SHA pin.

Renovate uses credential-free SSH remote strings. Its supported host-rule Git
authentication passes the HTTPS rewrite in the child environment, never argv or
stored `.git/config`. `git_transport.py` is the sole Git executable in that
child's path. It translates Renovate's new-ref force-with-lease request into a
**plain push only after proving that exact branch absent**; existing refs and
all other remote writes refuse. Every proof, absence probe and push uses one
resolved repository and one validated environment. Caller-supplied Git context
options and environment overrides refuse, except the literal native quotePath
prefix, exact same-host authentication shape and fixed LFS/prompt/SSH/strict-
option values. The effective push URL is checked immediately before push.
A durable attempt marker precedes the call;
unknown outcomes are reconciled, never blindly replayed. The desk pre-push
scanner hook stays enabled (`gitNoVerify: []`).

Opened PRs have `ci: update shared action pins` as title (no review prefix or
identity wording). The runner arms normal squash auto-merge only after reading
that opened PR's exact head and proving:

1. Every byte edit is an existing shared SHA span, with the ` # main` comment
   retained; parsed YAML changes only uses/ref scalars.
2. The new SHA is on source main and descends from every replaced old SHA.
3. The consumer is in the derived active roster; changed files and live PR head
   match the proof.

It uses `gh pr merge --auto --squash --match-head-commit <head>` and records the
proof/attempt/readback. Consumer CI, its review gate and merge queue remain
required. Failed proofs leave the PR unarmed and alert. Implementation PRs and
all dry runs are unarmed.

## Run and recover

Prerequisites: desk `gh`, Git, npm, Python with PyYAML 6.0 or newer (CI pins 6.0.3), and `desk-publish`
for installing the existing pre-push hook. The GitOps service in
`SylphxAI/infra` owns scheduling, locks, low CPU/IO priority, the 55-minute
process-group deadline, 4 GiB sampled cache cap, cleanup and durable notification
to `agent:xenon`. It clones the source depth 1, blobless, sparse, and skips LFS;
consumer clones use the same depth/filter/no-LFS policy and only materialize
`.github/` plus Renovate config. Repositories run serially. Cache is deleted
after every pass. No LLM polling schedule is involved.

```sh
# Read-only fleet discovery (default); no engine install or consumer writes.
python3 runner/shared_pins.py --state-dir /tmp/shared-pin-report --cache-root /tmp/shared-pin-cache
# Native Renovate dry run on admitted candidates; push adapter refuses writes.
python3 runner/shared_pins.py --state-dir /tmp/shared-pin-native-report --cache-root /tmp/shared-pin-native-cache --engine-dry-run
# Production, only through the GitOps supervisor:
python3 runner/shared_pins.py --state-dir /scratch/coordinator/state/shared-pins --cache-root /tmp/renovate-shared-pins --apply
```

`report.json` records source head, roster, candidates, findings, job estimates
and peak/final allocated cache bytes. `lag.trigger` contains actionable findings;
the service treats its contents as an opaque deduplication digest and sends only
a static message/report path. A complete zero-alert pass clears it. Interrupted
passes do not clear an existing alert. Persistent push/arm claim files protect
unknown requests: inspect remote branch, PR, checks and queue membership before
reconciling a claim. Never delete a claim just to repeat a refused mutation.
The runner reserves native API headroom above the desk poll floor and never
switches credentials or lowers a shared limiter.

## Test

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
# Install in a private temporary directory, not the source checkout:
D=$(mktemp -d); cp runner/package{,-lock}.json "$D/"
npm ci --prefix "$D" --omit=dev --no-audit --no-fund
SHARED_PIN_ENGINE_DIR="$D" "$D/node_modules/node/bin/node" --test tests/native_engine.mjs
rm -rf "$D"
```

Native tests exercise the locked manager's actual extraction/replacement,
configuration validation and transport, including an existing-branch update
refusal with unchanged remote head, and synthetic-credential argv/artifact
checks. Python tests cover roster, pin discovery, relevant ancestry, alert
thresholds, matrix uncertainty and publication proof.
