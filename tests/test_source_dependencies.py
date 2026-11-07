import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runner'))
from source_dependencies import DependencyUnknown, dependency_paths, touches
from shared_pins import admit_regular, changes_since_pin, regular_due, engine_config, main, source_reader
from pin_plan import regular_weekday, parse_pins, plan_repo
from github_io import Refused
import hashlib
from datetime import datetime, timezone


class SourceGitHub:
    """Immutable source tree/blob fixture with provider read accounting."""
    def __init__(self, sources):
        self.sources, self.requests, self.reads = sources, [], []
        self.truncated = set()
        self.failed_reads = set()

    def request(self, path):
        self.requests.append(path)
        ref = path.split('/git/trees/', 1)[1].split('?', 1)[0]
        if ref not in self.sources:
            raise Refused('github-request-refused')
        return {'truncated': ref in self.truncated, 'tree': [
            {'path': path, 'sha': hashlib.sha256(text.encode()).hexdigest(), 'type': 'blob'}
            for path, text in self.sources[ref].items()]}

    def text(self, repo, path, ref):
        self.reads.append((repo, path, ref))
        if (path, ref) in self.failed_reads:
            raise Refused('github-request-refused')
        return self.sources[ref][path]


class HistoricalConsumption(unittest.TestCase):
    old, target = 'a' * 40, 'b' * 40
    root = '.github/actions/a'

    def fixture(self):
        sources = {
            self.old: {self.root + '/action.yml': 'run: python scripts/old.py',
                       'scripts/old.py': 'import helper', 'scripts/helper.py': 'pass'},
            self.target: {self.root + '/action.yml': 'run: python scripts/new.py',
                          'scripts/new.py': 'pass', 'scripts/unrelated.py': 'pass'}}
        files = {'.github/workflows/ci.yml':
                 f'steps:\n  - uses: SylphxAI/.github/{self.root}@{self.old} # main\n'}
        return SourceGitHub(sources), files, parse_pins(files)

    def test_removed_historical_helper_fix_and_coarse_siblings_qualify(self):
        for changed in ('scripts/old.py', 'scripts/helper.py'):
            with self.subTest(changed=changed):
                gh, files, pins = self.fixture()
                source_reader(gh, self.target)(pins)
                fixes = [{'sha': 'c' * 40, 'merged_at': '2026-11-01T00:00:00Z',
                          'files': [changed], 'behind_pins': [self.old]},
                         {'sha': 'd' * 40, 'merged_at': '2026-11-02T00:00:00Z',
                          'files': ['.github/actions/unrelated/action.yml'], 'behind_pins': [self.old]}]
                result = plan_repo('SylphxAI/fixture', files, self.target, fixes, [],
                                   datetime(2026, 11, 7, tzinfo=timezone.utc), [], False, pins=pins)
                self.assertEqual([f['sha'] for f in result['qualifying_fixes']], ['c' * 40])
                self.assertTrue(result['should_open'])
                self.assertEqual(pins[0]['dependency_paths'], [self.root + '/action.yml',
                                 'scripts/helper.py', 'scripts/new.py', 'scripts/old.py', 'scripts/unrelated.py'])

    def test_revision_and_blob_reuse_keeps_distinct_pin_closures(self):
        gh, _, pins = self.fixture()
        # Same roots at the new ref must not inherit old-ref consumption from
        # the closure cache; identical blobs across refs require only one read.
        gh.sources[self.target]['scripts/new.py'] = 'import shared\nprint("target")'
        gh.sources[self.old]['scripts/old.py'] = 'import shared\nprint("old")'
        for source in gh.sources.values():
            source['scripts/shared.py'] = 'print("shared")'
        newer = dict(pins[0], sha=self.target)
        enrich = source_reader(gh, self.target)
        enrich([*pins, newer])
        enrich(pins)
        self.assertEqual(len(gh.requests), 2)
        self.assertEqual(len(gh.reads), 6)  # 2 actions + 2 scripts + shared + identical pass blobs.
        self.assertIn('scripts/old.py', pins[0]['dependency_paths'])
        self.assertNotIn('scripts/old.py', newer['dependency_paths'])
        self.assertIn('scripts/shared.py', newer['dependency_paths'])

    def test_truncated_and_unreadable_history_refuse_instead_of_empty_closure(self):
        for mode in ('truncated', 'missing', 'blob'):
            with self.subTest(mode=mode):
                gh, _, pins = self.fixture()
                if mode == 'truncated':
                    gh.truncated.add(self.old)
                elif mode == 'missing':
                    del gh.sources[self.old]
                else:
                    gh.failed_reads.add((self.root + '/action.yml', self.old))
                enrich = source_reader(gh, self.target)
                with self.assertRaisesRegex(Refused, 'source-dependencies-unreadable:' + self.old):
                    enrich(pins)
                self.assertNotIn('dependency_paths', pins[0])
                # A transient/incomplete answer must not become a permanent
                # cached empty closure in the same reader.
                gh.truncated.clear()
                gh.failed_reads.clear()
                if mode == 'missing':
                    gh.sources[self.old] = {self.root + '/action.yml': 'run: python scripts/old.py',
                                            'scripts/old.py': 'pass'}
                enrich(pins)
                self.assertIn('scripts/old.py', pins[0]['dependency_paths'])

    def test_unreadable_historical_source_is_reported_and_never_published(self):
        gh, files, _ = self.fixture()
        del gh.sources[self.old]
        source_request, source_text = gh.request, gh.text
        repo = 'SylphxAI/fixture'
        consumer_head = 'e' * 40
        portfolio = ('## Drive — Projects\n| # | Product | Repository | Owns |\n'
                     '|---|---|---|---|\n| 1 | Fixture | `' + repo + '` | Active |\n')
        def request(path):
            values = {'repos/SylphxAI/owner/commits/main': {'sha': 'f' * 40},
                      'repos/SylphxAI/.github/commits/main': {'sha': self.target},
                      'repos/' + repo: {'archived': False, 'default_branch': 'main'},
                      'repos/' + repo + '/commits/main': {'sha': consumer_head},
                      'repos/' + repo + '/git/matching-refs/heads/renovate/shared-ci-': [],
                      'repos/' + repo + '/git/trees/' + consumer_head: {
                          'tree': [{'type': 'tree', 'path': '.github', 'sha': '2' * 40}]},
                      'repos/' + repo + '/git/trees/' + '2' * 40 + '?recursive=1': {
                          'tree': [{'type': 'blob', 'path': path.removeprefix('.github/'), 'sha': '1' * 40}
                                   for path in files]}}
            return values[path] if path in values else source_request(path)
        def text(name, path, ref):
            if name == 'SylphxAI/owner':
                return portfolio
            return files[path] if name == repo else source_text(name, path, ref)
        gh.request, gh.text, gh.pages = request, text, lambda _: []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch('shared_pins.GitHub', return_value=gh), patch('shared_pins.run_engine') as engine, \
                    patch('shared_pins.verify_and_arm') as arm:
                self.assertEqual(main(['--state-dir', str(root / 'state'), '--cache-root', str(root / 'cache'),
                                       '--apply']), 0)
                engine.assert_not_called()
                arm.assert_not_called()
            report = json.loads((root / 'state/report.json').read_text())
            self.assertEqual(report['active_roster'], [repo])
            self.assertEqual(len(report['alerts']), 1)
            self.assertIn('source-dependencies-unreadable:' + self.old, report['alerts'][0]['reason'])
            self.assertIn('error', report['repositories'][0])
            self.assertTrue((root / 'state/lag.trigger').is_file())

    def test_unsupported_or_unresolved_refs_do_not_fetch_invented_history(self):
        gh, _, pins = self.fixture()
        unsupported = dict(pins[0], sha=None, ref='main')
        unresolved = dict(pins[0], roots=[''])
        current = dict(pins[0], sha=self.target)
        enrich = source_reader(gh, self.target)
        enrich([unsupported, current])
        with self.assertRaisesRegex(Refused, 'source-dependencies-unreadable:.*DependencyUnknown'):
            enrich([unresolved])
        self.assertEqual(len(gh.requests), 1)
        self.assertNotIn('dependency_paths', unresolved)


class DeclaredConsumption(unittest.TestCase):
    def test_action_script_closure_keeps_whole_script_tree_not_other_actions(self):
        files = {'.github/actions/a/action.yml': 'run: python scripts/a.py',
                 'scripts/a.py': 'import helper\nfrom common.check import run',
                 'scripts/helper.py': 'print("ok")',
                 'scripts/common/check.py': 'pass', 'scripts/unrelated.py': 'pass'}
        got = dependency_paths(['.github/actions/a'], files, files.__getitem__)
        self.assertEqual(got, ['.github/actions/a/action.yml', 'scripts/a.py',
                               'scripts/common/check.py', 'scripts/helper.py', 'scripts/unrelated.py'])
        pin = {'roots': ['.github/actions/a'], 'dependency_paths': got}
        self.assertTrue(touches(pin, ['scripts/helper.py']))
        self.assertTrue(touches(pin, ['scripts/unrelated.py']))
        self.assertFalse(touches(pin, ['.github/actions/b/action.yml']))
        with self.assertRaisesRegex(DependencyUnknown, 'local-consumption-unresolved'):
            dependency_paths([''], files, files.__getitem__)
        self.assertFalse(touches({'roots': ['']}, ['scripts/a.py']))

    def test_local_action_dependency(self):
        files = {'.github/workflows/a.yml': 'uses: ./.github/actions/a',
                 '.github/actions/a/action.yml': 'run: python scripts/a.py', 'scripts/a.py': 'pass'}
        self.assertEqual(set(dependency_paths(['.github/workflows/a.yml'], files, files.__getitem__)), set(files))

    def test_package_relative_import_reviewer_regression_enrolls_siblings_and_init(self):
        root = '.github/actions/a'
        files = {root + '/action.yml': 'run: python scripts/run.py',
                 root + '/policy.json': '{}',
                 'scripts/run.py': 'from pkg.entry import run',
                 'scripts/pkg/__init__.py': '',
                 'scripts/pkg/entry.py': 'from .helper import check\ndef run(): check()',
                 'scripts/pkg/helper.py': 'def check(): pass',
                 'scripts/pkg/data.json': '{}',
                 'scripts/not_imported.py': 'pass',
                 '.github/actions/unrelated/action.yml': 'run: echo unrelated'}
        closure = dependency_paths([root], files, files.__getitem__)
        self.assertEqual(set(closure), set(files) - {'.github/actions/unrelated/action.yml'})
        old, target, fix = 'a' * 40, 'b' * 40, 'c' * 40
        workflows = {'.github/workflows/a.yml': f'uses: SylphxAI/.github/{root}@{old}'}
        pins = parse_pins(workflows)
        source_reader(SourceGitHub({old: files, target: files}), target)(pins)
        result = plan_repo('SylphxAI/fixture', workflows, target, [
            {'sha': fix, 'files': ['scripts/pkg/helper.py'], 'behind_pins': [old],
             'merged_at': '2026-11-01T00:00:00Z'}], [],
            datetime(2026, 11, 7, tzinfo=timezone.utc), [], False, pins=pins)
        self.assertTrue(result['should_open'])
        self.assertEqual([r['sha'] for r in result['qualifying_fixes']], [fix])

    def test_action_sibling_paths_and_transitive_shared_helper_trees(self):
        files = {'.github/actions/a/action.yml':
                 'run: python "$GITHUB_ACTION_PATH/../b/entry.py"',
                 '.github/actions/a/config.json': '{}',
                 '.github/actions/b/entry.py':
                 'from pathlib import Path\nimport sys\nsys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_shared"))\nfrom broker import run',
                 '.github/actions/b/sibling.dat': 'bytes',
                 '.github/actions/_shared/broker.py': 'from common.entry import run',
                 '.github/actions/_shared/policy.json': '{}',
                 'lib/common/__init__.py': 'from .helper import check',
                 'lib/common/entry.py': 'from .helper import check',
                 'lib/common/helper.py': 'check = 1',
                 'lib/common/data.json': '{}',
                 '.github/actions/unrelated/action.yml': 'run: echo no',
                 'other/not_used.py': 'pass'}
        expected = set(files) - {'.github/actions/unrelated/action.yml', 'other/not_used.py'}
        self.assertEqual(set(dependency_paths(['.github/actions/a'], files, files.__getitem__)), expected)

    def test_file_root_keeps_whole_action_tree_and_reads_each_code_blob_once(self):
        files = {'.github/actions/a/nested/entry.py': 'from .helper import check',
                 '.github/actions/a/nested/helper.py': 'check = 1',
                 '.github/actions/a/policy.json': '{}',
                 '.github/actions/a/action.yml': 'run: echo yes',
                 '.github/actions/b/action.yml': 'run: echo no'}
        reads = []
        def read(path):
            reads.append(path)
            return files[path]
        got = dependency_paths(['.github/actions/a/nested/entry.py', '.github/actions/a'], files, read)
        self.assertEqual(set(got), set(files) - {'.github/actions/b/action.yml'})
        self.assertEqual(len(reads), 3)
        self.assertEqual(len(reads), len(set(reads)))

    def test_explicit_unresolvable_local_consumption_is_typed_unknown(self):
        root = '.github/actions/a'
        cases = [([], {}, 'local-consumption-unresolved'),
                 ([''], {}, 'local-consumption-unresolved'),
                 ([root], {}, 'local-path-missing'),
                 ([root], {root + '/action.yml': 'uses: ./.github/actions/missing'}, 'local-path-missing'),
                 ([root], {root + '/action.yml': 'run: python scripts/missing.py'}, 'local-reference-missing'),
                 ([root], {root + '/action.yml': 'run: node tools/missing.js'}, 'local-reference-missing'),
                 ([root], {root + '/action.yml': 'runs:\n  using: composite\n  steps:\n    - shell: bash\n      run: ./scripts/missing.sh\n'}, 'local-reference-missing'),
                 ([root], {root + '/action.yml': 'run: python "$GITHUB_ACTION_PATH/../missing/run.py"'}, 'local-path-missing'),
                 ([root], {root + '/action.yml': 'run: bash tools/check', 'tools/check': 'echo ok'}, 'executable-source-type-unknown'),
                 ([root], {root: 'link-target'}, 'local-directory-unresolved'),
                 ([root], {root + '/entry.py': 'from .missing import run'}, 'relative-import-missing'),
                 ([root], {root + '/entry.py': 'from ('}, 'python-source-unparseable')]
        for roots, files, reason in cases:
            with self.subTest(reason=reason, files=files):
                with self.assertRaisesRegex(DependencyUnknown, reason):
                    dependency_paths(roots, files, files.__getitem__)

    def test_dynamic_action_leaf_enrolls_literal_parent_tree(self):
        files = {'.github/actions/a/action.yml':
                 'run: python "$GITHUB_ACTION_PATH/../helpers/$TOOL.py"',
                 '.github/actions/helpers/tool.py': 'pass',
                 '.github/actions/helpers/data.json': '{}',
                 '.github/actions/unrelated/action.yml': 'run: echo no'}
        self.assertEqual(set(dependency_paths(['.github/actions/a'], files, files.__getitem__)),
                         set(files) - {'.github/actions/unrelated/action.yml'})

    def test_missing_historical_run_input_is_unknown_and_can_recover(self):
        old, target, root = 'a' * 40, 'b' * 40, '.github/actions/a'
        files = {'.github/workflows/a.yml': f'uses: SylphxAI/.github/{root}@{old}'}
        source = {root + '/action.yml': 'run: python scripts/run.py', 'scripts/run.py': 'pass'}
        gh = SourceGitHub({old: {root + '/action.yml': 'run: python scripts/old.py'}, target: source})
        pins = parse_pins(files)
        with self.assertRaisesRegex(Refused, 'source-dependencies-unreadable:' + old + ':DependencyUnknown'):
            source_reader(gh, target)(pins)
        self.assertNotIn('dependency_paths', pins[0])
        gh.sources[old]['scripts/old.py'] = 'pass'
        source_reader(gh, target)(pins)
        self.assertTrue(set(source) <= set(pins[0]['dependency_paths']))
        self.assertIn('scripts/old.py', pins[0]['dependency_paths'])

    def test_yaml_templates_are_included_as_data_not_executed(self):
        files = {'.github/actions/a/action.yml': 'run: python scripts/generate.py',
                 'scripts/generate.py': 'template = "uses: ./.github/actions/missing"',
                 'scripts/template.yml': 'uses: ./.github/actions/missing'}
        self.assertEqual(set(dependency_paths(['.github/actions/a'], files, files.__getitem__)), set(files))
        with self.assertRaisesRegex(DependencyUnknown, 'local-path-missing'):
            dependency_paths(['scripts/template.yml'], files, files.__getitem__)

    def test_shared_checkout_alias_requires_source_repository_provenance(self):
        workflow = ('steps:\n  - uses: actions/checkout@v4\n    with:\n'
                    '      repository: SylphxAI/.github\n      path: lane\n'
                    '  - uses: ./lane/.github/actions/helper\n')
        files = {'.github/workflows/a.yml': workflow,
                 '.github/actions/helper/action.yml': 'run: echo yes',
                 '.github/actions/helper/policy.json': '{}'}
        self.assertEqual(set(dependency_paths(['.github/workflows/a.yml'], files, files.__getitem__)), set(files))
        files['.github/workflows/a.yml'] = workflow.replace('SylphxAI/.github', 'other/repo')
        with self.assertRaisesRegex(DependencyUnknown, 'local-path-missing:lane/'):
            dependency_paths(['.github/workflows/a.yml'], files, files.__getitem__)

    def test_copied_pinned_tools_keep_source_directory_provenance(self):
        files = {'.github/actions/a/action.yml':
                 'run: |\n  for tool in run; do\n    cp "$GITHUB_ACTION_PATH/../../../scripts/$tool.py" "lane/scripts/$tool.py"\n  done\n  python lane/scripts/run.py\n',
                 'scripts/run.py': 'pass', 'scripts/policy.json': '{}'}
        self.assertEqual(set(dependency_paths(['.github/actions/a'], files, files.__getitem__)), set(files))
        files['.github/actions/a/action.yml'] = 'run: python lane/scripts/missing.py'
        with self.assertRaisesRegex(DependencyUnknown, 'local-reference-missing'):
            dependency_paths(['.github/actions/a'], files, files.__getitem__)

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


    def test_capped_history_preserves_returned_positive_consumed_evidence(self):
        class GH:
            cache = {}
            def compare(self, *_):
                return {'files': [{'filename': f'scripts/unrelated{i}.py'} for i in range(300)],
                        'commits': [{'sha': 'c', 'commit': {'committer': {'date': '2026-11-01T00:00:00Z'}}}],
                        'total_commits': 251}
            def forward(self, *_): return True
            def request(self, _): return {'files': [{'filename': '.github/actions/a/action.yml'}]}
        pin = {'sha': 'a' * 40, 'roots': ['.github/actions/a']}
        changes, unknown = changes_since_pin(GH(), [pin], 'b' * 40, [])
        self.assertEqual(len(changes), 2)
        self.assertFalse(changes[0]['lag_eligible'])
        self.assertEqual(len(changes[0]['files']), 300)
        self.assertEqual(changes[1]['files'], ['.github/actions/a/action.yml'])
        self.assertEqual(changes[1]['behind_pins'], ['a' * 40])
        self.assertEqual({u['reason'] for u in unknown}, {'comparison-files-incomplete', 'source-history-incomplete'})

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
