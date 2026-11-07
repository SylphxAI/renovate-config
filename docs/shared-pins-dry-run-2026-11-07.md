# Shared pin dry run — 7 November 2026

**The Saturday pass would open zero PRs; the simulated next weekly pass has 61 grouped candidates.** No consumer branches, PRs or auto-merge requests were written.

## Inputs and limits

- Source main read in-session: `820a08341997835e8416c78d29f9d33226760e98`. The live merged `shared-action-fix` inventory was empty at 05:39 UTC. General lag history is not evaluated by this offline snapshot replay; production discovery reads it live.
- Scope: 67 active repositories from proposed owner#1866 head `430dfd90d12b13054eeee9673b64b3707af00f87`. Until that documentation PR merges, production uses the smaller roster on owner main, with no exception list.
- Consumer workflow/open-PR inventory: 64 entries captured 05:09 UTC; three foundation entries read at 05:39 UTC. `SylphxAI/keel-engine` is unreadable and explicitly unknown, not a clean or zero-cost consumer. These snapshots are preview inputs, not a claim that heads stayed unchanged.
- 66 readable repos contain 1,211 discovered pin declarations, including 10 non-immutable refs which are reported rather than rewritten. Full-SHA head mismatch is not itself an ancestry or lag claim.
- Today clock: `2026-11-07T05:41:00Z`; next weekly simulation: `2026-11-09T04:17:00Z`. The latter freezes these inputs to show weekly volume, not future source changes.

## CI load per consumer

The weekly candidates expand to **1,039 known static jobs**. Seventeen candidate repos have an unknown upper bound because of external reusable workflows or dynamic matrices. Conditions can skip these jobs, and branch/event filters are not evaluated. Counts are static expansions for one workflow-pin PR, not executed jobs or runner minutes; merge-group, asynchronous verification and post-merge jobs are additional. HKMT has 59 known static jobs. Every candidate below would use title `ci: update shared action pins` and branch `renovate/shared-ci-week-2026-46`.

| Consumer | Full-SHA head mismatches | Weekly candidate | Known PR jobs | Static upper bound |
| --- | ---: | :---: | ---: | ---: |
| `Cubeage/big2-tycoon` | 13 | yes | 51 | 51 |
| `Cubeage/big2-tycoon-2` | 18 | yes | 53 | 53 |
| `Cubeage/big2-tycoon-keel` | 11 | yes | 10 | 10 |
| `Cubeage/big2-tycoon-tw` | 10 | yes | 29 | 29 |
| `Cubeage/blackjack-showdown` | 12 | yes | 13 | 13 |
| `Cubeage/block-sort-keel` | 37 | yes | 16 | unknown |
| `Cubeage/bloomkin-keel` | 18 | yes | 11 | unknown |
| `Cubeage/cubeage-kit` | 19 | yes | 17 | unknown |
| `Cubeage/cubeage-native-sdk` | 14 | yes | 11 | 11 |
| `Cubeage/cubeage-platform` | 22 | yes | 20 | unknown |
| `Cubeage/dearhouse-keel` | 35 | yes | 20 | unknown |
| `Cubeage/fun-big2-hk` | 30 | yes | 15 | 15 |
| `Cubeage/fun-big2-keel` | 20 | yes | 25 | 25 |
| `Cubeage/fun-big2-tw` | 26 | yes | 13 | 13 |
| `Cubeage/fun-mahjong` | 23 | yes | 9 | 9 |
| `Cubeage/fun-mahjong-keel` | 67 | yes | 33 | 33 |
| `Cubeage/fun-showhand` | 25 | yes | 17 | 17 |
| `Cubeage/fun-showhand-keel` | 3 | yes | 2 | 2 |
| `Cubeage/fun-texas-holdem` | 35 | yes | 12 | 12 |
| `Cubeage/fun-texas-holdem-keel` | 3 | yes | 2 | 2 |
| `Cubeage/godsmith-keel` | 23 | yes | 18 | unknown |
| `Cubeage/hk-mahjong-tycoon` | 125 | yes | 59 | unknown |
| `Cubeage/hk-mahjong-tycoon-keel` | 2 | yes | 7 | 7 |
| `Cubeage/last-minute-keel` | 28 | yes | 16 | unknown |
| `Cubeage/lootling-keel` | 29 | yes | 14 | 14 |
| `Cubeage/mahjong-tycoon-tw` | 6 | yes | 7 | 7 |
| `Cubeage/mahjong-tycoon-tw-2` | 7 | yes | 12 | 12 |
| `Cubeage/opencity-keel` | 23 | yes | 16 | unknown |
| `Cubeage/pinpoint-keel` | 25 | yes | 50 | unknown |
| `Cubeage/planet-post-keel` | 37 | yes | 21 | unknown |
| `Cubeage/rank-system` | 3 | yes | 3 | 3 |
| `Cubeage/tenkind-keel` | 29 | yes | 21 | unknown |
| `Cubeage/tycoon-engine` | 26 | yes | 17 | 17 |
| `Cubeage/voidies` | 13 | yes | 10 | unknown |
| `Cubeage/warden-keel` | 18 | yes | 19 | unknown |
| `Cubeage/worldreign-keel` | 15 | yes | 13 | unknown |
| `EpiowAI/epiow` | 20 | yes | 30 | 30 |
| `EpiowAI/epiow-legacy` | 11 | yes | 20 | 20 |
| `EpiowAI/epiow-minutes` | 0 | no | 3 | 3 |
| `OzyrixLtd/website` | 17 | yes | 16 | 16 |
| `shtse8/chatgpt-export` | 0 | no | 1 | 1 |
| `shtse8/portfolio-website` | 3 | yes | 4 | 4 |
| `SylphxAI/.github` | 11 | yes | 12 | 12 |
| `SylphxAI/ads-ops` | 2 | yes | 3 | 3 |
| `SylphxAI/anyagents` | 1 | yes | 4 | 4 |
| `SylphxAI/anymd` | 10 | yes | 20 | 20 |
| `SylphxAI/cloud` | 33 | yes | 19 | unknown |
| `SylphxAI/firestore_odm` | 4 | yes | 10 | 10 |
| `SylphxAI/Google-Photos-Delete-Tool` | 2 | yes | 3 | 3 |
| `SylphxAI/header-canary` | 0 | no | 2 | 2 |
| `SylphxAI/infra` | 19 | yes | 27 | 27 |
| `SylphxAI/keel` | 50 | yes | 27 | unknown |
| `SylphxAI/keel-engine` | unknown | unknown | unknown | unknown |
| `SylphxAI/keel-website` | 18 | yes | 11 | 11 |
| `SylphxAI/lockdocs` | 5 | yes | 8 | 8 |
| `SylphxAI/luzzy` | 15 | yes | 19 | 19 |
| `SylphxAI/number-grove-keel` | 28 | yes | 17 | 17 |
| `SylphxAI/owner` | 1 | yes | 3 | 3 |
| `SylphxAI/puzzled` | 20 | yes | 19 | 19 |
| `SylphxAI/readme-mark` | 3 | yes | 5 | 5 |
| `SylphxAI/renovate-config` | 0 | no | 2 | 2 |
| `SylphxAI/repomap` | 9 | yes | 13 | 13 |
| `SylphxAI/skills` | 0 | no | 1 | 1 |
| `SylphxAI/spiron` | 22 | yes | 25 | 25 |
| `SylphxAI/tachyn` | 20 | yes | 22 | 22 |
| `SylphxAI/tryit` | 13 | yes | 10 | 10 |
| `SylphxAI/viszy.ai` | 14 | yes | 10 | 10 |

## Native engine and disk receipt

An actual locked Renovate 44.222.0 / Node 24.16.0 HKMT native dry run completed **2026-11-07 05:44:25–05:45:43 UTC**. It returned repository result `done`, process exit 0, `cloned=true`, with full dry-run mode and an independently read-only push adapter. The transport materializes only the sparse CI/config selection, depth 1, blobless, with LFS smudge disabled. It did not open or arm a roll.

- Peak allocated cache: **569,212,928 bytes** (542.84 MiB), sampled every 250 ms; not a byte-hard peak guarantee.
- Locked engine install: **553,603,072 bytes**.
- After cleanup: **0 bytes**; the disposable pass root was removed.
- Native pass used 75 GitHub reads; it ran serially under nice 19 and idle IO. No credential or raw native logs were retained.

The first native attempts exposed two integration defects before publication: the initial `ls-remote` did not apply native host-rule authentication, and duplicate `--filter` options became a GitHub-unsupported combined filter. The implementation now applies the HTTPS rewrite only through runtime child environment variables to every Git call and replaces the native filter instead of appending it. Those failed attempts are not counted as successful dry runs.

## Findings requiring attention

- `SylphxAI/keel-engine`: inventory unreadable; no plan or clean-lag claim.
- Nine source-self checkout refs and one owner checkout ref use expressions or `main` instead of a full SHA. They remain unchanged and visible as non-immutable findings, not silently treated as current.
- Existing emergency/migration pin PRs are untouched. Before publication the live immutable branch key is checked again; a pushed attempt marker survives unknown outcomes. Proof or authority failures leave a PR unarmed and notify the standing owner.

Machine-readable local receipts: `/scratch/shared-pin-evidence/{today,weekly}/report.json` and `/scratch/shared-pin-evidence/native-dry-hkmt.json`. They include workflow-level estimate uncertainties; this table deliberately avoids treating unresolved expansions as zero.
