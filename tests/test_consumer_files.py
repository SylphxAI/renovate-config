"""Workflow discovery reads only the immutable relevant consumer subtree."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runner'))
from github_io import Refused
from shared_pins import collect_files

REPO, HEAD, GITHUB = 'SylphxAI/fixture', 'a' * 40, 'b' * 40
ROOT_URL = f'repos/{REPO}/git/trees/{HEAD}'
SUBTREE_URL = f'repos/{REPO}/git/trees/{GITHUB}?recursive=1'


class GitHub:
    def __init__(self):
        self.requests, self.reads = [], []
        self.responses = {
            # A large unrelated Unity asset tree can truncate the full tree.
            ROOT_URL + '?recursive=1': {'truncated': True, 'tree': []},
            ROOT_URL: {'truncated': False, 'tree': [
                {'path': '.github', 'type': 'tree', 'sha': GITHUB},
                {'path': 'Assets', 'type': 'tree', 'sha': 'c' * 40}]},
            SUBTREE_URL: {'truncated': False, 'tree': [
                {'path': 'workflows/ci.yml', 'type': 'blob', 'sha': '1' * 40, 'size': 42},
                {'path': 'actions/local/action.yaml', 'type': 'blob', 'sha': '2' * 40, 'size': 42},
                {'path': 'README.md', 'type': 'blob', 'sha': '3' * 40},
                {'path': 'workflows', 'type': 'tree', 'sha': '4' * 40}]} }

    def request(self, path):
        self.requests.append(path)
        return self.responses[path]

    def text(self, repo, path, ref):
        self.reads.append((repo, path, ref))
        return 'contents:' + path


class ConsumerFiles(unittest.TestCase):
    def test_complete_github_subtree_passes_despite_truncated_whole_repository(self):
        gh = GitHub()
        files = collect_files(gh, REPO, HEAD, {})
        self.assertEqual(files, {'.github/workflows/ci.yml': 'contents:.github/workflows/ci.yml',
                                '.github/actions/local/action.yaml': 'contents:.github/actions/local/action.yaml'})
        self.assertEqual(gh.requests, [ROOT_URL, SUBTREE_URL])
        self.assertEqual(gh.reads, [(REPO, '.github/workflows/ci.yml', HEAD),
                                    (REPO, '.github/actions/local/action.yaml', HEAD)])

    def test_truncated_relevant_subtree_refuses_without_reading_partial_files(self):
        gh = GitHub()
        gh.responses[SUBTREE_URL]['truncated'] = True
        with self.assertRaisesRegex(Refused, '^consumer-tree-truncated$'):
            collect_files(gh, REPO, HEAD, {})
        self.assertEqual(gh.reads, [])

    def test_truncated_root_is_unknown_not_absent(self):
        gh = GitHub()
        gh.responses[ROOT_URL]['truncated'] = True
        with self.assertRaisesRegex(Refused, '^consumer-tree-truncated$'):
            collect_files(gh, REPO, HEAD, {})
        self.assertEqual(gh.reads, [])

    def test_complete_root_without_github_is_known_empty(self):
        gh = GitHub()
        gh.responses[ROOT_URL]['tree'] = gh.responses[ROOT_URL]['tree'][1:]
        self.assertEqual(collect_files(gh, REPO, HEAD, {}), {})
        self.assertEqual(gh.requests, [ROOT_URL])
        self.assertEqual(gh.reads, [])

    def test_github_blob_does_not_masquerade_as_absent_subtree(self):
        gh = GitHub()
        gh.responses[ROOT_URL]['tree'][0]['type'] = 'blob'
        with self.assertRaisesRegex(Refused, '^consumer-github-not-tree$'):
            collect_files(gh, REPO, HEAD, {})
        self.assertEqual(gh.requests, [ROOT_URL])
        self.assertEqual(gh.reads, [])

    def test_relevant_blob_limit_and_content_cache_are_preserved(self):
        gh = GitHub()
        cache = {'1' * 40: 'cached ci'}
        self.assertEqual(collect_files(gh, REPO, HEAD, cache)['.github/workflows/ci.yml'], 'cached ci')
        self.assertEqual(gh.reads, [(REPO, '.github/actions/local/action.yaml', HEAD)])
        gh = GitHub()
        gh.responses[SUBTREE_URL]['tree'][0]['size'] = 2_000_001
        with self.assertRaisesRegex(Refused, '^workflow-too-large$'):
            collect_files(gh, REPO, HEAD, {})
        self.assertEqual(gh.reads, [])


if __name__ == '__main__':
    unittest.main()
