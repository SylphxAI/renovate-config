"""Tests for desk/self-hosted general Renovate runner."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runner'))
import dependency_updates as du
from github_io import Refused

STO_FIXTURE = """## Register 2: `STO`

### 2.1 Drive — Foundations
| `#` | Product / Engine | Canonical Repository | Owner | Scope |
|---:|---|---|---|---|
| **1** | **Sylphx** | `SylphxAI/cloud` (foundation support: `SylphxAI/infra`) | `apollo` | Core |

### 2.3 Drive, Maintain & Retired
| `#` | Product | Mode | Entity | Canonical Repository & Public Surface |
|---:|---|---|---|---|
| **42** | **Site A** | **Drive** | `ENT-EX-FOUR` | `OzyrixLtd/site-a` |
| **43** | **Delivered** | **Maintain** | `ENT-EX-ONE` | `SylphxAI/bgca` (`sylphx_delivery=delivered`) |
"""


class DependencyUpdatesTests(unittest.TestCase):
    def test_discover_scope_combines_sto_and_extra_org_and_filters_delivered_archived(self):
        class GH:
            def request(self, path):
                if path == 'repos/SylphxAI/owner/commits/main':
                    return {'sha': 'a' * 40}
                if path == 'repos/SylphxAI/cloud':
                    return {'archived': False, 'disabled': False}
                if path == 'repos/SylphxAI/infra':
                    return {'archived': True, 'disabled': False}
                if path == 'repos/OzyrixLtd/site-a':
                    return {'archived': False, 'disabled': False}
                if path == 'repos/OzyrixLtd/site-b':
                    return {'archived': False, 'disabled': False}
                if path == 'repos/SylphxAI/cloud/properties/values':
                    return [{'property_name': 'sylphx_delivery', 'value': 'active'}]
                raise Refused('unexpected')

            def text(self, repo, path, ref):
                assert (repo, path, ref) == ('SylphxAI/owner', 'company/group-state-registers.md', 'a' * 40)
                return STO_FIXTURE

            def pages(self, path):
                assert path == 'orgs/OzyrixLtd/repos?type=sources'
                return [
                    {'full_name': 'OzyrixLtd/site-a', 'archived': False, 'fork': False},
                    {'full_name': 'OzyrixLtd/site-b', 'archived': False, 'fork': False},
                    {'full_name': 'OzyrixLtd/old-fork', 'archived': False, 'fork': True},
                ]

        sha, active, skipped = du.discover_scope(GH())
        self.assertEqual(sha, 'a' * 40)
        self.assertEqual(active, ['OzyrixLtd/site-a', 'OzyrixLtd/site-b', 'SylphxAI/cloud'])
        self.assertEqual(skipped, [{'repo': 'SylphxAI/infra', 'skip': 'archived'}])

    def test_sylphx_delivered_property_fails_closed(self):
        class GH:
            def request(self, path):
                if path == 'repos/SylphxAI/delivered-repo':
                    return {'archived': False, 'disabled': False}
                if path == 'repos/SylphxAI/delivered-repo/properties/values':
                    return [{'property_name': 'sylphx_delivery', 'value': 'delivered'}]
                raise AssertionError(path)

        _, active, skipped = du.discover_scope(GH(), only_repos=['SylphxAI/delivered-repo'])
        self.assertEqual(active, [])
        self.assertEqual(skipped, [{'repo': 'SylphxAI/delivered-repo', 'skip': 'delivered'}])

    def test_empty_repository_is_skipped_cleanly(self):
        class GH:
            def request(self, path):
                if path == 'repos/SylphxAI/empty-repo':
                    return {'archived': False, 'disabled': False, 'size': 0}
                if path == 'repos/SylphxAI/empty-repo/branches?per_page=1':
                    return []
                raise AssertionError(path)

        _, active, skipped = du.discover_scope(GH(), only_repos=['SylphxAI/empty-repo'])
        self.assertEqual(active, [])
        self.assertEqual(skipped, [{'repo': 'SylphxAI/empty-repo', 'skip': 'empty'}])

    def test_run_repo_passes_connected_identity_and_accepts_disabled_repo(self):
        class GH:
            _token = 'secret-user-token'
            login = 'shtse8'
            env = {'GH_TOKEN': 'secret-user-token', 'PATH': '/usr/bin'}

        seen = {}

        class Res:
            returncode = 0
            stdout = json.dumps({'msg': 'Repository finished', 'repository': 'EpiowAI/epiow', 'result': 'disabled', 'cloned': False}).encode()
            stderr = b''

        def fake_run(argv, *, env, cwd, capture_output, timeout):
            seen['argv'] = argv
            seen['env'] = env
            seen['config'] = json.loads(Path(env['RENOVATE_CONFIG_FILE']).read_text())
            return Res()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node = root / 'node'
            cli = root / 'renovate.js'
            with patch.object(du.subprocess, 'run', side_effect=fake_run):
                entry = du.run_repo(GH(), 'EpiowAI/epiow', root, (node, cli), du.DEFAULT_CONFIG, dry_run='off', force=True)
            Res.stdout = json.dumps({'msg': 'Repository finished', 'repository': 'EpiowAI/epiow', 'result': 'disabled-by-config', 'cloned': False}).encode()
            with patch.object(du.subprocess, 'run', side_effect=fake_run):
                disabled_cfg = du.run_repo(GH(), 'EpiowAI/epiow', root, (node, cli), du.DEFAULT_CONFIG, dry_run='off', force=True)

        self.assertEqual(entry['engine_result'], 'disabled')
        self.assertEqual(disabled_cfg['engine_result'], 'disabled-by-config')
        self.assertEqual(seen['env']['RENOVATE_USERNAME'], 'shtse8')
        self.assertEqual(seen['env']['RENOVATE_GIT_AUTHOR'], 'Kyle Tse <hi@kylet.se>')
        self.assertEqual(seen['env']['RENOVATE_SCHEDULE'], '[]')
        self.assertNotIn('RENOVATE_DRY_RUN', seen['env'])
        self.assertEqual(seen['config']['repositories'], ['EpiowAI/epiow'])
        self.assertEqual(seen['env']['RENOVATE_GENERAL_REPO'], 'EpiowAI/epiow')
        self.assertEqual(seen['env']['RENOVATE_GENERAL_READ_ONLY'], '0')

    def test_dependency_git_transport_strips_force_with_lease_and_blocks_main_or_force(self):
        import dependency_git_transport as dgt
        cleaned, branch = dgt.push_args(['--force-with-lease', '-u', 'origin', 'renovate/next-16.x'])
        self.assertEqual(cleaned, ['-u', 'origin', 'renovate/next-16.x'])
        self.assertEqual(branch, 'renovate/next-16.x')
        for bad in (
            ['--force', 'origin', 'renovate/x'],
            ['-f', 'origin', 'renovate/x'],
            ['origin', '+renovate/x'],
            ['origin', 'main'],
            ['origin', 'renovate/x:main'],
            ['--no-verify', 'origin', 'renovate/x'],
            ['--delete', 'origin', 'renovate/x'],
        ):
            with self.assertRaises(ValueError):
                dgt.push_args(bad)
        self.assertEqual(
            dgt.clone_args(['clone', '--filter=tree:0', '--', 'git@github.com:OzyrixLtd/site-b.git', '.'], 'OzyrixLtd/site-b'),
            ['clone', '--no-tags', '--filter=tree:0', '--', 'git@github.com:OzyrixLtd/site-b.git', '.'],
        )
        with self.assertRaises(ValueError):
            dgt.clone_args(['clone', 'git@github.com:Other/repo.git', '.'], 'OzyrixLtd/site-b')


if __name__ == '__main__':
    unittest.main()
