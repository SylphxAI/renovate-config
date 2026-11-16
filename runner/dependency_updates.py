#!/usr/bin/env python3
"""Desk/self-hosted general Renovate pass over active STO and OzyrixLtd repositories."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import re
import shutil
import subprocess
import sys
import tempfile

from github_io import GitHub, Refused, save
from pin_plan import parse_active_portfolio
from shared_pins import ENGINE_RESERVE, FLOOR, allocated, install_engine, private_directory, utcnow

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / 'dependency_config.json'
DEFAULT_EXTRA_ORGS = ('OzyrixLtd',)
GIT_AUTHOR = 'Kyle Tse <hi@kylet.se>'


def discover_scope(gh, *, extra_orgs=DEFAULT_EXTRA_ORGS, only_repos=()):
    """Resolve active STO and extra-org repositories without static repo lists."""
    if only_repos:
        candidates = sorted(set(only_repos), key=str.casefold)
        owner_sha = None
    else:
        owner_sha = gh.request('repos/SylphxAI/owner/commits/main')['sha']
        registers = gh.text('SylphxAI/owner', 'company/group-state-registers.md', owner_sha)
        repos = set(parse_active_portfolio(registers))
        for org in extra_orgs:
            for item in gh.pages(f'orgs/{org}/repos?type=sources'):
                full = item.get('full_name')
                if not full or item.get('archived') or item.get('fork') or item.get('disabled'):
                    continue
                repos.add(full)
        candidates = sorted(repos, key=str.casefold)

    active, skipped = [], []
    for repo in candidates:
        try:
            meta = gh.request(f'repos/{repo}')
            if meta.get('archived') or meta.get('disabled'):
                skipped.append({'repo': repo, 'skip': 'archived'})
                continue
            if meta.get('size') == 0 and gh.request(f'repos/{repo}/branches?per_page=1') == []:
                skipped.append({'repo': repo, 'skip': 'empty'})
                continue
            owner = repo.split('/', 1)[0]
            if owner == 'SylphxAI':
                props = gh.request(f'repos/{repo}/properties/values')
                if not isinstance(props, list):
                    raise Refused('repository-properties-unreadable')
                if any(p.get('property_name') == 'sylphx_delivery' and p.get('value') == 'delivered'
                       for p in props):
                    skipped.append({'repo': repo, 'skip': 'delivered'})
                    continue
            active.append(repo)
        except (Refused, OSError, ValueError, subprocess.SubprocessError) as error:
            cause = str(error) if isinstance(error, Refused) else type(error).__name__
            skipped.append({'repo': repo, 'error': cause})
    return owner_sha, active, skipped


def run_repo(gh, repo, root, binary, config_path, *, dry_run='full', force=False):
    """Run the locked native Renovate CLI on one repository."""
    base_config = json.loads(Path(config_path).read_text())
    folder = root / 'pass'
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    bindir = folder / 'bin'
    bindir.mkdir()
    (bindir / 'git').symlink_to(HERE / 'dependency_git_transport.py')
    clean_env = {k: v for k, v in gh.env.items()
                 if not k.startswith(('RENOVATE_', 'SHARED_PINS_', 'GIT_CONFIG_'))}
    base_path = clean_env.get('PATH', os.environ.get('PATH', ''))
    real_bun = shutil.which('bun', path=base_path)
    if real_bun:
        bun_shim = bindir / 'bun'
        quoted_bun = shlex.quote(real_bun)
        bun_shim.write_text(
            '#!/bin/sh\n'
            'case "$1" in\n'
            '  install|i)\n'
            '    for a in "$@"; do\n'
            '      case "$a" in --frozen-lockfile|--lockfile-only) exec ' + quoted_bun + ' "$@" ;; esac\n'
            '    done\n'
            '    shift\n'
            '    exec ' + quoted_bun + ' install --lockfile-only "$@"\n'
            '    ;;\n'
            'esac\n'
            'exec ' + quoted_bun + ' "$@"\n'
        )
        bun_shim.chmod(0o755)
    install_hook = '1' if shutil.which('desk-publish', path=base_path) else '0'
    read_only = '0' if dry_run == 'off' else '1'
    try:
        config = dict(base_config)
        config.update(
            repositories=[repo],
            baseDir=str(folder / 'work'),
            cacheDir=str(folder / 'cache'),
            customEnvVariables={
                'GIT_LFS_SKIP_SMUDGE': '1',
                'GIT_TERMINAL_PROMPT': '0',
                'RENOVATE_GENERAL_REPO': repo,
                'RENOVATE_GENERAL_READ_ONLY': read_only,
                'SHARED_PINS_INSTALL_HOOK': install_hook,
            },
        )
        run_config_path = folder / 'config.json'
        save(run_config_path, config)
        env = dict(
            clean_env,
            RENOVATE_TOKEN=gh._token,
            RENOVATE_USERNAME=gh.login,
            RENOVATE_GIT_AUTHOR=GIT_AUTHOR,
            RENOVATE_CONFIG_FILE=str(run_config_path),
            RENOVATE_REPOSITORIES=repo,
            LOG_LEVEL='info',
            LOG_FORMAT='json',
            GIT_LFS_SKIP_SMUDGE='1',
            GIT_TERMINAL_PROMPT='0',
            RENOVATE_GENERAL_REPO=repo,
            RENOVATE_GENERAL_READ_ONLY=read_only,
            SHARED_PINS_INSTALL_HOOK=install_hook,
        )
        env['RENOVATE_HOST_RULES'] = json.dumps([
            {'hostType': 'github', 'matchHost': 'github.com', 'token': gh._token}
        ])
        env['RENOVATE_CUSTOM_ENV_VARIABLES'] = json.dumps({
            **config['customEnvVariables'],
            'GIT_CONFIG_COUNT': '1',
            'GIT_CONFIG_KEY_0': f'url.https://x-access-token:{gh._token}@github.com/.insteadOf',
            'GIT_CONFIG_VALUE_0': 'https://github.com/',
        })
        if dry_run and dry_run != 'off':
            env['RENOVATE_DRY_RUN'] = dry_run
        if force:
            env['RENOVATE_SCHEDULE'] = '[]'
        env['PATH'] = str(bindir) + ':' + str(binary[0].parent) + ':' + base_path
        result = subprocess.run([str(binary[0]), str(binary[1])], env=env, cwd=HERE.parent,
                                capture_output=True, timeout=1200)
        if gh._token.encode() in result.stdout or gh._token.encode() in result.stderr:
            raise Refused('engine-diagnostic-credential-refused')
        terminal = []
        for line in result.stdout.splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if item.get('msg') == 'Repository finished' and item.get('repository') == repo:
                terminal.append(item)
        status = terminal[0].get('result') if len(terminal) == 1 else 'missing'
        if result.returncode or status not in ('done', 'disabled', 'disabled-by-config'):
            code = status if isinstance(status, str) and re.fullmatch(r'[a-z-]{1,64}', status) else 'unknown'
            raise Refused(f'native-engine-failed:{result.returncode}:{code}')
        return {
            'repo': repo,
            'engine_exit': result.returncode,
            'engine_result': status,
            'engine_cloned': terminal[0].get('cloned') is True,
            'cache_peak_bytes': allocated(root),
        }
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='run live Renovate writes without dry-run')
    parser.add_argument('--dry-run', choices=('off', 'lookup', 'full'), default=None)
    parser.add_argument('--force', action='store_true', help='ignore preset schedule window for this run')
    parser.add_argument('--repo', action='append', default=[], help='limit pass to named owner/repo (repeatable)')
    parser.add_argument('--org', action='append', default=[], help='extra orgs to scan (defaults to OzyrixLtd)')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--cache-root', type=Path, required=True)
    args = parser.parse_args()

    if args.apply and args.dry_run and args.dry_run != 'off':
        parser.error('--apply conflicts with --dry-run')
    dry_run = 'off' if args.apply else (args.dry_run or 'full')

    private_directory(args.state_dir)
    private_directory(args.cache_root)
    gh = GitHub(verify_user=False)
    extra_orgs = tuple(args.org) if args.org else DEFAULT_EXTRA_ORGS
    owner_sha, active, skipped = discover_scope(gh, extra_orgs=extra_orgs, only_repos=args.repo)
    report = {
        'read_at': utcnow().isoformat(),
        'apply': args.apply,
        'dry_run': dry_run,
        'force': args.force,
        'owner_head': owner_sha,
        'active_count': len(active),
        'results': list(skipped),
        'alerts': [],
        'cache_peak_bytes': 0,
    }
    with tempfile.TemporaryDirectory(prefix='renovate-pass-', dir=args.cache_root) as temporary:
        root = Path(temporary)
        binary = None
        for repo in active:
            if dry_run == 'off':
                gh.verify_connected_user()
                if gh.remaining() <= FLOOR + ENGINE_RESERVE:
                    raise Refused('native-engine-budget-reserve')
            try:
                binary = binary or install_engine(root)
                entry = run_repo(gh, repo, root, binary, args.config, dry_run=dry_run, force=args.force)
                report['cache_peak_bytes'] = max(report['cache_peak_bytes'], entry.get('cache_peak_bytes', 0))
                report['results'].append(entry)
            except (Refused, OSError, ValueError, subprocess.SubprocessError) as error:
                cause = str(error) if isinstance(error, Refused) else type(error).__name__
                report['alerts'].append({'repo': repo, 'reason': cause})
                report['results'].append({'repo': repo, 'error': cause})
        report['cache_peak_bytes'] = max(report['cache_peak_bytes'], allocated(root))
    report['cache_after_bytes'] = allocated(args.cache_root)
    save(args.state_dir / 'report.json', report)
    print(json.dumps({
        'report': str(args.state_dir / 'report.json'),
        'repositories': len(report['results']),
        'active': len(active),
        'alerts': len(report['alerts']),
        'cache_peak_bytes': report['cache_peak_bytes'],
        'cache_after_bytes': report['cache_after_bytes'],
    }))
    return 1 if report['alerts'] else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Refused, OSError, subprocess.SubprocessError) as error:
        print('renovate pass refused: ' + (str(error) if isinstance(error, Refused) else type(error).__name__),
              file=sys.stderr)
        sys.exit(1)
