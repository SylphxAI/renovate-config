#!/usr/bin/env python3
"""Bounded Git transport for general desk Renovate runs (no force-push, no URL tokens)."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

from git_transport import call, github_url, hook_env, parse_clone_invocation, prepare_invocation

_BRANCH_RE = re.compile(r'renovate/(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+')
_REPO_RE = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')


def _expected_remotes(repo: str) -> set[str]:
    if not _REPO_RE.fullmatch(repo):
        raise ValueError('invalid target repository')
    return {f'https://github.com/{repo}', f'https://github.com/{repo}.git'}


def _valid_general_branch(name: str) -> bool:
    if not _BRANCH_RE.fullmatch(name):
        return False
    return '..' not in name and not name.endswith('.lock')


def clone_args(args: list[str], repo: str) -> list[str]:
    """Validate clone target and flags without persisting credentials or unapproved filters."""
    flags, positional, saw_end_opts = parse_clone_invocation(args)
    if github_url(positional[0]) not in _expected_remotes(repo):
        raise ValueError('clone repository mismatch')
    selected = [a for a in flags if a != '--no-tags']
    tail = ['--', *positional] if saw_end_opts else positional
    return ['clone', '--no-tags', *selected, *tail]


def push_args(args: list[str]) -> tuple[list[str], str]:
    """Translate Renovate's new-branch force-with-lease into an ordinary non-force push."""
    if ('--no-verify' in args
            or any(a in ('--force', '-f', '--delete', '--mirror', '--all', '--tags') or a.startswith('--force=')
                   for a in args)):
        raise ValueError('unapproved push option')
    cleaned = [a for a in args if a != '--force-with-lease' and not a.startswith('--force-with-lease=')]
    if any(a.startswith('-') and a not in ('-u', '--verbose', '--porcelain') for a in cleaned):
        raise ValueError('unapproved push option')
    if cleaned.count('origin') != 1:
        raise ValueError('push must target origin')
    refs = [a for a in cleaned if a != 'origin' and not a.startswith('-')]
    if len(refs) != 1:
        raise ValueError('push must name exactly one ref')
    ref = refs[0]
    if ref.startswith('+'):
        raise ValueError('force push refused')
    if ':' in ref:
        src, dst = ref.split(':', 1)
        if not src or any(c.isspace() for c in src):
            raise ValueError('invalid push source')
        branch = dst[len('refs/heads/'):] if dst.startswith('refs/heads/') else dst
    else:
        branch = ref
    if not _valid_general_branch(branch):
        raise ValueError('push limited to renovate/* branches')
    return cleaned, branch


def main(args: list[str]) -> int:
    command, args, directory, env = prepare_invocation(args)
    repo = os.environ.get('RENOVATE_GENERAL_REPO', '')

    def run(values, *, capture=False):
        return call(values, directory=directory, env=env, capture=capture)

    if command == 'clone':
        result = run(clone_args(args, repo))
        if result.returncode:
            return result.returncode
        if os.environ.get('SHARED_PINS_INSTALL_HOOK') == '1':
            return subprocess.run(['desk-publish', 'install-hook', str((directory / args[-1]).resolve())],
                                  env=hook_env(env), check=False).returncode
        return 0
    if command == 'push':
        if os.environ.get('RENOVATE_GENERAL_READ_ONLY', '1') == '1':
            raise ValueError('dry run cannot push')
        cleaned, _branch = push_args(args[1:])
        expected = _expected_remotes(repo)
        resolved = run(['rev-parse', '--show-toplevel'], capture=True)
        if resolved.returncode or not Path(resolved.stdout.strip()).is_dir():
            raise ValueError('unresolved consumer repository')
        top = Path(resolved.stdout.strip()).resolve()
        remote = call(['remote', 'get-url', 'origin'], directory=top, env=env, capture=True)
        push_remote = call(['remote', 'get-url', '--push', '--all', 'origin'], directory=top, env=env, capture=True)
        if remote.returncode or remote.stdout.strip() not in expected:
            raise ValueError('selected consumer remote changed')
        if push_remote.returncode or push_remote.stdout.strip() != remote.stdout.strip():
            raise ValueError('selected consumer push remote changed')
        return call(['push', *cleaned], directory=top, env=hook_env(env)).returncode
    if '--no-verify' in args:
        raise ValueError('verification bypass refused')
    if '--force' in args or any(a.startswith('--force-with-lease') for a in args):
        raise ValueError('force option refused')
    return run(args).returncode


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, ValueError):
        print('renovate Git transport refused an unsafe or uncertain operation', file=sys.stderr)
        sys.exit(1)
