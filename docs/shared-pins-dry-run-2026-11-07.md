# Shared pin dry run — 7 November 2026

**The Saturday pass would open zero PRs; the first staggered week has 61 relevant grouped candidates, spread 14/11/11/13/12 across Monday–Friday.** No consumer branches, PRs, arms or merge requests were written.

## Inputs and limits

- Source main captured at 05:39 UTC: `820a08341997835e8416c78d29f9d33226760e98`. Its merged `shared-action-fix` inventory was empty. Frozen snapshot replay does not evaluate ordinary lag age; production reads that history live.
- Scope: 67 repositories from owner#1866, now merged as `078a00be1231454c4f00603b959b615fcf796e27`. No exception list. Workflow/open-PR snapshots were captured 05:09 UTC, with foundation entries at 05:39 UTC; they do not prove unchanged current heads.
- Consumed-path eligibility was recomputed against the source Git object database: 98 old-SHA ancestor/diff proofs, 47 dependency closures, 134 source text reads. Every one of the original 61 candidates consumes an actually changed path; the filter prevents future unrelated-action churn rather than hiding this accumulated backlog.
- One distinct non-ancestor SHA (`d5c21651b7447684dfdaa734e69bea9e07bd8eac`, run-store) occurs in **HKMT and cloud**. Their proposed rolls remain **unarmed** and name the ancestry failure in the PR body. Other pins in these consumers have positive consumed-change evidence.
- `SylphxAI/keel-engine` is unreadable: excluded from writes and explicitly unknown in the lag report, not green.
- Saturday clock: `2026-11-07T06:00:00Z`; simulated regular clocks: 9–13 November at 04:17 UTC. Simulations freeze these inputs, not future source/consumer changes.

## Capacity

| Assigned weekday | Relevant candidates | Known static PR jobs |
| --- | ---: | ---: |
| Monday | 14 | 295 |
| Tuesday | 11 | 184 |
| Wednesday | 11 | 133 |
| Thursday | 13 | 222 |
| Friday | 12 | 205 |
| **Week total** | **61** | **1,039** |

The daily rows assume prior rolls have merged. A hard cap of **15 open roll PRs** across the roster defers regular admissions while earlier PRs remain open. A marked affected fix bypasses both cap and weekday. At 146 jobs/hour, the largest day is about 2.0 hours of whole-pool capacity, compared with 7.1 hours for the original Monday burst.

Counts are finite static PR-workflow expansions, not executed jobs or runner minutes. Conditions and branch/event filters can skip jobs; external reusable workflows and dynamic matrices leave 17 candidate upper bounds unknown. Merge-group and post-merge work are additional. HKMT has 59 known jobs.

## Proposed PRs

Every candidate uses title `ci: update shared action pins` and branch `renovate/shared-ci-week-2026-46`; only its assigned weekday is eligible. The table lists all 67 scoped repositories, including no-roll and unknown entries.

| Consumer | Assigned day | Would open that day | Known PR jobs | Static upper bound | Auto-arm withheld |
| --- | --- | :---: | ---: | ---: | --- |
| `Cubeage/big2-tycoon` | Monday | yes | 51 | 51 | — |
| `Cubeage/big2-tycoon-2` | Monday | yes | 53 | 53 | — |
| `Cubeage/big2-tycoon-keel` | Wednesday | yes | 10 | 10 | — |
| `Cubeage/big2-tycoon-tw` | Thursday | yes | 29 | 29 | — |
| `Cubeage/blackjack-showdown` | Tuesday | yes | 13 | 13 | — |
| `Cubeage/block-sort-keel` | Thursday | yes | 16 | unknown | — |
| `Cubeage/bloomkin-keel` | Friday | yes | 11 | unknown | — |
| `Cubeage/cubeage-kit` | Monday | yes | 17 | unknown | — |
| `Cubeage/cubeage-native-sdk` | Thursday | yes | 11 | 11 | — |
| `Cubeage/cubeage-platform` | Tuesday | yes | 20 | unknown | — |
| `Cubeage/dearhouse-keel` | Wednesday | yes | 20 | unknown | — |
| `Cubeage/fun-big2-hk` | Thursday | yes | 15 | 15 | — |
| `Cubeage/fun-big2-keel` | Tuesday | yes | 25 | 25 | — |
| `Cubeage/fun-big2-tw` | Friday | yes | 13 | 13 | — |
| `Cubeage/fun-mahjong` | Monday | yes | 9 | 9 | — |
| `Cubeage/fun-mahjong-keel` | Friday | yes | 33 | 33 | — |
| `Cubeage/fun-showhand` | Thursday | yes | 17 | 17 | — |
| `Cubeage/fun-showhand-keel` | Thursday | yes | 2 | 2 | — |
| `Cubeage/fun-texas-holdem` | Friday | yes | 12 | 12 | — |
| `Cubeage/fun-texas-holdem-keel` | Wednesday | yes | 2 | 2 | — |
| `Cubeage/godsmith-keel` | Thursday | yes | 18 | unknown | — |
| `Cubeage/hk-mahjong-tycoon` | Friday | yes | 59 | unknown | d5c21651b7447684dfdaa734e69bea9e07bd8eac |
| `Cubeage/hk-mahjong-tycoon-keel` | Monday | yes | 7 | 7 | — |
| `Cubeage/last-minute-keel` | Friday | yes | 16 | unknown | — |
| `Cubeage/lootling-keel` | Thursday | yes | 14 | 14 | — |
| `Cubeage/mahjong-tycoon-tw` | Wednesday | yes | 7 | 7 | — |
| `Cubeage/mahjong-tycoon-tw-2` | Tuesday | yes | 12 | 12 | — |
| `Cubeage/opencity-keel` | Tuesday | yes | 16 | unknown | — |
| `Cubeage/pinpoint-keel` | Monday | yes | 50 | unknown | — |
| `Cubeage/planet-post-keel` | Thursday | yes | 21 | unknown | — |
| `Cubeage/rank-system` | Wednesday | yes | 3 | 3 | — |
| `Cubeage/tenkind-keel` | Monday | yes | 21 | unknown | — |
| `Cubeage/tycoon-engine` | Friday | yes | 17 | 17 | — |
| `Cubeage/voidies` | Monday | yes | 10 | unknown | — |
| `Cubeage/warden-keel` | Monday | yes | 19 | unknown | — |
| `Cubeage/worldreign-keel` | Tuesday | yes | 13 | unknown | — |
| `EpiowAI/epiow` | Tuesday | yes | 30 | 30 | — |
| `EpiowAI/epiow-legacy` | Wednesday | yes | 20 | 20 | — |
| `EpiowAI/epiow-minutes` | Monday | no | 3 | 3 | — |
| `OzyrixLtd/website` | Thursday | yes | 16 | 16 | — |
| `shtse8/chatgpt-export` | Monday | no | 1 | 1 | — |
| `shtse8/portfolio-website` | Friday | yes | 4 | 4 | — |
| `SylphxAI/.github` | Wednesday | yes | 12 | 12 | — |
| `SylphxAI/ads-ops` | Friday | yes | 3 | 3 | — |
| `SylphxAI/anyagents` | Wednesday | yes | 4 | 4 | — |
| `SylphxAI/anymd` | Monday | yes | 20 | 20 | — |
| `SylphxAI/cloud` | Wednesday | yes | 19 | unknown | d5c21651b7447684dfdaa734e69bea9e07bd8eac |
| `SylphxAI/firestore_odm` | Friday | yes | 10 | 10 | — |
| `SylphxAI/Google-Photos-Delete-Tool` | Monday | yes | 3 | 3 | — |
| `SylphxAI/header-canary` | Monday | no | 2 | 2 | — |
| `SylphxAI/infra` | Monday | yes | 27 | 27 | — |
| `SylphxAI/keel` | Thursday | yes | 27 | unknown | — |
| `SylphxAI/keel-engine` | unknown | no | unknown | unknown | unreadable |
| `SylphxAI/keel-website` | Wednesday | yes | 11 | 11 | — |
| `SylphxAI/lockdocs` | Friday | yes | 8 | 8 | — |
| `SylphxAI/luzzy` | Thursday | yes | 19 | 19 | — |
| `SylphxAI/number-grove-keel` | Thursday | yes | 17 | 17 | — |
| `SylphxAI/owner` | Monday | yes | 3 | 3 | — |
| `SylphxAI/puzzled` | Friday | yes | 19 | 19 | — |
| `SylphxAI/readme-mark` | Monday | yes | 5 | 5 | — |
| `SylphxAI/renovate-config` | Thursday | no | 2 | 2 | — |
| `SylphxAI/repomap` | Tuesday | yes | 13 | 13 | — |
| `SylphxAI/skills` | Friday | no | 1 | 1 | — |
| `SylphxAI/spiron` | Wednesday | yes | 25 | 25 | — |
| `SylphxAI/tachyn` | Tuesday | yes | 22 | 22 | — |
| `SylphxAI/tryit` | Tuesday | yes | 10 | 10 | — |
| `SylphxAI/viszy.ai` | Tuesday | yes | 10 | 10 | — |

## Native engine and resource proof

A real locked Renovate full dry run on HKMT at 05:44:25–05:45:43 UTC cloned successfully, resolved/extracted the pins and finished `done`; the transport stayed read-only. Allocated disk peaked at **569,212,928 bytes (543 MiB)**, including the locked engine, and was **0 bytes after cleanup**. Connected-user API budget changed 3,517 → 3,442 (75 reads); no token appeared in stored logs/argv/configuration.

Retained local receipts: `/scratch/shared-pin-evidence/relevant-{07,09,10,11,12,13}/report.json`, `revised-summary.json`, `relevant-inventory.json`, `native-dry-hkmt.json` and `native-tests-final.log`. The source dependency helper follows literal script paths/local uses/Python imports; unresolved checkout consumption remains unknown rather than creating blanket eligibility. Production GitHub compare responses cap the file/history window: returned positive consumed-path evidence remains usable, while omitted history is reported unknown, never as no lag.
