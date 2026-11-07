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
from source_dependencies import dependency_paths, touches

HERE = Path(__file__).resolve().parent
SOURCE = 'SylphxAI/.github'
FLOOR = 3000
ENGINE_RESERVE = 400


def utcnow():
    return datetime.now(timezone.utc)


def regular_due(now):
    return now.weekday() < 5 and (now.hour, now.minute) >= (4, 17)


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


def engine_config(repo, pins, branch_key, root, *, ancestry_failures=()):
    config = json.loads((HERE / 'config.json').read_text())
    if ancestry_failures:
        config['prBodyTemplate'] += ('\n\nAutomatic merge is withheld: source main is not a proven descendant of these existing pins: '
                                     + ', '.join('`' + sha + '`' for sha in ancestry_failures)
                                     + '. An ancestry review is required.')
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
    config = engine_config(repo, row['pins'], key, folder, ancestry_failures=row.get('ancestry_failures', []))
    config_path = folder / 'config.json'
    manifest_path = folder / 'manifest.json'
    save(manifest_path, dict(repo=repo, base_head=row['head'], target=target, pins=[p for p in row['pins'] if p.get('sha')], files=row['files']))
    claim = state / (hashlib.sha256((repo + ':' + key).encode()).hexdigest() + '.push-claim')
    config['customEnvVariables'] = {
        'GIT_LFS_SKIP_SMUDGE': '1', 'SHARED_PINS_BRANCH': branch,
        'SHARED_PINS_MANIFEST': str(manifest_path), 'SHARED_PINS_PUSH_CLAIM': str(claim),
        'SHARED_PINS_INSTALL_HOOK': '1', 'SHARED_PINS_READ_ONLY': '1' if dry_run else '0'}
    save(config_path, config)
    if claim.exists():
        raise Refused('prior-push-attempt-needs-reconciliation')
    clean_env = {k: v for k, v in gh.env.items()
                 if not k.startswith(('RENOVATE_', 'SHARED_PINS_', 'GIT_CONFIG_'))}
    env = dict(clean_env, RENOVATE_TOKEN=gh._token, RENOVATE_USERNAME=gh.login,
               RENOVATE_CONFIG_FILE=str(config_path), LOG_LEVEL='info', LOG_FORMAT='json',
               GIT_LFS_SKIP_SMUDGE='1', SHARED_PINS_BRANCH=branch,
               SHARED_PINS_MANIFEST=str(manifest_path), SHARED_PINS_PUSH_CLAIM=str(claim),
               SHARED_PINS_INSTALL_HOOK='1', SHARED_PINS_READ_ONLY='1' if dry_run else '0')
    env['PATH'] = str(bindir) + ':' + str(binary[0].parent) + ':' + os.environ['PATH']
    # Renovate's SSH remotes carry no credential. Its supported host-rule Git
    # adapter supplies authentication in child environment variables only. The
    # transport canonicalizes credential-free GitHub SSH arguments to HTTPS.
    env['RENOVATE_HOST_RULES'] = json.dumps([{'hostType': 'github', 'matchHost': 'github.com', 'token': gh._token}])
    # Initial ls-remote is unauthenticated in the native Git layer even with a
    # host rule. Apply the same supported Git environment-only rewrite to every
    # child operation; the secret is never serialized in config.json. The
    # transport accepts only this canonical rule or the native same-host trio.
    env['RENOVATE_CUSTOM_ENV_VARIABLES'] = json.dumps({**config['customEnvVariables'],
        'GIT_CONFIG_COUNT': '1',
        'GIT_CONFIG_KEY_0': f'url.https://x-access-token:{gh._token}@github.com/.insteadOf',
        'GIT_CONFIG_VALUE_0': 'https://github.com/'})
    if dry_run:
        env['RENOVATE_DRY_RUN'] = 'full'
    try:
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
        if result.returncode or len(terminal) != 1 or terminal[0].get('result') != 'done':
            # Finite provider result codes only; never persist arbitrary native
            # error objects/configuration even on a nonzero process exit.
            code = terminal[0].get('result', 'missing') if len(terminal) == 1 else 'missing'
            code = code if isinstance(code, str) and re.fullmatch('[a-z-]{1,64}', code) else 'unknown'
            raise Refused(f'native-engine-failed:{result.returncode}:{code}')
        # Never retain raw native logs: configuration can contain authentication.
        return {'engine_exit': result.returncode, 'engine_result': 'done',
                'engine_cloned': terminal[0].get('cloned') is True, 'branch': branch}
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
    """Positive consumed-path proof plus oldest outstanding relevant change.

    Aggregate comparison proves regular relevance independently of the history
    window. A capped history/file response remains unknown for lag purposes.
    """
    changes, unknown = [], []
    shas = sorted({p['sha'] for p in pins if re.fullmatch('[a-fA-F0-9]{40}', (p.get('sha') or '')) and p['sha'] != head})
    for old in shas:
        comparison = gh.compare(old, head)
        if not gh.forward(old, head):
            unknown.append({'sha': old, 'reason': 'pin-is-not-source-main-ancestor'})
            continue
        selected = [p for p in pins if p.get('sha') == old]
        aggregate = [p['filename'] for p in comparison.get('files', [])]
        if len(aggregate) >= 300:
            unknown.append({'sha': old, 'reason': 'comparison-files-incomplete'})
        # A capped response still proves every returned path changed. Omitted
        # paths cannot cancel positive evidence or establish a healthy pin.
        changes.append({'sha': head, 'merged_at': utcnow().isoformat(), 'files': aggregate,
                        'behind_pins': [old], 'comparison_pin': old, 'lag_eligible': False})
        for fix in fix_rows:
            if old != fix['sha'] and gh.forward(old, fix['sha']):
                fix.setdefault('behind_pins', []).append(old)
            elif gh.forward(fix['sha'], old):
                fix.setdefault('included_by_pins', []).append(old)
        commits = comparison.get('commits', [])
        if comparison.get('total_commits', len(commits)) > len(commits):
            unknown.append({'sha': old, 'reason': 'source-history-incomplete'})
            # Returned commits still prove positive relevant changes. Missing
            # later commits cannot erase that evidence or imply a healthy pin.
        pending = list(selected)
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
            affected = [p for p in pending if touches(p, paths)]
            if affected:
                changes.append({'sha': commit['sha'], 'merged_at': commit['commit']['committer']['date'],
                                'files': paths, 'behind_pins': [old], 'comparison_pin': old})
                pending = [p for p in pending if p not in affected]
    if any(p.get('sha') == head for p in pins):
        for fix in fix_rows:
            if gh.forward(fix['sha'], head):
                fix.setdefault('included_by_pins', []).append(head)
    return changes, unknown


def source_reader(gh, target):
    """Resolve declared consumption at both immutable ends of each pin roll.

    Target-only closure loses a helper removed or replaced after a marked fix.
    Cache complete trees/closures by revision and successful text by blob SHA;
    an unreadable historical input remains unknown, never an empty closure.
    """
    trees, texts, closures = {}, {}, {}

    def tree(ref):
        if ref not in trees:
            value = gh.request(f'repos/{SOURCE}/git/trees/{ref}?recursive=1')
            if value.get('truncated'):
                raise Refused('source-tree-truncated')
            trees[ref] = {e['path']: e['sha'] for e in value['tree'] if e['type'] == 'blob'}
        return trees[ref]

    def closure(ref, roots):
        key = (ref, roots)
        if key not in closures:
            paths = tree(ref)
            def read(path):
                sha = paths[path]
                if sha not in texts:
                    texts[sha] = gh.text(SOURCE, path, ref)
                return texts[sha]
            closures[key] = dependency_paths(roots, paths, read)
        return closures[key]

    tree(target)
    def enrich(pins):
        for pin in pins:
            roots = tuple(pin.get('roots', []))
            refs = [target]
            old = pin.get('sha') or ''
            if re.fullmatch('[a-fA-F0-9]{40}', old) and old != target and any(roots):
                refs.append(old)
            declared = set()
            for ref in refs:
                try:
                    declared.update(closure(ref, roots))
                except (Refused, OSError, ValueError, subprocess.SubprocessError) as error:
                    cause = str(error) if isinstance(error, Refused) else type(error).__name__
                    raise Refused(f'source-dependencies-unreadable:{ref}:{cause}') from error
            pin['dependency_paths'] = sorted(declared)
    return enrich


def admit_regular(decision, open_rolls, cap=15):
    """Expedited fixes bypass the capacity cap; regular slots never do."""
    if decision.get('should_open') and not decision.get('qualifying_fixes') and open_rolls >= cap:
        decision.update(should_open=False, capacity_deferred=True)
    return decision


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
        observed = gh.queue_state(repo, pr['number'])
        admitted = (observed.get('headRefOid') == head and
                    (observed.get('state') == 'MERGED' or observed.get('isInMergeQueue') is True
                     or observed.get('autoMergeRequest') is not None))
        receipt.update(armed=admitted, auto_merge=observed.get('autoMergeRequest'),
                       is_in_merge_queue=observed.get('isInMergeQueue'), state=observed.get('state'))
        if not admitted:
            receipt['proof'] = ['arm-not-observed']

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
    if args.engine_dry_run and args.inventory:
        parser.error('native engine requires live discovery, not offline fixtures')
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
            enrich = None if gh is None else source_reader(gh, target)
            blob_cache, binary = {}, None
            source_rows = {r['repo']: r for r in rows}
            discovered = []
            open_rolls, inventory_known = 0, True
            for repo in roster:
                inventory_read = False
                try:
                    if args.inventory:
                        if repo not in source_rows:
                            raise Refused('repository-not-in-fixture')
                        row = dict(source_rows[repo])
                    else:
                        meta = gh.request(f'repos/{repo}')
                        if meta.get('archived'):
                            report['repositories'].append({'repo': repo, 'skip': 'archived'})
                            continue
                        row = {'repo': repo, 'prs': gh.pages(f'repos/{repo}/pulls?state=open')}
                    if row.get('archived'):
                        report['repositories'].append({'repo': repo, 'skip': 'archived'})
                        continue
                    # Fleet capacity is an independent observation. Preserve it
                    # even if later consumer/source discovery refuses this row.
                    prs = row.get('prs')
                    if not isinstance(prs, list) or any(not isinstance(pr, dict) for pr in prs):
                        raise Refused('open-roll-inventory-unreadable')
                    open_rolls += sum(1 for pr in prs if pr.get('headRefName', pr.get('head', {}).get('ref', '')).startswith('renovate/shared-ci-'))
                    inventory_read = True
                    if args.inventory:
                        if 'error' in row or not isinstance(row.get('files'), dict):
                            raise Refused('repository-inventory-unreadable')
                        row['files'] = {p if p.startswith('.github/') else '.github/workflows/' + p: t
                                        for p, t in row['files'].items()}
                    else:
                        head = gh.request(f'repos/{repo}/commits/{meta["default_branch"]}')['sha']
                        row.update(head=head, files=collect_files(gh, repo, head, blob_cache),
                                   branches=gh.request(f'repos/{repo}/git/matching-refs/heads/renovate/shared-ci-'))
                    row['pins'] = parse_pins(row['files'])
                    if enrich:
                        enrich(row['pins'])
                    else:
                        for pin in row['pins']:
                            pin['dependency_paths'] = row.get('source_dependencies', {}).get('|'.join(pin['roots']), [])
                    discovered.append(row)
                except (Refused, OSError, ValueError, subprocess.SubprocessError) as error:
                    cause = str(error) if isinstance(error, Refused) else type(error).__name__
                    if not inventory_read:
                        inventory_known = False
                        report['alerts'].append({'repo': repo, 'reason': 'open-roll-inventory-unknown'})
                    report['alerts'].append({'repo': repo, 'reason': cause})
                    report['repositories'].append({'repo': repo, 'error': cause})
            report.update(open_roll_prs=open_rolls, open_roll_inventory_known=inventory_known, regular_open_cap=15)
            for row in discovered:
                repo = row['repo']
                try:
                    changes, unknown = (row.get('changes', []), row.get('unknown_source_history', [])) if gh is None else changes_since_pin(gh, row['pins'], target, fix_rows)
                    existing = [p.get('headRefName', p.get('head', {}).get('ref', '')) for p in row.get('prs', [])]
                    existing += [b['ref'] for b in row.get('branches', [])]
                    decision = plan_repo(repo, row['files'], target, fix_rows, changes, now, existing,
                                         regular=regular_due(now), pins=row['pins'])
                    admit_regular(decision, open_rolls)
                    if not inventory_known:
                        decision.update(should_open=False, admission='open-roll-inventory-unknown')
                    if decision.get('should_open'):
                        open_rolls += 1
                    decision['unknown_source_history'] = unknown
                    row['ancestry_failures'] = sorted({u['sha'] for u in unknown if u['reason'] == 'pin-is-not-source-main-ancestor' or u['reason'] == 'not-proven-source-ancestor'})
                    decision['auto_arm_withheld'] = row['ancestry_failures']
                    report['alerts'].extend({'repo': repo, **u} for u in unknown)
                    report['alerts'].extend({'repo': repo, **{k: v for k, v in a.items() if k != 'age_hours'}} for a in decision.get('lag_alerts', []))
                    report['alerts'].extend({'repo': repo, **f} for f in decision.get('findings', []))
                    # Planning is read-only; native Renovate runs only for an
                    # admitted new immutable branch, not existing pin PRs.
                    key = decision.get('branch_key')
                    if key and decision.get('should_open', True) and (args.apply or args.engine_dry_run):
                        if gh.remaining() <= FLOOR + ENGINE_RESERVE:
                            raise Refused('native-engine-budget-reserve')
                        prior = gh.pages(f'repos/{repo}/pulls?state=all&head={repo.split("/")[0]}:renovate/shared-ci-{key}')
                        if prior:
                            decision.update(should_open=False, prior_pr=True)
                            report['repositories'].append(decision)
                            continue
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
