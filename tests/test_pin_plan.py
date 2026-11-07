from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import re

import unittest
from functools import wraps


def cases(_names, values):
    def decorate(function):
        function._cases = [(value,) for value in values] if "," not in _names else values
        return function
    return decorate

# Works both in renovate-config (runner is not a package) and isolated handoff.
spec = importlib.util.spec_from_file_location("pin_plan", Path(__file__).parents[1] / "runner" / "pin_plan.py")
pin_plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pin_plan)
parse_active_portfolio = pin_plan.parse_active_portfolio
parse_pins = pin_plan.parse_pins
plan_repo = pin_plan.plan_repo
estimate_pr_ci_jobs = pin_plan.estimate_pr_ci_jobs

OLD = "a" * 40
HEAD = "b" * 40
FIX = "c" * 40
NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
PATH = ".github/workflows/ci.yml"


def workflow(root=".github/actions/review", ref=OLD):
    return f"on: [pull_request, merge_group]\njobs:\n  test:\n    runs-on: self-hosted\n    steps:\n      - uses: SylphxAI/.github/{root}@{ref} # main\n"


def plan(*, files=None, fixes=None, changes=None, now=NOW, regular=False, branches=()):
    return plan_repo("SylphxAI/example", files or {PATH: workflow()}, HEAD,
                     fixes or [], changes or [], now, list(branches), regular)


def change(*, sha=FIX, age=timedelta(hours=25), files=None, **kwargs):
    return {"sha": sha, "merged_at": (NOW - age).isoformat(),
            "files": files if files is not None else [".github/actions/review/action.yml"],
            "number": 23, **kwargs}


def _test_portfolio_repository_cells_only_in_active_sections():
    text = """# Portfolio
Prose `SylphxAI/not-listed`
## Open source
| # | Product | Repository | Owns |
| 0 | Public | `SylphxAI/not-active` | |
## Drive — SylphxAI
| # | Product | Repository | Owns |
| ---: | --- | --- | --- |
| 1 | Cloud | `SylphxAI/cloud`; foundation support: `SylphxAI/.github`, `SylphxAI/infra` ([names.md](names.md)) | `SylphxAI/not-a-cell` is a dependency |
| 2 | Renamed | `SylphxAI/new` (renamed from `SylphxAI/old` 2026-09-23) | Active |
| 3 | Parked | `SylphxAI/parked` | Play is preserved. Parked: last in queue |
| 4 | Product **paused** | `SylphxAI/paused` | Preserve data |
| 5 | Legacy | `SylphxAI/archived` (archived) | |
## Maintain — Cubeage
| # | Product | Repository | Owns |
| 6 | Frozen | `Cubeage/frozen` and its ranking service `Cubeage/rank` | Frozen with notice; sign-in/play still run |
| 7 | Retired | `Cubeage/retired` | Retired and archived. Support now in `Cubeage/active` |
## Retired — history only
| # | Product | Repository | Owns |
| 8 | Past | `SylphxAI/past` | |
## Drive and Maintain — other organizations
| # | Product | State | Repository | Owns |
| 9 | BGCA | Maintain | `SylphxAI/bgca` | Client software; repository carries `sylphx_delivery=delivered` |
| 10 | Suite | Drive | `EpiowAI/epiow`, `EpiowAI/minutes` | |
## CI names
`SylphxAI/nope`
"""
    assert parse_active_portfolio(text) == ["Cubeage/frozen", "Cubeage/rank", "EpiowAI/epiow", "EpiowAI/minutes", "SylphxAI/.github", "SylphxAI/cloud", "SylphxAI/infra", "SylphxAI/new"]


@cases("quote,comment", [("", ""), ("", " # main"), ('"', " # main"), ("'", "")])
def _test_uses_offsets_and_exact_source_match(quote, comment):
    text = "# 雪 🧭\njobs:\n  test:\n    steps:\n" + f"      - uses: {quote}SylphxAI/.github/.github/actions/review@{OLD}{quote}{comment}\n"
    pin, = parse_pins({PATH: text})
    assert pin["sha"] == OLD
    assert pin["roots"] == [".github/actions/review"]
    assert text[pin["start"]:pin["end"]] == OLD
    assert text[pin["match_start"]:pin["match_end"]] == pin["match"]
    assert pin["match"] == f"      - uses: {quote}SylphxAI/.github/.github/actions/review@{OLD}{quote}{comment}"
    # Replacement can be anchored to source rather than reserializing YAML.
    offset = pin["start"] - pin["match_start"]
    regex = re.escape(pin["match"][:offset]) + r"(?P<currentDigest>[a-f0-9]{40})" + re.escape(pin["match"][offset + 40:])
    assert re.search(regex, text)["currentDigest"] == OLD


@cases("ref", ["main", "v1", "abcdef1", "${{ inputs.ref }}"])
def _test_nonimmutable_uses_are_findings(ref):
    pin, = parse_pins({PATH: workflow(ref=ref)})
    assert pin["sha"] is None
    assert pin["ref"] == ref
    assert pin["finding"] == "non_immutable_ref"


@cases("reverse,quoted", [(False, False), (True, False), (False, True), (True, True)])
def _test_checkout_both_field_orders_quoted_and_infer_cloud_review_root(reverse, quoted):
    q = '"' if quoted else ""
    fields = [f"repository: {q}SylphxAI/.github{q}", f"ref: {q}{OLD}{q} # main"]
    if reverse:
        fields.reverse()
    text = "jobs:\n  test:\n    steps:\n      - uses: actions/checkout@v4\n        with:\n" + "".join("          " + line + "\n" for line in fields) + "          path: review-shared\n      - uses: ./review-shared/.github/actions/pr-review\n"
    pin, = parse_pins({PATH: text})
    assert pin["kind"] == "checkout"
    assert pin["consumed_roots"] == [".github/actions/pr-review"]
    assert text[pin["start"]:pin["end"]] == OLD
    assert "repository:" in pin["match"] and "ref:" in pin["match"]
    assert "- uses: ./review-shared" not in pin["match"]


def _test_missing_uses_ref_is_a_finding():
    text = "steps:\n- uses: SylphxAI/.github/.github/actions/review\n"
    pin, = parse_pins({PATH: text})
    assert pin["finding"] == "non_immutable_ref"
    assert pin["sha"] is None


def _test_checkout_unknown_ref_and_unresolved_consumption_still_reported():
    text = "jobs:\n  x:\n    steps:\n      - uses: actions/checkout@v4\n        with: {repository: 'SylphxAI/.github', ref: main, path: shared}\n      - run: echo done\n"
    pin, = parse_pins({PATH: text})
    assert pin["roots"] == [""]
    assert pin["finding"] == "non_immutable_ref"


def _test_checkout_does_not_infer_another_job_or_replaced_destination():
    text = f"""jobs:
  first:
    steps:
      - uses: actions/checkout@v4
        with: {{repository: SylphxAI/.github, ref: {OLD}, path: shared}}
      - uses: actions/checkout@v4
        with: {{repository: Someone/else, path: shared}}
      - uses: ./shared/.github/actions/not-original
  second:
    steps:
      - uses: ./shared/.github/actions/not-same-job
"""
    assert parse_pins({PATH: text})[0]["roots"] == [""]


def _test_checkout_script_consumption_and_reusable_workflow_pin():
    text = f"""jobs:
  first:
    uses: SylphxAI/.github/.github/workflows/verify.yml@{OLD}
  second:
    steps:
      - uses: actions/checkout@v4
        with: {{repository: SylphxAI/.github, ref: {OLD}, path: .image-lane}}
      - run: python3 .image-lane/scripts/publish.py
"""
    pins = parse_pins({PATH: text})
    assert [pin["roots"] for pin in pins] == [[".github/workflows/verify.yml"], ["scripts/publish.py"]]


def _test_comment_and_shell_strings_are_not_declarations_and_malformed_yaml_is_finding():
    text = f"# uses: SylphxAI/.github/.github/actions/review@{OLD}\nsteps:\n- run: |\n    uses: SylphxAI/.github/.github/actions/review@{OLD}\n"
    assert parse_pins({PATH: text}) == []
    assert parse_pins({PATH: "x: [\n# SylphxAI/.github"})[0]["finding"] == "invalid_yaml"


def _test_no_ancestry_is_unknown_not_a_fix_or_lag_breach():
    report = plan(fixes=[change()])
    assert report["outdated_count"] == 1  # Explicitly a head mismatch, not ancestry.
    assert report["qualifying_fixes"] == []
    assert report["lag_alerts"] == []
    assert report["findings"][0]["kind"] == "ancestry_unknown"
    assert not report["should_open"]


def _test_pin_newer_than_fix_is_not_qualifying():
    report = plan(fixes=[change(included_by_pins=[OLD])])
    assert report["qualifying_fixes"] == []
    assert report["lag_alerts"] == []
    assert report["findings"] == []


def _test_equal_fix_pin_is_included_without_separate_ancestry():
    report = plan(files={PATH: workflow(ref=FIX)}, fixes=[change()])
    assert report["qualifying_fixes"] == []
    assert report["findings"] == []


def _test_affected_fix_key_and_existing_immutable_branch():
    record = change(behind_pins=[OLD])
    report = plan(fixes=[record])
    assert report["branch_key"] == f"fix-{FIX}"
    assert report["should_open"]
    assert report["qualifying_fixes"][0]["affected_paths"] == [PATH]
    assert report["lag_alerts"][0]["kind"] == "marked_fix"
    report = plan(fixes=[record], branches=[f"renovate/shared-ci-fix-{FIX}"])
    assert report["branch_exists"] and not report["should_open"]


def _test_unrelated_fix_does_not_qualify_and_shared_helpers_do():
    assert not plan(fixes=[change(files=[".github/actions/unrelated/action.yml"], behind_pins=[OLD])])["qualifying_fixes"]
    assert plan(fixes=[change(files=["scripts/common.py"], behind_pins=[OLD])])["qualifying_fixes"]
    assert not plan(fixes=[change(files=["docs/readme.md"], behind_pins=[OLD])])["qualifying_fixes"]


@cases("marked,hours,expected", [(True, 24, 0), (True, 24.01, 1), (False, 192, 0), (False, 192.01, 1)])
def _test_lag_boundaries_are_strict(marked, hours, expected):
    records = [change(age=timedelta(hours=hours), behind_pins=[OLD])]
    report = plan(fixes=records if marked else [], changes=[] if marked else records)
    assert len(report["lag_alerts"]) == expected


def _test_conflicting_ancestry_is_unknown_and_future_merge_is_not_eligible():
    report = plan(fixes=[change(behind_pins=[OLD], included_by_pins=[OLD])])
    assert not report["qualifying_fixes"]
    assert report["findings"][0]["kind"] == "ancestry_unknown"
    report = plan(fixes=[change(age=timedelta(hours=-1), behind_pins=[OLD])])
    assert not report["qualifying_fixes"]
    assert report["findings"][0]["kind"] == "future_merged_at"


def _test_regular_week_uses_iso_year_and_is_not_reopened():
    date = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert plan(now=date, regular=True)["branch_key"] == "week-2026-53"
    assert not plan(now=date, regular=True, branches=["renovate/shared-ci-week-2026-53"])["should_open"]
    assert not plan(files={PATH: workflow(ref=HEAD)}, regular=True)["should_open"]


def _test_ci_static_matrices_and_path_filters_and_ignored_nonpr_workflow():
    text = """on: pull_request
jobs:
  test:
    strategy:
      matrix:
        os: [linux, mac]
        version: [20, 22, 24]
        exclude: [{os: mac, version: 20}]
        include: [{os: win, version: 24}]
    runs-on: self-hosted
  gate:
    runs-on: self-hosted
"""
    docs = "on:\n  pull_request:\n    paths: ['docs/**']\njobs:\n  docs:\n    runs-on: self-hosted\n"
    files = {PATH: text, ".github/workflows/docs.yml": docs,
             ".github/workflows/release.yml": "on: workflow_dispatch\njobs:\n  release:\n    runs-on: self-hosted\n"}
    report = estimate_pr_ci_jobs(files, [PATH])
    assert report["known_jobs"] == 7
    assert report["jobs_upper_bound"] == 7
    assert report["exact"]
    assert [item["path"] for item in report["workflows"]] == [PATH]


def _test_ci_dynamic_matrix_external_reusable_and_conditions_are_not_false_exact():
    text = f"""on: [pull_request]
jobs:
  build:
    strategy:
      matrix: ${{{{ fromJSON(needs.plan.outputs.matrix) }}}}
    runs-on: self-hosted
  external:
    uses: SylphxAI/.github/.github/workflows/build.yml@{OLD}
  gate:
    if: always()
    runs-on: self-hosted
  never:
    if: false
    runs-on: self-hosted
"""
    report = estimate_pr_ci_jobs({PATH: text}, [PATH])
    assert report["known_jobs"] == 1
    assert report["jobs_upper_bound"] is None
    assert report["dynamic_matrices"] == 1
    assert report["reusable_calls"] == 1
    assert not report["exact"]
    assert len(report["uncertainties"]) == 3


def _test_ci_local_reusable_expansion():
    caller = "on: pull_request\njobs:\n  call:\n    uses: ./.github/workflows/called.yml\n    strategy:\n      matrix:\n        version: [20, 22]\n"
    called = "on: workflow_call\njobs:\n  test:\n    runs-on: self-hosted\n  gate:\n    runs-on: self-hosted\n"
    report = estimate_pr_ci_jobs({PATH: caller, ".github/workflows/called.yml": called}, [PATH])
    assert report["known_jobs"] == 4
    assert report["reusable_calls"] == 2
    assert report["exact"]


def _test_aware_timestamps_required_and_inputs_are_not_modified():
    with unittest.TestCase().assertRaisesRegex(ValueError, "UTC offset"):
        plan(now=NOW.replace(tzinfo=None))
    record = change(behind_pins=[OLD])
    before = repr(record)
    plan(fixes=[record])
    assert repr(record) == before


class TestPinPlan(unittest.TestCase):
    pass


def _attach(function, arguments):
    @wraps(function)
    def run(self):
        function(*arguments)
    return run


for _name, _function in list(globals().items()):
    if _name.startswith("_test_") and callable(_function):
        for _index, _arguments in enumerate(getattr(_function, "_cases", [()])):
            _method = _name[1:] + (f"_{_index}" if hasattr(_function, "_cases") else "")
            setattr(TestPinPlan, _method, _attach(_function, _arguments))


if __name__ == "__main__":
    unittest.main()
