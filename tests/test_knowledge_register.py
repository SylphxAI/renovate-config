"""The fleet readers must resolve a complete authoritative STO before discovery."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runner'))
import dependency_updates
import knowledge_register as knowledge
import shared_pins
from github_io import Refused

STO = """## Register 2: `STO`
### 2.1 Drive — Foundations
| # | Product | Canonical Repository | Notes |
|---|---|---|---|
| 1 | Engine | `example/current` (release source: `example/source`) | `example/not-a-repo-cell` |

### 2.2 Drive, Maintain & Retired
| # | Title | Mode | Live Repository | Remake Repository |
|---|---|---|---|---|
| 2 | Active | Maintain | `example/active` | `example/next` (Deferred) |
| 3 | Paused | Paused | `example/paused` | — |
"""


class KnowledgeRegisterTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'ANYAGENTS_API_URL': 'https://knowledge.example:8443/',
                                      'ANYAGENTS_TOKEN': 'fixture-read-bearer'}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        constructor = patch.object(knowledge.http.client, 'HTTPSConnection')
        self.connect = constructor.start()
        self.addCleanup(constructor.stop)
        self.conn = self.connect.return_value
        self.response = self.conn.getresponse.return_value
        self.response.status = 200
        self.response.length = 0
        self.document = {'namespace': 'org:governance', 'topic': 'group-state-registers',
                         'version': 7, 'truncated': False, 'deleted_at_ms': None, 'body': STO}
        self.response.read.side_effect = lambda _: json.dumps(self.document).encode('utf-8')

    def test_reads_only_the_canonical_sto_section_and_filters_active_rows(self):
        register = knowledge.read_sto_register()
        self.assertEqual(register.version, 7)
        self.assertEqual(register.repos, ('example/active', 'example/current', 'example/source'))
        self.connect.assert_called_once_with('knowledge.example', 8443, timeout=15)
        args, kwargs = self.conn.request.call_args
        self.assertEqual(args, ('POST', '/v1/knowledge'))
        self.assertEqual(json.loads(kwargs['body']), {
            'action': 'read', 'namespace': 'org:governance', 'topic': 'group-state-registers',
            'section': 'register-2-sto-product-engine-repository-store-id-domain-ownership-register',
            'max_bytes': 131072,
        })
        self.assertEqual(kwargs['headers'], {'Authorization': 'Bearer fixture-read-bearer',
                                            'Content-Type': 'application/json', 'Accept': 'application/json'})
        self.assertNotIn('ANYAGENTS_TOKEN', os.environ)
        self.conn.close.assert_called_once_with()

    def test_current_token_file_takes_precedence_and_does_not_fall_back_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / 'credential'
            for token in ('first-read-bearer', 'rotated-read-bearer'):
                token_path.write_text(token + '\n')
                os.environ.update(ANYAGENTS_TOKEN_FILE=str(token_path), ANYAGENTS_TOKEN='unused-fallback')
                knowledge.read_sto_register()
                self.assertEqual(self.conn.request.call_args.kwargs['headers']['Authorization'], 'Bearer ' + token)
                self.assertNotIn('ANYAGENTS_TOKEN_FILE', os.environ)
            self.conn.request.reset_mock()
            os.environ.update(ANYAGENTS_TOKEN_FILE=str(token_path.with_name('missing')),
                              ANYAGENTS_TOKEN='unused-fallback')
            with self.assertRaisesRegex(Refused, '^knowledge-token-file-unreadable$'):
                knowledge.read_sto_register()
            self.conn.request.assert_not_called()

    def test_rejects_unsafe_origin_or_missing_credentials_without_a_request(self):
        for url in ('', 'http://knowledge.example', 'https://user@knowledge.example',
                    'https://knowledge.example/elsewhere', 'https://knowledge.example:xyz'):
            with self.subTest(url=url), patch.dict(os.environ, {'ANYAGENTS_API_URL': url}):
                with self.assertRaisesRegex(Refused, '^knowledge-api-origin-invalid$'):
                    knowledge.read_sto_register()
        os.environ.pop('ANYAGENTS_TOKEN', None)
        with self.assertRaisesRegex(Refused, '^knowledge-token-unavailable$'):
            knowledge.read_sto_register()
        self.connect.assert_not_called()

    def test_non_success_does_not_read_body_or_follow_redirect(self):
        for status in (302, 401, 403, 404, 500):
            with self.subTest(status=status), patch.dict(os.environ, {'ANYAGENTS_TOKEN': 'fixture-read-bearer'}):
                self.response.status = status
                with self.assertRaisesRegex(Refused, f'^knowledge-http-{status}$'):
                    knowledge.read_sto_register()
        self.assertEqual(self.conn.request.call_count, 5)
        self.response.read.assert_not_called()

    def test_transport_or_content_failure_is_safe_and_bounded(self):
        with patch.dict(os.environ, {'ANYAGENTS_TOKEN': 'fixture-read-bearer'}):
            self.conn.getresponse.side_effect = TimeoutError('fixture-read-bearer')
            with self.assertRaisesRegex(Refused, '^knowledge-request-failed$'):
                knowledge.read_sto_register()
        self.conn.getresponse.side_effect = None
        self.response.read.side_effect = None
        for raw, reason in ((b'{', 'invalid'), (b'\xff', 'invalid'),
                            (b'x' * (knowledge.MAX_RESPONSE_BYTES + 1), 'incomplete')):
            with self.subTest(reason=reason), patch.dict(os.environ, {'ANYAGENTS_TOKEN': 'fixture-read-bearer'}):
                self.response.read.return_value = raw
                with self.assertRaisesRegex(Refused, f'^knowledge-response-{reason}$'):
                    knowledge.read_sto_register()
                self.response.read.assert_called_with(knowledge.MAX_RESPONSE_BYTES + 1)

    def test_wrong_or_incomplete_document_refused(self):
        good = self.document.copy()
        for change in ({'namespace': 'other'}, {'topic': 'other'}, {'version': True},
                       {'version': 0}, {'truncated': True}, {'truncated': None},
                       {'deleted_at_ms': 100}, {'body': None}):
            with self.subTest(change=change), patch.dict(os.environ, {'ANYAGENTS_TOKEN': 'fixture-read-bearer'}):
                self.document = {**good, **change}
                with self.assertRaisesRegex(Refused, '^knowledge-document-invalid$'):
                    knowledge.read_sto_register()

    def test_refuses_malformed_sto_after_preceding_valid_rows(self):
        for body in ('', STO.replace('Register 2: `STO`', 'Drive', 1),
                     STO.replace('| — |', '| extra | — |', 1),
                     STO.replace('| 3 |', '| invalid |'), STO + '## Register 2: STO\n'):
            with self.subTest(body=body[-50:]), patch.dict(os.environ, {'ANYAGENTS_TOKEN': 'fixture-read-bearer'}):
                self.document['body'] = body
                with self.assertRaisesRegex(Refused, '^knowledge-sto-invalid$'):
                    knowledge.read_sto_register()

    def test_both_live_entry_points_abort_before_any_github_activity(self):
        for runner in (dependency_updates, shared_pins):
            self.document['truncated'] = True
            with (self.subTest(runner=runner.__name__), tempfile.TemporaryDirectory() as tmp,
                  patch.dict(os.environ, {'ANYAGENTS_TOKEN': 'fixture-read-bearer'}),
                  patch.object(runner, 'GitHub') as github, patch.object(runner, 'install_engine') as install):
                root = Path(tmp)
                with self.assertRaisesRegex(Refused, '^knowledge-document-invalid$'):
                    runner.main(['--apply', '--state-dir', str(root / 'state'), '--cache-root', str(root / 'cache')])
                github.assert_not_called()
                install.assert_not_called()
                self.assertFalse((root / 'state' / 'report.json').exists())

    def test_both_live_entry_points_record_revision_and_discover_the_same_roster(self):
        for runner in (dependency_updates, shared_pins):
            github = Mock()
            requests = []

            def request(path):
                if path == f'repos/{shared_pins.SOURCE}/commits/main':
                    return {'sha': 'f' * 40}
                if path == f'repos/{shared_pins.SOURCE}/git/trees/{"f" * 40}?recursive=1':
                    return {'tree': [], 'truncated': False}
                if path.startswith('repos/example/'):
                    requests.append(path.removeprefix('repos/'))
                    return {'archived': True}
                raise AssertionError(path)

            github.request.side_effect = request
            github.pages.return_value = []
            with (self.subTest(runner=runner.__name__), tempfile.TemporaryDirectory() as tmp,
                  patch.dict(os.environ, {'ANYAGENTS_TOKEN': 'fixture-read-bearer'}),
                  patch.object(runner, 'GitHub', return_value=github), patch.object(shared_pins, 'fixes', return_value=[]),
                  patch.object(runner, 'install_engine') as install):
                root = Path(tmp)
                self.conn.request.reset_mock()
                self.assertEqual(runner.main(['--apply', '--state-dir', str(root / 'state'),
                                              '--cache-root', str(root / 'cache')]), 0)
                self.conn.request.assert_called_once()
                self.assertEqual(requests, ['example/active', 'example/current', 'example/source'])
                self.assertEqual(json.loads((root / 'state' / 'report.json').read_text())['sto_version'], 7)
                github.text.assert_not_called()
                install.assert_not_called()


if __name__ == '__main__':
    unittest.main()
