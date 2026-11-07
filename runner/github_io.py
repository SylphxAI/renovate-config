"""Connected-user GitHub adapter; credentials never enter argv or artifacts."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess


class Refused(RuntimeError):
    pass


class GitHub:
    def __init__(self, expected_login: str = 'shtse8'):
        # gh owns credential custody. Capture, never log, its local delegation.
        env = dict(os.environ)
        for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'RENOVATE_TOKEN'):
            env.pop(key, None)
        # Only this local credential read uses the installed unwrapped CLI. The
        # desk wrapper's legacy owner routing can otherwise mint an App token
        # even for auth; all provider calls below still use its shared limiter.
        auth_cli = Path(os.environ.get('WORKSPACE_HOME', '/home/kyle')) / '.local/bin/gh.real'
        if not auth_cli.is_file():
            raise Refused('connected-auth-cli-unavailable')
        result = subprocess.run([str(auth_cli), 'auth', 'token', '--hostname', 'github.com'],
                                env=env, capture_output=True, text=True, timeout=20)
        if result.returncode or not result.stdout.strip():
            raise Refused('connected-credential-unavailable')
        self._token = result.stdout.strip()
        self.env = dict(env, GH_TOKEN=self._token, DESK_GH_PRIORITY='poll')
        self.calls = 0
        self.cache = {}
        # An explicit GH_TOKEN prevents desk gh from selecting an App. The gh
        # wrapper still meters and sheds every call against this user's budget.
        user, headers = self.request('user', headers=True)
        scopes = {s.strip() for s in headers.get('x-oauth-scopes', '').split(',')}
        if user.get('login') != expected_login or user.get('type') != 'User':
            raise Refused('connected-identity-mismatch')
        if not {'repo', 'workflow'} <= scopes:
            raise Refused('connected-scopes-missing-repo-or-workflow')
        self.login = expected_login

    def request(self, path: str, *, headers: bool = False, method: str = 'GET', body=None):
        if path.startswith(('http:', 'https:', '/')):
            raise Refused('non-relative-github-path')
        argv = ['gh', 'api', '--method', method, '-H', 'Accept: application/vnd.github+json', path]
        if headers:
            argv.append('--include')
        if body is not None:
            argv += ['--input', '-']
        result = subprocess.run(argv, env=self.env, input=json.dumps(body) if body is not None else None,
                                capture_output=True, text=True, timeout=60)
        self.calls += 1
        if result.returncode:
            # Provider errors may echo URLs/headers. Fixed failure labels only.
            raise Refused('github-request-refused')
        raw = result.stdout
        if headers:
            block, raw = raw.split('\n\n', 1)
            parsed = {k.lower(): v.strip() for line in block.splitlines() if ':' in line
                      for k, v in [line.split(':', 1)]}
            return json.loads(raw), parsed
        return json.loads(raw) if raw.strip() else None

    def pages(self, path: str):
        separator = '&' if '?' in path else '?'
        items = []
        for page in range(1, 101):
            rows = self.request(f'{path}{separator}per_page=100&page={page}')
            if not isinstance(rows, list):
                raise Refused('github-pagination-shape')
            items.extend(rows)
            if len(rows) < 100:
                return items
        raise Refused('github-inventory-incomplete')

    def compare(self, old: str, new: str):
        key = (old, new)
        if key not in self.cache:
            self.cache[key] = self.request(f'repos/SylphxAI/.github/compare/{old}...{new}')
        return self.cache[key]

    def forward(self, old: str, new: str):
        if old == new:
            return True
        value = self.compare(old, new)
        return value.get('status') == 'ahead' and value.get('merge_base_commit', {}).get('sha') == old

    def text(self, repo: str, path: str, ref: str):
        from urllib.parse import quote
        value = self.request(f'repos/{repo}/contents/{quote(path, safe="/")}?ref={quote(ref, safe="")}')
        if value.get('encoding') != 'base64':
            raise Refused('github-content-encoding')
        return base64.b64decode(value['content']).decode('utf-8')

    def remaining(self):
        limits = self.request('rate_limit')['resources']
        # Native Renovate has its own API client. Reserve its whole pass before
        # invoking it, above the desk poll floor, and stop if either resource is
        # low. Never switch identities or lower the shared floor.
        return min(limits['core']['remaining'], limits['graphql']['remaining'])

    def queue_state(self, repo: str, number: int):
        owner, name = repo.split('/')
        query = """query($owner:String!,$name:String!,$number:Int!){
          repository(owner:$owner,name:$name){pullRequest(number:$number){
            headRefOid state isInMergeQueue autoMergeRequest{enabledAt mergeMethod}
          }}}
        """
        value = self.request('graphql', method='POST', body={'query': query,
            'variables': {'owner': owner, 'name': name, 'number': number}})
        if value.get('errors'):
            raise Refused('arm-readback-unavailable')
        return value['data']['repository']['pullRequest']

    def arm(self, repo: str, number: int, head: str):
        result = subprocess.run(['gh', 'pr', 'merge', '-R', repo, str(number), '--auto', '--squash',
                                 '--match-head-commit', head], env=self.env, capture_output=True,
                                text=True, timeout=90)
        if result.returncode:
            raise Refused('normal-auto-merge-refused')


def save(path: Path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)
