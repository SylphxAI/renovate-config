"""Returned positive evidence and fleet capacity survive partial discovery."""
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runner'))
import shared_pins as runner
from github_io import Refused
from pin_plan import parse_pins, plan_repo

OLD, TARGET, BAD = 'a' * 40, 'b' * 40, 'd' * 40
ROOT = '.github/actions/a'
FILES = {'.github/workflows/a.yml': f'steps:\n  - uses: SylphxAI/.github/{ROOT}@{OLD} # main\n'}
NOW = datetime(2026, 11, 9, 5, tzinfo=timezone.utc)
PORTFOLIO = '''## Drive — Repositories
| # | Product | Repository | Owns |
|---|---|---|---|
| 1 | Bad | `SylphxAI/a-bad` | Active |
| 2 | Good | `SylphxAI/example` | Active |
'''


class CompareEvidence(unittest.TestCase):
    def decision(self, positive, commit_positive=False):
        pins = parse_pins(FILES)
        class GH:
            cache = {}
            def compare(self, *args):
                paths = [f'unrelated/{n}' for n in range(300)]
                if positive:
                    paths[0] = ROOT + '/action.yml'
                return {'files': [{'filename': p} for p in paths],
                        'commits': ([{'sha': 'c' * 40, 'commit': {'committer': {'date': '2026-11-01T00:00:00Z'}}}]
                                    if commit_positive else [])}
            def forward(self, *args):
                return True
            def request(self, path):
                return {'files': [{'filename': ROOT + '/action.yml'}]}
        changes, unknown = runner.changes_since_pin(GH(), pins, TARGET, [])
        decision = plan_repo('SylphxAI/example', FILES, TARGET, [], changes, NOW, [], True, pins=pins)
        return decision, unknown

    def test_capped_compare_retains_returned_consumed_path_even_without_commit_evidence(self):
        decision, unknown = self.decision(True)
        self.assertTrue(decision['should_open'])
        self.assertIn('comparison-files-incomplete', [x['reason'] for x in unknown])

    def test_capped_compare_without_positive_files_or_commits_is_unknown_not_healthy(self):
        decision, unknown = self.decision(False)
        self.assertFalse(decision['should_open'])
        self.assertEqual(unknown, [{'sha': OLD, 'reason': 'comparison-files-incomplete'}])

    def test_capped_compare_retains_positive_commit_even_when_aggregate_omits_it(self):
        decision, unknown = self.decision(False, True)
        self.assertTrue(decision['should_open'])
        self.assertTrue(unknown)


class FleetCapacity(unittest.TestCase):
    def run_fixture(self, *, failure='source', existing=15, marked=False):
        class GH:
            def request(self, path):
                if path.endswith('/commits/main'):
                    return {'sha': TARGET}
                if '/git/matching-refs/' in path:
                    return []
                return {'default_branch': 'main', 'archived': False}
            def text(self, *args):
                return PORTFOLIO
            def pages(self, path):
                if '/a-bad/' in path:
                    if failure == 'inventory':
                        raise Refused('fixture-inventory-refused')
                    return [{'head': {'ref': f'renovate/shared-ci-week-2026-{n:02}'}} for n in range(existing)]
                return []
        def collect(gh, repo, *args):
            if repo.endswith('a-bad') and failure == 'consumer':
                raise Refused('fixture-consumer-refused')
            return {p: text.replace(OLD, BAD) if repo.endswith('a-bad') else text for p, text in FILES.items()}
        def reader(gh, target):
            def enrich(pins):
                if pins[0]['sha'] == BAD and failure == 'source':
                    raise Refused('source-dependencies-unreadable:' + BAD)
                pins[0]['dependency_paths'] = []
            return enrich
        change = {'sha': TARGET, 'files': [ROOT + '/action.yml'], 'behind_pins': [OLD],
                  'comparison_pin': OLD, 'merged_at': '2026-11-01T00:00:00Z'}
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            for name, kwargs in {
                'GitHub': {'return_value': GH()}, 'collect_files': {'side_effect': collect},
                'source_reader': {'side_effect': reader}, 'utcnow': {'return_value': NOW},
                'fixes': {'return_value': [change] if marked else []},
                'changes_since_pin': {'return_value': ([change], [])},
            }.items():
                stack.enter_context(patch.object(runner, name, **kwargs))
            with redirect_stdout(io.StringIO()):
                runner.main(['--state-dir', temp + '/state', '--cache-root', temp + '/cache'])
            return json.loads(Path(temp + '/state/report.json').read_text())

    def test_open_rolls_count_before_source_enrichment_refuses(self):
        report = self.run_fixture()
        self.assertEqual(report['open_roll_prs'], 15)
        self.assertTrue(report['open_roll_inventory_known'])
        good = next(r for r in report['repositories'] if r['repo'] == 'SylphxAI/example')
        self.assertFalse(good['should_open'])
        self.assertTrue(good['capacity_deferred'])

    def test_open_rolls_count_even_when_consumer_files_cannot_be_read(self):
        report = self.run_fixture(failure='consumer')
        self.assertEqual(report['open_roll_prs'], 15)
        self.assertTrue(report['open_roll_inventory_known'])
        self.assertFalse(next(r for r in report['repositories'] if r['repo'] == 'SylphxAI/example')['should_open'])

    def test_unreadable_inventory_refuses_all_new_regular_and_marked_rolls(self):
        for marked in (False, True):
            with self.subTest(marked=marked):
                report = self.run_fixture(failure='inventory', marked=marked)
                self.assertFalse(report['open_roll_inventory_known'])
                good = next(r for r in report['repositories'] if r['repo'] == 'SylphxAI/example')
                self.assertFalse(good['should_open'])
                self.assertEqual(good['admission'], 'open-roll-inventory-unknown')
                self.assertIn('open-roll-inventory-unknown', [r.get('reason') for r in report['alerts']])

    def test_known_inventory_below_cap_still_admits_healthy_consumer(self):
        report = self.run_fixture(existing=14)
        self.assertEqual(report['open_roll_prs'], 14)
        self.assertTrue(report['open_roll_inventory_known'])
        self.assertTrue(next(r for r in report['repositories'] if r['repo'] == 'SylphxAI/example')['should_open'])

    def test_known_inventory_full_cap_still_admits_marked_fix(self):
        report = self.run_fixture(marked=True)
        self.assertEqual(report['open_roll_prs'], 15)
        self.assertTrue(next(r for r in report['repositories'] if r['repo'] == 'SylphxAI/example')['should_open'])


if __name__ == '__main__':
    unittest.main()
