#!/usr/bin/env python3
"""One serial weekly/marked-fix Renovate pass, with a read-only lag report."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from github_io import GitHub, Refused, save
from pin_plan import parse_active_portfolio, parse_pins, plan_repo
from pin_proof import prove_files

HERE = Path(__file__).resolve().parent
SOURCE = 'SylphxAI/.github'
FLOOR = 3000
ENGINE_RESERVE = 400


def utcnow():
    return datetime.now(timezone.utc)


def regular_due(now):
    return now.weekday() == 0 and now.hour == 4 and now.minute >= 17


def private_directory(path):
    if path.is_symlink():
        raise Refused('directory-is-symlink')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_uid != os.getuid() or not path.is_dir():
        raise Refused('directory-owner-or-type')


def allocated(path):
    seen, size = set(), 0
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in [root, *(str(Path(root) / n) for n in dirs + files)]:
            try:
                stat = os.lstat(name)
                key = (stat.st_dev, stat.st_ino)
                if key not in seen:
                    seen.add(key)
                    size += stat.st_blocks * 512
            except FileNotFoundError:
                pass
    return size


def engine_config(repo, pins, branch_key, root):
    config = json.loads((HERE / 'config.json').read_text())
    custom = []
    for path in sorted({p['path'] for p in pins if re.fullmatch('[a-fA-F0-9]{40}', (p.get('sha') or ''))}):
        matches = []
        for pin in pins:
            if pin['path'] != path or not re.fullmatch('[a-fA-F0-9]{40}', (pin.get('sha') or '')):
                continue
            match = pin['match']
            # Literal source context is escaped; only the source's SHA span is
            # a capture. No lookaround/backreferences: compatible with RE2.
            offset = pin.get('match_sha_start', match.index((pin.get('sha') or '')))
            matches.append(re.escape(match[:offset]) + '(?<currentDigest>[a-fA-F0-9]{40})' +
                           re.escape(match[offset + 40:]))
        custom.append({'customType': 'regex', 'managerFilePatterns': ['/^' + re.escape(path) + '$/'],
                       'matchStrings': matches, 'depNameTemplate': SOURCE,
                       'datasourceTemplate': 'github-digest', 'versioningTemplate': 'exact',
                       'currentValueTemplate': 'main'})
    topic = f'shared-ci-{branch_key}'
    config.update(repositories=[repo], customManagers=custom, groupName='shared CI action pins',
                  groupSlug=topic, branchTopic=topic, group={'branchTopic': topic},
                  baseDir=str(root / 'work'), cacheDir=str(root / 'cache'))
    return config


def install_engine(root):
    engine = root / 'engine'
    engine.mkdir()
    for name in ('package.json', 'package-lock.json'):
        shutil.copyfile(HERE / name, engine / name)
    # No user delegation goes to the package registry or package install scripts.
    env = {k: v for k, v in os.environ.items() if not any(s in k for s in ('TOKEN', 'PASSWORD', 'SECRET'))}
    env['npm_config_cache'] = str(root / 'npm-cache')
    result = subprocess.run(['npm', 'ci', '--prefix', str(engine), '--omit=dev', '--no-audit', '--no-fund'],
                            env=env, capture_output=True, timeout=600)
    if result.returncode:
        raise Refused('locked-engine-install-failed')
    node = engine / 'node_modules/node/bin/node'
    cli = engine / 'node_modules/renovate/dist/renovate.js'
    if not node.is_file() or not cli.is_file():
        raise Refused('locked-engine-entrypoint-missing')
    return node, cli


def run_engine(gh, row, key, target, root, state, binary, *, dry_run):
    repo = row['repo']
    branch = 'renovate/shared-ci-' + key
    folder = root / 'pass'
    folder.mkdir()
    bindir = folder / 'bin'
    bindir.mkdir()
    (bindir / 'git').symlink_to(HERE / 'git_transport.py')
    config = engine_config(repo, row['pins'], key, folder)
    config_path = folder / 'config.json'
    manifest_path = folder / 'manifest.json'
    save(manifest_path, dict(base_head=row['head'], target=target, pins=[p for p in row['pins'] if p.get('sha')], files=row['files']))
    claim = state / (hashlib.sha256((repo + ':' + key).encode()).hexdigest() + '.push-claim')
    config['customEnvVariables'] = {
        'GIT_LFS_SKIP_SMUDGE': '1', 'SHARED_PINS_BRANCH': branch,
        'SHARED_PINS_MANIFEST': str(manifest_path), 'SHARED_PINS_PUSH_CLAIM': str(claim),
        'SHARED_PINS_INSTALL_HOOK': '1', 'SHARED_PINS_READ_ONLY': '1' if dry_run else '0'}
    save(config_path, config)
    if claim.exists():
        raise Refused('prior-push-attempt-needs-reconciliation')
    env = dict(gh.env, RENOVATE_TOKEN=gh._token, RENOVATE_USERNAME=gh.login,
               RENOVATE_CONFIG_FILE=str(config_path), LOG_LEVEL='info', LOG_FORMAT='json',
               GIT_LFS_SKIP_SMUDGE='1', SHARED_PINS_BRANCH=branch,
               SHARED_PINS_MANIFEST=str(manifest_path), SHARED_PINS_PUSH_CLAIM=str(claim),
               SHARED_PINS_INSTALL_HOOK='1', SHARED_PINS_READ_ONLY='1' if dry_run else '0')
    env['PATH'] = str(bindir) + ':' + str(binary[0].parent) + ':' + os.environ['PATH']
    # Renovate's SSH remotes carry no credential. Its supported host-rule Git
    # adapter supplies HTTPS authentication in child environment variables only.
    env['RENOVATE_HOST_RULES'] = json.dumps([{'hostType': 'github', 'matchHost': 'github.com', 'token': gh._token}])
    if dry_run:
        env['RENOVATE_DRY_RUN'] = 'full'
    try:
        result = subprocess.run([str(binary[0]), str(binary[1])], env=env, cwd=HERE.parent,
                                capture_output=True, timeout=1200)
        if gh._token.encode() in result.stdout or gh._token.encode() in result.stderr:
            raise Refused('engine-diagnostic-credential-refused')
        if result.returncode:
            raise Refused('native-engine-failed')
        # Never retain raw native logs: configuration can contain authentication.
        return {'engine_exit': result.returncode, 'branch': branch}
    finally:
        row['cache_peak_bytes'] = allocated(root)
        shutil.rmtree(folder)


def collect_files(gh, repo, head, blob_cache):
    tree = gh.request(f'repos/{repo}/git/trees/{head}?recursive=1')
    if tree.get('truncated'):
        raise Refused('consumer-tree-truncated')
    files = {}
    for entry in tree['tree']:
        path = entry['path']
        if entry['type'] != 'blob' or not path.startswith('.github/') or not path.endswith(('.yml', '.yaml')):
            continue
        if entry['sha'] not in blob_cache:
            if entry.get('size', 0) > 2_000_000:
                raise Refused('workflow-too-large')
            blob_cache[entry['sha']] = gh.text(repo, path, head)
        files[path] = blob_cache[entry['sha']]
    return files


def fixes(gh):
    result = []
    for issue in gh.pages(f'repos/{SOURCE}/issues?state=closed&labels=shared-action-fix'):
        if 'pull_request' not in issue:
            continue
        pr = gh.request(f'repos/{SOURCE}/pulls/{issue["number"]}')
        if not pr.get('merged_at'):
            continue
        paths = gh.pages(f'repos/{SOURCE}/pulls/{pr["number"]}/files')
        result.append({'number': pr['number'], 'sha': pr['merge_commit_sha'], 'merged_at': pr['merged_at'],
                       'files': [p['filename'] for p in paths]})
    return result


def changes_since_pin(gh, pins, head, fix_rows):
    """Read first relevant outstanding commits, with explicit incomplete findings.

    The comparison's aggregate file list is capped by GitHub. A truncated graph
    or file inventory is reported as unknown, never as no lag. Per-commit files
    are read only until each consumed root has an oldest outstanding change.
    """
    changes, unknown = [], []
    shas = sorted({p['sha'] for p in pins if re.fullmatch('[a-fA-F0-9]{40}', (p.get('sha') or '')) and p['sha'] != head})
    for old in shas:
        comparison = gh.compare(old, head)
        if not gh.forward(old, head):
            unknown.append({'sha': old, 'reason': 'pin-is-not-source-main-ancestor'})
            continue
        commits = comparison.get('commits', [])
        if comparison.get('total_commits', len(commits)) > len(commits):
            unknown.append({'sha': old, 'reason': 'source-history-incomplete'})
            continue
        roots = {r for p in pins if p['sha'] == old for r in p.get('consumed_roots', p.get('roots', ['']))}
        pending = set(roots or [''])
        for commit in commits:
            if not pending:
                break
            detail = gh.cache.get(('commit', commit['sha']))
            if detail is None:
                detail = gh.request(f'repos/{SOURCE}/commits/{commit["sha"]}')
                gh.cache[('commit', commit['sha'])] = detail
            paths = [p['filename'] for p in detail.get('files', [])]
            if len(paths) >= 300:
                unknown.append({'sha': old, 'reason': 'commit-files-incomplete'})
            affected = {r for r in pending if not r or any(p.startswith(r.rstrip('/') + '/') or p == r or
                        p.startswith(('scripts/', '.github/actions/')) and not r for p in paths)
                        or any(p.startswith('scripts/') for p in paths)}
            if affected:
                changes.append({'sha': commit['sha'], 'merged_at': commit['commit']['committer']['date'],
                                'files': paths, 'behind_pins': [old]})
                pending -= affected
        for fix in fix_rows:
            if gh.forward(old, fix['sha']) and old != fix['sha']:
                fix.setdefault('behind_pins', []).append(old)
            elif gh.forward(fix['sha'], old):
                fix.setdefault('included_by_pins', []).append(old)
    return changes, unknown


def verify_and_arm(gh, row, pr, roster, target, state):
    repo, head = row['repo'], pr['head']['sha']
    errors = []
    if repo not in roster:
        errors.append('not-active-roster')
    # Get the actual PR's complete file inventory and the exact opened head.
    changed = gh.pages(f'repos/{repo}/pulls/{pr["number"]}/files')
    paths = {p['filename'] for p in changed}
    if any(p.get('status') != 'modified' or p['filename'] not in row['files'] for p in changed):
        errors.append('unapproved-changed-file')
    after = dict(row['files'])
    for path in paths & row['files'].keys():
        after[path] = gh.text(repo, path, head)
    errors += prove_files(row['files'], after, [p for p in row['pins'] if p.get('sha')], target)
    main = gh.request(f'repos/{SOURCE}/commits/main')['sha']
    if not gh.forward(target, main):
        errors.append('new-sha-not-on-source-main')
    for pin in row['pins']:
        if pin.get('sha') and not gh.forward(pin['sha'], target):
            errors.append('not-forward-source-ancestry')
    current = gh.request(f'repos/{repo}/pulls/{pr["number"]}')
    if current['head']['sha'] != head or current.get('state') != 'open':
        errors.append('opened-head-changed')
    receipt = {'repo': repo, 'pr': pr['html_url'], 'head': head, 'proof': sorted(set(errors)),
               'checked_at': utcnow().isoformat(), 'armed': False}
    path = state / f'arm-{repo.replace("/", "--")}-{pr["number"]}.json'
    if not errors:
        # Receipt before mutation: unknown arm outcomes reconcile, never resend.
        if path.exists():
            return dict(receipt, proof=['prior-arm-attempt-needs-reconciliation'])
        receipt['arm_attempted'] = True
        save(path, receipt)
        gh.arm(repo, pr['number'], head)
        observed = gh.request(f'repos/{repo}/pulls/{pr["number"]}')
        # REST auto_merge can be null once queued; the normal gh command's
        # result is retained separately from queue admission, not a merge claim.
        receipt.update(armed=True, auto_merge=observed.get('auto_merge'), state=observed['state'])
    save(path, receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--cache-root', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, help='offline discovery fixture; never permits apply')
    parser.add_argument('--portfolio', type=Path, help='portfolio fixture, with --inventory only')
    parser.add_argument('--source-head', help='source fixture SHA, with --inventory only')
    parser.add_argument('--now', help='test clock, with --inventory only')
    parser.add_argument('--engine-dry-run', action='store_true')
    args = parser.parse_args(argv)
    if args.apply and (args.inventory or args.portfolio or args.source_head or args.now or args.engine_dry_run):
        parser.error('apply cannot use fixture/dry-run inputs')
    private_directory(args.state_dir)
    private_directory(args.cache_root)
    with (args.state_dir / 'runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        now = datetime.fromisoformat(args.now.replace('Z', '+00:00')) if args.now else utcnow()
        gh = None if args.inventory else GitHub()
        report = {'read_at': now.isoformat(), 'apply': args.apply, 'regular_due': regular_due(now),
                  'repositories': [], 'alerts': [], 'cache_peak_bytes': 0}
        with tempfile.TemporaryDirectory(prefix='pass-', dir=args.cache_root) as temporary:
            root = Path(temporary)
            if args.inventory:
                if not args.portfolio or not args.source_head:
                    parser.error('offline inventory requires --portfolio and --source-head')
                portfolio = args.portfolio.read_text()
                rows = json.loads(args.inventory.read_text())
                target, fix_rows = args.source_head, []
            else:
                owner = gh.request('repos/SylphxAI/owner/commits/main')['sha']
                portfolio = gh.text('SylphxAI/owner', 'company/portfolio.md', owner)
                target = gh.request(f'repos/{SOURCE}/commits/main')['sha']
                fix_rows = fixes(gh)
                rows = []
            roster = parse_active_portfolio(portfolio)
            report.update(source_head=target, active_roster=roster)
            blob_cache, binary = {}, None
            source_rows = {r['repo']: r for r in rows}
            for repo in roster:
                try:
                    if args.inventory:
                        if repo not in source_rows:
                            raise Refused('repository-not-in-fixture')
                        row = dict(source_rows[repo])
                        row['files'] = {p if p.startswith('.github/') else '.github/workflows/' + p: t
                                        for p, t in row['files'].items()}
                    else:
                        meta = gh.request(f'repos/{repo}')
                        if meta.get('archived'):
                            report['repositories'].append({'repo': repo, 'skip': 'archived'})
                            continue
                        head = gh.request(f'repos/{repo}/commits/{meta["default_branch"]}')['sha']
                        row = {'repo': repo, 'head': head, 'files': collect_files(gh, repo, head, blob_cache),
                               'prs': gh.pages(f'repos/{repo}/pulls?state=open')}
                    if row.get('archived'):
                        report['repositories'].append({'repo': repo, 'skip': 'archived'})
                        continue
                    row['pins'] = parse_pins(row['files'])
                    changes, unknown = ([], []) if gh is None else changes_since_pin(gh, row['pins'], target, fix_rows)
                    existing = [p.get('headRefName', p.get('head', {}).get('ref', '')) for p in row.get('prs', [])]
                    decision = plan_repo(repo, row['files'], target, fix_rows, changes, now, existing,
                                         regular=regular_due(now))
                    decision['unknown_source_history'] = unknown
                    report['alerts'].extend({'repo': repo, **u} for u in unknown)
                    report['alerts'].extend({'repo': repo, **{k: v for k, v in a.items() if k != 'age_hours'}} for a in decision.get('lag_alerts', []))
                    report['alerts'].extend({'repo': repo, **f} for f in decision.get('findings', []))
                    # Planning is read-only; native Renovate runs only for an
                    # admitted new immutable branch, not existing pin PRs.
                    key = decision.get('branch_key')
                    if key and decision.get('should_open', True) and (args.apply or args.engine_dry_run):
                        if gh.remaining() <= FLOOR + ENGINE_RESERVE:
                            raise Refused('native-engine-budget-reserve')
                        binary = binary or install_engine(root)
                        decision.update(run_engine(gh, row, key, target, root, args.state_dir, binary,
                                                   dry_run=not args.apply))
                        report['cache_peak_bytes'] = max(report['cache_peak_bytes'], row.get('cache_peak_bytes', 0))
                        if args.apply:
                            prs = gh.pages(f'repos/{repo}/pulls?state=open&head={repo.split("/")[0]}:renovate/shared-ci-{key}')
                            if len(prs) != 1:
                                raise Refused('opened-pr-not-reconciled')
                            arm = verify_and_arm(gh, row, prs[0], roster, target, args.state_dir)
                            decision['arm'] = arm
                            if arm['proof']:
                                report['alerts'].append(arm)
                    report['repositories'].append(decision)
                except (Refused, OSError, ValueError, subprocess.SubprocessError) as error:
                    # One repo cannot starve the rest. Unknown publication claims
                    # survive in durable state and must be reconciled, not resent.
                    cause = str(error) if isinstance(error, Refused) else type(error).__name__
                    report['alerts'].append({'repo': repo, 'reason': cause})
                    report['repositories'].append({'repo': repo, 'error': cause})
            report['cache_peak_bytes'] = max(report['cache_peak_bytes'], allocated(root))
        report['cache_after_bytes'] = allocated(args.cache_root)
        save(args.state_dir / 'report.json', report)
        if report['alerts']:
            save(args.state_dir / 'lag.trigger', {'report': str(args.state_dir / 'report.json'), 'alerts': report['alerts']})
        else:
            (args.state_dir / 'lag.trigger').unlink(missing_ok=True)
        print(json.dumps({'report': str(args.state_dir / 'report.json'), 'repositories': len(report['repositories']),
                          'alerts': len(report['alerts']), 'cache_peak_bytes': report['cache_peak_bytes'],
                          'cache_after_bytes': report['cache_after_bytes']}))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Refused, OSError, subprocess.SubprocessError) as error:
        print('shared-ci pass refused: ' + (str(error) if isinstance(error, Refused) else type(error).__name__), file=sys.stderr)
        sys.exit(1)
