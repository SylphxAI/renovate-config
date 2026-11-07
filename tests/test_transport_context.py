"""Actual repositories distinguish the proved cwd from a redirected push cwd."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runner'))
import git_transport
from pin_plan import parse_pins

ADAPTER = Path(git_transport.__file__).resolve()
OLD, NEW = 'a' * 40, 'b' * 40
BRANCH = 'renovate/shared-ci-week-2026-46'
FILE = '.github/workflows/a.yml'


class ContextBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pin-context-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.good, self.other, self.remote = (self.root / n for n in ('good', 'other', 'remote.git'))
        self.init(self.good)
        before = f'steps:\n  - uses: SylphxAI/.github/.github/actions/a@{OLD} # main\n'
        file = self.good / FILE
        file.parent.mkdir(parents=True)
        file.write_text(before)
        self.git(self.good, 'add', '.')
        self.git(self.good, 'commit', '-m', 'base')
        base = self.git(self.good, 'rev-parse', 'HEAD')
        self.git(self.good, 'checkout', '-b', BRANCH)
        file.write_text(before.replace(OLD, NEW))
        self.git(self.good, 'add', '.')
        self.git(self.good, 'commit', '-m', 'pins')
        self.git(self.good, 'remote', 'add', 'origin', 'https://github.com/SylphxAI/example.git')
        manifest = self.root / 'manifest.json'
        manifest.write_text(json.dumps({'repo': 'SylphxAI/example', 'base_head': base,
            'files': {FILE: before}, 'pins': parse_pins({FILE: before}), 'target': NEW}))
        self.init(self.other)
        (self.other / 'NOT-A-PIN').write_text('unproved arbitrary content')
        self.git(self.other, 'add', '.')
        self.git(self.other, 'commit', '-m', 'arbitrary')
        self.git(self.other, 'checkout', '-b', BRANCH)
        self.git(self.root, 'init', '--bare', str(self.remote))
        self.git(self.other, 'remote', 'add', 'origin', str(self.remote))
        self.claim, self.trace = self.root / 'claim', self.root / 'trace.jsonl'
        self.env.update(SHARED_PINS_BRANCH=BRANCH, SHARED_PINS_MANIFEST=str(manifest),
                        SHARED_PINS_PUSH_CLAIM=str(self.claim), SHARED_PINS_TEST_TRACE=str(self.trace))

    def git(self, cwd, *args):
        return subprocess.run(['/usr/bin/git', *args], cwd=cwd, env=self.env,
                              capture_output=True, text=True, check=True).stdout.strip()

    def init(self, path):
        path.mkdir()
        self.git(path, 'init', '-b', 'main')
        self.git(path, 'config', 'user.name', 'Kyle Tse')
        self.git(path, 'config', 'user.email', 'hi@kylet.se')

    def invoke(self, *args, extra_env=None):
        return subprocess.run([str(ADAPTER), *args], cwd=self.good,
                              env={**self.env, **(extra_env or {})}, capture_output=True, text=True)

    def no_other_ref(self):
        value = subprocess.run(['/usr/bin/git', '--git-dir', str(self.remote),
                                'show-ref', '--verify', f'refs/heads/{BRANCH}'],
                               env=self.env, capture_output=True)
        self.assertEqual(value.returncode, 128)

    def test_reviewer_other_repository_repro_and_context_overrides_are_refused(self):
        cases = [(['-C', str(self.other), 'push', 'origin', BRANCH], {}),
                 (['--git-dir', str(self.other / '.git'), 'push', 'origin', BRANCH], {}),
                 (['-C' + str(self.other), 'push', 'origin', BRANCH], {}),
                 (['--work-tree=' + str(self.other), 'status'], {}),
                 (['--exec-path=/tmp', 'status'], {}),
                 (['--config-env=core.worktree=REDIRECT', 'status'], {}),
                 (['push', '-c', 'core.quotePath=false', 'origin', BRANCH], {}),
                 (['-c', 'core.quotePath=true', 'status'], {}),
                 (['-c', 'core.sshCommand=evil', 'status'], {}),
                 (['push', 'origin', BRANCH], {'GIT_DIR': str(self.other / '.git')}),
                 (['push', 'origin', BRANCH], {'GIT_WORK_TREE': str(self.other)}),
                 (['push', 'origin', BRANCH], {'GIT_COMMON_DIR': str(self.other / '.git')}),
                 (['status'], {'GIT_INDEX_FILE': str(self.other / '.git/index')}),
                 (['status'], {'GIT_CONFIG': '/tmp/unapproved'}),
                 (['push', 'origin', BRANCH], {'GIT_CONFIG_PARAMETERS': "'core.hooksPath'='/dev/null'"})]
        for args, env in cases:
            with self.subTest(args=args, overrides=list(env)):
                result = self.invoke(*args, extra_env=env)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn('unsafe or uncertain', result.stderr)
                self.assertFalse(self.claim.exists())
                self.no_other_ref()
        calls = [json.loads(line) for line in self.trace.read_text().splitlines()]
        self.assertFalse(any(row[0] == '/usr/bin/git' for row in calls))

    def test_native_shape_passes_and_extra_auth_keys_or_hosts_refuse(self):
        auth = {'GIT_CONFIG_COUNT': '3'}
        key = 'url.https://x-access-token:synthetic-token@github.com/.insteadOf'
        for i, value in enumerate(('ssh://git@github.com/', 'git@github.com:', 'https://github.com/')):
            auth[f'GIT_CONFIG_KEY_{i}'], auth[f'GIT_CONFIG_VALUE_{i}'] = key, value
        result = self.invoke('-c', 'core.quotePath=false', 'status', '--porcelain', extra_env=auth)
        self.assertEqual(result.returncode, 0, result.stderr)
        for bad in ({'GIT_CONFIG_KEY_3': 'url.https://other.invalid/.insteadOf'},
                    {'GIT_CONFIG_KEY_0': 'url.https://x-access-token:synthetic-token@other.invalid/.insteadOf'},
                    {'GIT_CONFIG_COUNT': '5'}, {'GIT_CONFIG_GLOBAL': '/dev/null'},
                    {'GIT_SSH_COMMAND': 'arbitrary-command'},
                    {'GIT_TEST_DISALLOW_ABBREVIATED_OPTIONS': 'false'},
                    {'GIT_TEST_DISALLOW_ABBREVIATED_OPTIONS': '1'}):
            result = self.invoke('status', extra_env={**auth, **bad})
            self.assertNotEqual(result.returncode, 0)

    def test_proved_manifest_push_uses_one_context_and_validated_environment(self):
        real_call = git_transport.call
        calls = []
        def bound_call(args, **kwargs):
            calls.append((args, kwargs['directory'], kwargs['env']))
            if args[0] == 'ls-remote':
                return subprocess.CompletedProcess(args, 2, '', '')
            if args[0] == 'push':
                return subprocess.CompletedProcess(args, 0, '', '')
            return real_call(args, **kwargs)
        previous = Path.cwd()
        try:
            os.chdir(self.good)
            with patch.dict(os.environ, self.env, clear=True), patch.object(git_transport, 'call', side_effect=bound_call):
                self.assertEqual(git_transport.main(['-c', 'core.quotePath=false', 'push', 'origin', BRANCH]), 0)
        finally:
            os.chdir(previous)
        self.assertEqual(calls[-2][0], ['remote', 'get-url', '--push', '--all', 'origin'])
        self.assertEqual(calls[-1][0], ['push', 'origin', BRANCH])
        self.assertEqual({directory for _, directory, _ in calls}, {self.good.resolve()})
        self.assertTrue(all(env is calls[0][2] for _, _, env in calls))
        self.no_other_ref()

    def test_effective_target_still_catches_repo_redirect_if_input_schema_ever_misses_one(self):
        redirected = {**self.env, 'GIT_CONFIG_COUNT': '1',
                      'GIT_CONFIG_KEY_0': 'url.https://github.com/Other/unapproved.git.insteadOf',
                      'GIT_CONFIG_VALUE_0': 'https://github.com/SylphxAI/example.git'}
        previous = Path.cwd()
        try:
            os.chdir(self.good)
            with patch.dict(os.environ, self.env, clear=True), patch.object(git_transport, 'git_environment', return_value=redirected):
                with self.assertRaisesRegex(ValueError, 'selected consumer remote changed'):
                    git_transport.main(['push', 'origin', BRANCH])
        finally:
            os.chdir(previous)
        self.assertFalse(self.claim.exists())
        self.no_other_ref()

    def test_effective_same_host_repository_redirect_is_caught_after_absence_probe(self):
        real_call = git_transport.call
        calls = []
        environments = []
        directories = []
        def bound_call(args, **kwargs):
            calls.append(args)
            environments.append(kwargs['env'])
            directories.append(kwargs['directory'])
            if args[0] == 'ls-remote':
                # No network: a longer on-disk rewrite appears after the first
                # target inspection. The final inspection must still reject it.
                self.git(self.good, 'config', 'url.https://github.com/Other/unapproved.git.insteadOf',
                         'https://github.com/SylphxAI/example.git')
                return subprocess.CompletedProcess(args, 2, '', '')
            return real_call(args, **kwargs)
        previous = Path.cwd()
        try:
            os.chdir(self.good)
            with patch.dict(os.environ, self.env, clear=True), patch.object(git_transport, 'call', side_effect=bound_call):
                with self.assertRaisesRegex(ValueError, 'effective consumer push target changed'):
                    git_transport.main(['-c', 'core.quotePath=false', 'push', 'origin', BRANCH])
        finally:
            os.chdir(previous)
        self.assertTrue(self.claim.exists())
        self.assertEqual(calls[-1], ['remote', 'get-url', '--push', '--all', 'origin'])
        self.assertFalse(any(args[0] == 'push' for args in calls))
        self.assertTrue(all(env is environments[0] for env in environments))
        self.assertEqual(set(directories), {self.good.resolve()})
        self.no_other_ref()


if __name__ == '__main__':
    unittest.main()
