#!/usr/bin/env python3
"""Bound Renovate's Git transport to sparse clones and immutable branch creation.

Renovate asks for force-with-lease even for a new ref. Translate only that
create case to an ordinary push; never update an existing remote ref. This is
not a dependency writer: Renovate still extracts, resolves, edits and commits.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

REAL_GIT = '/usr/bin/git'


def push_args(args: list[str], branch: str) -> list[str]:
    """The sole admitted mutation is a plain push to this one new branch."""
    if not re.fullmatch(r'renovate/shared-ci-(?:week-\d{4}-\d{2}|fix-[a-f0-9]{40})', branch):
        raise ValueError('invalid immutable branch')
    if '--no-verify' in args or any(a in args for a in ('--force', '-f', '--delete', '--mirror', '--all', '--tags')):
        raise ValueError('unapproved push option')
    cleaned = [a for a in args if a != '--force-with-lease']
    if any(a.startswith('-') and a not in ('-u', '--verbose', '--porcelain') for a in cleaned):
        raise ValueError('unapproved push option')
    expected = {branch, f'{branch}:{branch}', f'{branch}:refs/heads/{branch}'}
    refs = [a for a in cleaned if ':' in a or a == branch]
    if len(refs) != 1 or refs[0] not in expected or 'origin' not in cleaned:
        raise ValueError('push is not the selected immutable branch')
    if any(a.startswith('+') or a.startswith('--force') for a in cleaned):
        raise ValueError('force push refused')
    return cleaned


def clone_args(args: list[str]) -> list[str]:
    if any(a.startswith(('https://', 'http://')) and '@' in a for a in args):
        raise ValueError('credential-bearing URL refused')
    # The engine supplies [clone, -b, base, URL, .]; never materialize asset blobs.
    return [args[0], '--depth=1', '--filter=blob:none', '--no-checkout', *args[1:]]


def call(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_LFS_SKIP_SMUDGE='1')
    # Local remote inspection must describe the stored credential-free URL,
    # not Git's environment-only authenticated rewrite.
    if 'remote' in args:
        for key in list(env):
            if key == 'GIT_CONFIG_COUNT' or key.startswith(('GIT_CONFIG_KEY_', 'GIT_CONFIG_VALUE_')):
                env.pop(key, None)
    trace = os.environ.get('SHARED_PINS_TEST_TRACE')
    if trace:
        import json
        with open(trace, 'a') as output:
            output.write(json.dumps([REAL_GIT, *args]) + '\n')
    result = subprocess.run([REAL_GIT, *args], capture_output=True, text=True, env=env, check=False)
    # Git may echo the authenticated environment rewrite in network errors.
    # Strip URL userinfo before returning anything to the engine/logger.
    result.stdout = re.sub(r'(https?://)[^/\s@]+@', r'\1', result.stdout)
    result.stderr = re.sub(r'(https?://)[^/\s@]+@', r'\1', result.stderr)
    if not capture:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
    return result


def main(args: list[str]) -> int:
    if os.environ.get('SHARED_PINS_TEST_TRACE'):
        import json
        with open(os.environ['SHARED_PINS_TEST_TRACE'], 'a') as output:
            output.write(json.dumps(['adapter', *args]) + '\n')
    if not args:
        return call(args).returncode
    # simple-git puts -c key=value before the subcommand. Do not search
    # arbitrary values for command names or admit alternate remote writers.
    index = 0
    while index < len(args) and args[index] in ('-c', '-C'):
        if index + 1 >= len(args):
            raise ValueError('missing git config')
        key = args[index + 1].split('=', 1)[0]
        if args[index] == '-c' and key not in ('core.quotePath',):
            raise ValueError('unapproved command config')
        index += 2
    command = args[index] if index < len(args) else ''
    allowed = {'version', '--version', 'rev-parse', 'status', 'config', 'remote', 'init',
               'fetch', 'checkout', 'reset', 'clean', 'branch', 'log', 'show', 'show-ref',
               'ls-files', 'ls-tree', 'ls-remote', 'diff', 'diff-tree', 'cat-file',
               'merge-base', 'merge', 'add', 'commit', 'symbolic-ref', 'check-ignore',
               'for-each-ref', 'check-attr', 'rev-list', 'check-ref-format', 'submodule', 'tag', 'clone', 'push', 'sparse-checkout'}
    if command not in allowed:
        raise ValueError('unapproved Git command')
    if any(re.search(r'https?://[^/\s]+@', a) for a in args):
        raise ValueError('credential-bearing Git argv refused')
    if command == 'clone':
        index = args.index('clone')
        result = call(args[:index] + clone_args(args[index:]))
        if result.returncode:
            return result.returncode
        # Last argument is Renovate's target directory. Non-cone patterns do
        # not hydrate unrelated root files or LFS assets.
        target = args[-1]
        result = call(['-C', target, 'sparse-checkout', 'set', '--no-cone',
                       '/.github/', '/renovate.json', '/renovate.json5', '/.renovaterc', '/.renovaterc.json'])
        if result.returncode:
            return result.returncode
        if os.environ.get('SHARED_PINS_INSTALL_HOOK') == '1':
            return subprocess.run(['desk-publish', 'install-hook', str(Path(target).resolve())], check=False).returncode
        return 0
    if command == 'push':
        index = args.index('push')
        branch = os.environ.get('SHARED_PINS_BRANCH', '')
        cleaned = push_args(args[index + 1:], branch)
        if os.environ.get('SHARED_PINS_READ_ONLY') == '1':
            raise ValueError('dry run cannot push')
        manifest = os.environ.get('SHARED_PINS_MANIFEST')
        if manifest:
            import json
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from pin_proof import prove_files
            proof = json.loads(Path(manifest).read_text())
            parent = call(['rev-parse', f'{branch}^'], capture=True)
            if parent.returncode or parent.stdout.strip() != proof['base_head']:
                raise ValueError('consumer base changed')
            changed = call(['diff', '--name-only', f'{branch}^', branch], capture=True)
            if changed.returncode or any(p not in proof['files'] for p in changed.stdout.splitlines()):
                raise ValueError('unapproved changed path')
            after = {}
            for path, text in proof['files'].items():
                value = call(['show', f'{branch}:{path}'], capture=True)
                if value.returncode:
                    raise ValueError('unreadable candidate')
                after[path] = value.stdout
            if prove_files(proof['files'], after, proof['pins'], proof['target'], require_main=False):
                raise ValueError('candidate is not a SHA-only move')
        elif os.environ.get('SHARED_PINS_TEST_TRANSPORT') != '1':
            raise ValueError('missing source manifest')
        # An interrupted request is never repeated: claim before the first
        # attempt. A later pass reconciles branch/PR state instead.
        marker = Path(os.environ['SHARED_PINS_PUSH_CLAIM'])
        with marker.open('x') as out:
            out.write(branch + '\n')
        result = call(args[:index] + ['ls-remote', '--exit-code', '--heads', 'origin', f'refs/heads/{branch}'], capture=True)
        if result.returncode != 2 or result.stdout.strip():
            raise ValueError('remote branch exists or absence is unproved; refusing mutation')
        return call(args[:index] + ['push', *cleaned]).returncode
    if '--no-verify' in args:
        raise ValueError('verification bypass refused')
    # Fetch/rebase of an existing roll is not part of this writer's contract.
    if '--force' in args or any(a.startswith('--force-with-lease') for a in args):
        raise ValueError('force option refused')
    return call(args).returncode


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, ValueError):
        print('shared-ci Git transport refused an unsafe or uncertain operation', file=sys.stderr)
        sys.exit(1)
