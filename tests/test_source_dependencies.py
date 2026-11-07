import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runner'))
from source_dependencies import dependency_paths, touches
from shared_pins import admit_regular, changes_since_pin, regular_due, engine_config, main
from pin_plan import regular_weekday
from datetime import datetime, timezone


class DeclaredConsumption(unittest.TestCase):
    def test_action_script_and_python_import_closure_without_unrelated_scripts(self):
        files = {'.github/actions/a/action.yml': 'run: python scripts/a.py',
                 'scripts/a.py': 'import helper\nfrom common.check import run',
                 'scripts/helper.py': 'print("ok")',
                 'scripts/common/check.py': 'pass', 'scripts/unrelated.py': 'pass'}
        got = dependency_paths(['.github/actions/a'], files, files.__getitem__)
        self.assertEqual(got, ['.github/actions/a/action.yml', 'scripts/a.py',
                               'scripts/common/check.py', 'scripts/helper.py'])
        pin = {'roots': ['.github/actions/a'], 'dependency_paths': got}
        self.assertTrue(touches(pin, ['scripts/helper.py']))
        self.assertFalse(touches(pin, ['scripts/unrelated.py', '.github/actions/b/action.yml']))
        self.assertEqual(dependency_paths([''], files, files.__getitem__), [])
        self.assertFalse(touches({'roots': ['']}, ['scripts/a.py']))

    def test_local_action_dependency(self):
        files = {'.github/workflows/a.yml': 'uses: ./.github/actions/a',
                 '.github/actions/a/action.yml': 'run: python scripts/a.py', 'scripts/a.py': 'pass'}
        self.assertEqual(set(dependency_paths(['.github/workflows/a.yml'], files, files.__getitem__)), set(files))

    def test_ordinary_cap_but_explicit_fix_bypasses_it(self):
        regular = {'should_open': True, 'qualifying_fixes': []}
        self.assertTrue(admit_regular(dict(regular), 14)['should_open'])
        self.assertFalse(admit_regular(dict(regular), 15)['should_open'])
        fix = {'should_open': True, 'qualifying_fixes': [{'sha': 'f' * 40}]}
        self.assertTrue(admit_regular(fix, 99)['should_open'])

    def test_same_day_catchup_but_no_weekend(self):
        def clock(day, hour, minute): return datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc)
        self.assertFalse(regular_due(clock(9, 4, 16)))
        self.assertTrue(regular_due(clock(9, 4, 17)))
        self.assertTrue(regular_due(clock(10, 18, 17)))
        self.assertFalse(regular_due(clock(7, 12, 17)))

    def test_aggregate_is_not_a_lag_timestamp_and_history_stops_at_consumed_change(self):
        old, target = 'a' * 40, 'b' * 40
        pin = {'sha': old, 'roots': ['.github/actions/a'], 'dependency_paths': ['scripts/helper.py']}
        class GH:
            cache = {}
            def compare(self, *_):
                return {'files': [{'filename': 'scripts/helper.py'}], 'commits': [
                    {'sha': 'c', 'commit': {'committer': {'date': '2026-11-01T00:00:00Z'}}},
                    {'sha': 'd', 'commit': {'committer': {'date': '2026-11-02T00:00:00Z'}}}], 'total_commits': 2}
            def forward(self, *_): return True
            def request(self, path):
                if path.endswith('/c'): return {'files': [{'filename': 'scripts/unrelated.py'}]}
                return {'files': [{'filename': 'scripts/helper.py'}]}
        changes, unknown = changes_since_pin(GH(), [pin], target, [])
        self.assertEqual(unknown, [])
        self.assertFalse(changes[0]['lag_eligible'])
        self.assertEqual(changes[1]['merged_at'], '2026-11-02T00:00:00Z')
        self.assertEqual(changes[1]['files'], ['scripts/helper.py'])

    def test_capped_history_still_has_relevance_but_reports_unknown_age(self):
        class GH:
            cache = {}
            def compare(self, *_): return {'files': [{'filename': '.github/actions/a/action.yml'}], 'commits': [], 'total_commits': 251}
            def forward(self, *_): return True
        changes, unknown = changes_since_pin(GH(), [{'sha': 'a' * 40, 'roots': ['.github/actions/a']}], 'b' * 40, [])
        self.assertEqual(len(changes), 1)
        self.assertFalse(changes[0]['lag_eligible'])
        self.assertEqual(unknown[0]['reason'], 'source-history-incomplete')


    def test_nonancestor_warning_is_in_native_pr_body_with_automerge_disabled(self):
        config = engine_config('SylphxAI/fixture', [], 'week-2026-46', Path('/tmp/fixture'),
                               ancestry_failures=['a' * 40])
        self.assertFalse(config['automerge'])
        self.assertFalse(config['platformAutomerge'])
        self.assertIn('Automatic merge is withheld', config['prBodyTemplate'])
        self.assertIn('`' + 'a' * 40 + '`', config['prBodyTemplate'])

    def test_offline_dry_run_entrypoint_never_calls_engine_or_arm(self):
        repo, old, target = 'SylphxAI/fixture', 'a' * 40, 'b' * 40
        text = 'steps:\n  - uses: SylphxAI/.github/.github/actions/a@' + old + ' # main\n'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'portfolio.md').write_text('## Drive — Projects\n| # | Product | Repository | Owns |\n|---|---|---|---|\n| 1 | Example | `' + repo + '` | Active |\n')
            (root / 'inventory.json').write_text(json.dumps([{'repo': repo, 'head': 'c' * 40,
                'files': {'.github/workflows/a.yml': text}, 'prs': [], 'changes': [{'sha': target,
                    'merged_at': '2026-11-01T00:00:00Z', 'behind_pins': [old], 'comparison_pin': old,
                    'files': ['.github/actions/a/action.yml'], 'lag_eligible': False}]}]))
            with patch('shared_pins.GitHub') as github, patch('shared_pins.run_engine') as engine, patch('shared_pins.verify_and_arm') as arm:
                self.assertEqual(main(['--inventory', str(root / 'inventory.json'), '--portfolio', str(root / 'portfolio.md'),
                    '--source-head', target, '--state-dir', str(root / 'state'), '--cache-root', str(root / 'cache'),
                    '--now', f'2026-11-{9 + regular_weekday(repo):02d}T04:17:00Z']), 0)
                github.assert_not_called()
                engine.assert_not_called()
                arm.assert_not_called()
            report = json.loads((root / 'state/report.json').read_text())
            self.assertTrue(report['repositories'][0]['should_open'])
            self.assertFalse(report['apply'])


if __name__ == '__main__': unittest.main()
