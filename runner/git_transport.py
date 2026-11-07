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
    if (len(refs) != 1 or refs[0] not in expected or cleaned.count('origin') != 1
            or any(a not in expected | {'origin', '-u', '--verbose', '--porcelain'} for a in cleaned)):
        raise ValueError('push is not the selected immutable branch')
    if any(a.startswith('+') or a.startswith('--force') for a in cleaned):
        raise ValueError('force push refused')
    return cleaned


def clone_args(args: list[str]) -> list[str]:
    # Accept only the native clone grammar; Git accepts abbreviated options and
    # attached -c values, so a denylist of configuration spellings is unsafe.
    if not args or args[0] != 'clone':
        raise ValueError('invalid clone command')
    positional = []
    i = 1
    while i < len(args):
        value = args[i]
        if value in ('-b', '--branch'):
            if i + 1 >= len(args) or args[i + 1].startswith('-'):
                raise ValueError('missing clone branch')
            i += 2
            continue
        if (value in ('--no-checkout', '--single-branch', '--no-tags', '--quiet')
                or re.fullmatch(r'--depth=\d+', value)
                or value.startswith('--filter=')):
            i += 1
            continue
        if value.startswith('-'):
            raise ValueError('clone configuration override refused')
        positional.append(value)
        i += 1
    if len(positional) != 2:
        raise ValueError('invalid clone target')
    if any(a.startswith(('https://', 'http://')) and '@' in a for a in args):
        raise ValueError('credential-bearing URL refused')
    # The engine supplies [clone, -b, base, URL, .]; never materialize asset blobs.
    # Repeated --filter combines filters, which GitHub rejects. Replace the
    # native blob filter instead of appending another one.
    selected = [a for a in args[1:] if not a.startswith(('--filter=', '--depth=')) and a != '--no-checkout']
    return [args[0], '--depth=1', '--filter=blob:none', '--no-checkout', *selected]


def git_environment():
    """Accept only the native same-host auth shape; bind one effective env."""
    fixed = {'GIT_LFS_SKIP_SMUDGE': '1', 'GIT_TERMINAL_PROMPT': '0',
             'GIT_SSH_COMMAND': 'ssh -o BatchMode=yes',
             'GIT_TEST_DISALLOW_ABBREVIATED_OPTIONS': 'true'}
    inherited = {k: v for k, v in os.environ.items() if k.startswith('GIT_')}
    count = inherited.get('GIT_CONFIG_COUNT')
    auth = {}
    if count is not None:
        # One canonical rewrite, the native auth helper's exact trio, or our
        # initial canonical rewrite followed by that same native trio.
        shapes = {'1': ['https://github.com/'],
                  '3': ['ssh://git@github.com/', 'git@github.com:', 'https://github.com/'],
                  '4': ['https://github.com/', 'ssh://git@github.com/',
                        'git@github.com:', 'https://github.com/']}
        if count not in shapes:
            raise ValueError('unapproved Git auth count')
        keys = [inherited.get(f'GIT_CONFIG_KEY_{i}', '') for i in range(int(count))]
        values = [inherited.get(f'GIT_CONFIG_VALUE_{i}') for i in range(int(count))]
        if (len(set(keys)) != 1 or not re.fullmatch(
                r'url\.https://x-access-token:[A-Za-z0-9_%.-]+@github\.com/\.insteadOf', keys[0])
                or values != shapes[count]):
            raise ValueError('unapproved Git auth rewrite')
        auth = {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': keys[0],
                'GIT_CONFIG_VALUE_0': 'https://github.com/'}
        accepted = {'GIT_CONFIG_COUNT', *(f'GIT_CONFIG_{kind}_{i}'
                    for i in range(int(count)) for kind in ('KEY', 'VALUE'))}
    else:
        accepted = set()
    for key, value in inherited.items():
        if key not in accepted and (key not in fixed or value != fixed[key]):
            raise ValueError('unapproved Git environment override')
    return {**{k: v for k, v in os.environ.items() if not k.startswith('GIT_')}, **fixed, **auth}


def github_url(value):
    """Keep native SSH argv credential-free, but use HTTPS for real Git."""
    for prefix in ('git@github.com:', 'ssh://git@github.com/'):
        if value.startswith(prefix):
            path = value[len(prefix):]
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', path):
                raise ValueError('unapproved GitHub SSH target')
            return 'https://github.com/' + path
    return value


def call(args: list[str], *, directory: Path, env: dict, capture: bool = False) -> subprocess.CompletedProcess:
    # The directory and validated environment are supplied once by main and
    # reused for proof, effective-target inspection, absence probe and push.
    argv = [REAL_GIT, '-C', str(directory), *(github_url(a) for a in args)]
    trace = os.environ.get('SHARED_PINS_TEST_TRACE')
    if trace:
        import json
        with open(trace, 'a') as output:
            output.write(json.dumps(argv) + '\n')
    result = subprocess.run(argv, capture_output=True, text=True, env=env, check=False)
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
    # The native library hard-codes this one presentation setting. Consume it
    # literally, never forward any caller-supplied global option to real Git.
    if args[:2] == ['-c', 'core.quotePath=false']:
        args = args[2:]
    if not args:
        raise ValueError('missing Git subcommand')
    command = args[0]
    index = 0
    if any(re.match(r'^-(?:c|C)(?:.|$)|^--(?:git-dir|work-tree|exec-path|config-env|namespace|super-prefix)(?:=|$)', a)
           for a in args):
        raise ValueError('Git context/configuration override refused')
    env = git_environment()
    directory = Path.cwd().resolve()
    def run(values, *, capture=False):
        return call(values, directory=directory, env=env, capture=capture)
    allowed = {'version', '--version', 'rev-parse', 'status', 'config', 'remote', 'init',
               'fetch', 'checkout', 'reset', 'clean', 'branch', 'log', 'show', 'show-ref',
               'ls-files', 'ls-tree', 'ls-remote', 'diff', 'diff-tree', 'cat-file',
               'merge-base', 'merge', 'add', 'commit', 'symbolic-ref', 'check-ignore',
               'for-each-ref', 'check-attr', 'rev-list', 'check-ref-format', 'submodule', 'tag', 'clone', 'push', 'sparse-checkout'}
    if command not in allowed:
        raise ValueError('unapproved Git command')
    if any(re.search(r'https?://[^/\s]+@', a) for a in args):
        raise ValueError('credential-bearing Git argv refused')
    if command == 'config':
        options = args[index + 1:]
        if any(re.search(r'(?i)hooksPath|^include(?:If)?\.', a) for a in options):
            raise ValueError('hook configuration override refused')
        reads = {'--get', '--get-all', '--get-regexp', '--get-urlmatch', '--list', '-l'}
        if not any(a in reads for a in options):
            values = [a for a in options if a != '--local']
            if len(values) == 2 and values[0] not in ('user.name', 'user.email'):
                raise ValueError('unapproved Git configuration write')
            if len(values) > 2 or any(a.startswith('-') for a in values):
                raise ValueError('unapproved Git configuration operation')
    if command == 'remote':
        options = args[index + 1:]
        # Renovate may inspect a remote or set its credential-free fetch URL;
        # it must never install an alternate pushurl or additional target.
        if options and options[0] == 'set-url':
            if len(options) != 3 or options[1] != 'origin' or options[2].startswith('-'):
                raise ValueError('remote mutation refused')
        elif options and options[0] not in ('get-url', '-v', '--verbose'):
            raise ValueError('remote mutation refused')
    if command == 'clone':
        index = args.index('clone')
        result = run(clone_args(args))
        if result.returncode:
            return result.returncode
        # Last argument is Renovate's target directory. Non-cone patterns do
        # not hydrate unrelated root files or LFS assets.
        target = args[-1]
        result = call(['sparse-checkout', 'set', '--no-cone',
                       '/.github/', '/renovate.json', '/renovate.json5', '/.renovaterc', '/.renovaterc.json'],
                      directory=(directory / target).resolve(), env=env)
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
        resolved = run(['rev-parse', '--show-toplevel'], capture=True)
        if resolved.returncode or not Path(resolved.stdout.strip()).is_dir():
            raise ValueError('unresolved consumer repository')
        directory = Path(resolved.stdout.strip()).resolve()
        manifest = os.environ.get('SHARED_PINS_MANIFEST')
        if manifest:
            import json
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from pin_proof import prove_files
            proof = json.loads(Path(manifest).read_text())
            remote = run(['remote', 'get-url', 'origin'], capture=True)
            push_remote = run(['remote', 'get-url', '--push', '--all', 'origin'], capture=True)
            repo = proof['repo']
            expected = {f'https://github.com/{repo}', f'https://github.com/{repo}.git'}
            if remote.returncode or remote.stdout.strip() not in expected:
                raise ValueError('selected consumer remote changed')
            if push_remote.returncode or push_remote.stdout.strip() != remote.stdout.strip():
                raise ValueError('selected consumer push remote changed')
            parent = run(['rev-parse', f'{branch}^'], capture=True)
            if parent.returncode or parent.stdout.strip() != proof['base_head']:
                raise ValueError('consumer base changed')
            changed = run(['diff', '--name-only', f'{branch}^', branch], capture=True)
            if changed.returncode or any(p not in proof['files'] for p in changed.stdout.splitlines()):
                raise ValueError('unapproved changed path')
            after = {}
            for path, text in proof['files'].items():
                value = run(['show', f'{branch}:{path}'], capture=True)
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
        result = run(['ls-remote', '--exit-code', '--heads', 'origin', f'refs/heads/{branch}'], capture=True)
        if result.returncode != 2 or result.stdout.strip():
            raise ValueError('remote branch exists or absence is unproved; refusing mutation')
        if manifest:
            effective = run(['remote', 'get-url', '--push', '--all', 'origin'], capture=True)
            if effective.returncode or effective.stdout.strip() not in expected:
                raise ValueError('effective consumer push target changed')
        return run(['push', *cleaned]).returncode
    if '--no-verify' in args:
        raise ValueError('verification bypass refused')
    # Fetch/rebase of an existing roll is not part of this writer's contract.
    if '--force' in args or any(a.startswith('--force-with-lease') for a in args):
        raise ValueError('force option refused')
    return run(args).returncode


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, ValueError):
        print('shared-ci Git transport refused an unsafe or uncertain operation', file=sys.stderr)
        sys.exit(1)
