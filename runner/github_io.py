"""Connected-user GitHub adapter; credentials never enter argv or artifacts."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import subprocess
import time

DEFAULT_TOKEN_BROKER = '/scratch/coordinator/bin/desk-gh-token'
_APP_TOKEN_TTL_SECONDS = 600
_OWNER_PATH = re.compile(r'^(?:repos|orgs)/([A-Za-z0-9][A-Za-z0-9-]*)/')


class Refused(RuntimeError):
    pass


class GitHub:
    def __init__(self, expected_login: str = 'shtse8', *, verify_user: bool = True):
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
        self._base_env = env
        # Keep the connected user token without poll priority so startup checks
        # and PR/merge writes do not shed at the 3000-remaining poll floor.
        self.env = dict(env, GH_TOKEN=self._token)
        self._app_tokens = {}
        self._token_broker = os.environ.get('DESK_GH_TOKEN_BIN', DEFAULT_TOKEN_BROKER)
        self.calls = 0
        self.cache = {}
        self._expected_login = expected_login
        self._verified_user = False
        self.login = expected_login
        if verify_user:
            self.verify_connected_user()

    def verify_connected_user(self):
        """Verify the connected user login and scopes before write/engine calls."""
        if getattr(self, '_verified_user', False):
            return
        expected = getattr(self, '_expected_login', getattr(self, 'login', 'shtse8'))
        # An explicit GH_TOKEN verifies the connected user and its scopes
        # without ever substituting an App token for PR authorship.
        user, headers = self.request('user', headers=True)
        scopes = {s.strip() for s in headers.get('x-oauth-scopes', '').split(',')}
        if user.get('login') != expected or user.get('type') != 'User':
            raise Refused('connected-identity-mismatch')
        if not {'repo', 'workflow'} <= scopes:
            raise Refused('connected-scopes-missing-repo-or-workflow')
        self._verified_user = True
        self.login = expected

    def _app_env(self, owner: str):
        if os.environ.get('DESK_GH_APP_READS', '1') == '0':
            return None
        broker = getattr(self, '_token_broker', '') or ''
        if not broker or not os.path.isfile(broker) or not os.access(broker, os.X_OK):
            return None
        tokens = getattr(self, '_app_tokens', None)
        if tokens is None:
            tokens = {}
            self._app_tokens = tokens
        key = owner.lower()
        now = time.monotonic()
        cached = tokens.get(key)
        if cached and now - cached[1] < _APP_TOKEN_TTL_SECONDS:
            return dict(getattr(self, '_base_env', self.env), GH_TOKEN=cached[0])
        base_env = getattr(self, '_base_env', None)
        if base_env is None:
            base_env = {k: v for k, v in self.env.items() if k not in ('GH_TOKEN', 'GITHUB_TOKEN', 'RENOVATE_TOKEN')}
        try:
            result = subprocess.run([broker, 'token', owner, '--read'], env=base_env,
                                    capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return None
        token = result.stdout.strip() if result.returncode == 0 else ''
        if not token:
            return None
        tokens[key] = (token, now)
        return dict(base_env, GH_TOKEN=token)

    def _run_api(self, argv, *, payload=None, read_owner=None):
        call_env = self._app_env(read_owner) if read_owner else None
        if call_env is None:
            call_env = self.env
        result = subprocess.run(argv, env=call_env, input=payload,
                                capture_output=True, text=True, timeout=60)
        self.calls += 1
        if result.returncode and call_env is not self.env and read_owner:
            getattr(self, '_app_tokens', {}).pop(read_owner.lower(), None)
            result = subprocess.run(argv, env=self.env, input=payload,
                                    capture_output=True, text=True, timeout=60)
            self.calls += 1
        if result.returncode:
            # Provider errors may echo URLs/headers. Fixed failure labels only.
            raise Refused('github-request-refused')
        return result.stdout

    def request(self, path: str, *, headers: bool = False, method: str = 'GET', body=None, app_read_owner: str = None):
        if path.startswith(('http:', 'https:', '/')):
            raise Refused('non-relative-github-path')
        argv = ['gh', 'api', '--method', method, '-H', 'Accept: application/vnd.github+json', path]
        if headers:
            argv.append('--include')
        if body is not None:
            argv += ['--input', '-']
        payload = json.dumps(body) if body is not None else None
        read_owner = app_read_owner
        if read_owner is None and method == 'GET':
            match = _OWNER_PATH.match(path)
            if match:
                read_owner = match.group(1)
        raw = self._run_api(argv, payload=payload, read_owner=read_owner)
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
            'variables': {'owner': owner, 'name': name, 'number': number}}, app_read_owner=owner)
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
