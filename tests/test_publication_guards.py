"""Targeted stdlib tests for the shared-pin publication boundary.

Production runner files are imported from ../runner. Isolated reviewers can
set SHARED_PIN_TEST_RUNNER to a separate source worktree's runner directory.
Run with ``python3 -m unittest discover -s tests -p 'test_publication_guards.py'``
or directly with ``python3 tests/test_publication_guards.py``.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


# Prefer colocated production files when copied into the runner repository.
# Isolated reviewers can select a separate source worktree explicitly.
RUNNER = Path(os.environ.get("SHARED_PIN_TEST_RUNNER", str(Path(__file__).resolve().parents[1] / "runner")))
if str(RUNNER) not in sys.path:
    # The runner is intentionally a script directory rather than a package.
    sys.path.insert(0, str(RUNNER))

import git_transport  # noqa: E402
import github_io  # noqa: E402
import pin_proof  # noqa: E402


OLD = "a" * 40
NEW = "b" * 40
SOURCE_MAIN = "c" * 40
PR_HEAD = "d" * 40
PATH = ".github/workflows/ci.yml"
BRANCH = "renovate/shared-ci-week-2026-45"


def workflow_text(sha: str = OLD, *, comment: bool = True, unrelated: str = "ubuntu-latest") -> str:
    suffix = " # main" if comment else ""
    return (
        "name: CI\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: " + unrelated + "\n"
        "    steps:\n"
        "      - uses: SylphxAI/.github/.github/actions/review@" + sha + suffix + "\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        "          repository: SylphxAI/.github\n"
        "          ref: " + sha + suffix + "\n"
    )


def pin_for(text: str, occurrence: int, *, sha: str = OLD) -> dict:
    """Build the source-defined pin span used by prove_files."""
    start = -1
    for _ in range(occurrence + 1):
        start = text.index(sha, start + 1)
    return {"path": PATH, "start": start, "end": start + len(sha), "sha": sha}


class TestPinProof(unittest.TestCase):
    def test_sha_only_uses_and_checkout_ref_preserve_main_comments(self):
        before = workflow_text()
        after = before.replace(OLD, NEW)
        pins = [pin_for(before, 0), pin_for(before, 1)]

        self.assertEqual(pin_proof.prove_files({PATH: before}, {PATH: after}, pins, NEW), [])

    def test_missing_main_comment_is_rejected(self):
        before = workflow_text(comment=False)
        after = before.replace(OLD, NEW)
        pins = [pin_for(before, 0), pin_for(before, 1)]

        failures = pin_proof.prove_files({PATH: before}, {PATH: after}, pins, NEW)
        self.assertIn(f"{PATH}:missing-main-comment", failures)

    def test_unrelated_content_edit_is_not_sha_only(self):
        before = workflow_text()
        after = workflow_text(unrelated="ubuntu-24.04").replace(OLD, NEW)
        pins = [pin_for(before, 0), pin_for(before, 1)]

        failures = pin_proof.prove_files({PATH: before}, {PATH: after}, pins, NEW)
        self.assertIn(f"{PATH}:not-sha-only", failures)
        self.assertIn(f"{PATH}:parsed-yaml-diff", failures)

    def test_unknown_sha_or_metadata_change_is_rejected(self):
        before = workflow_text()
        unknown = "e" * 40
        after = before.replace(OLD, unknown)
        pins = [pin_for(before, 0), pin_for(before, 1)]

        failures = pin_proof.prove_files({PATH: before}, {PATH: after}, pins, NEW)
        self.assertIn(f"{PATH}:not-sha-only", failures)

    def test_malformed_yaml_is_rejected(self):
        before = workflow_text()
        after = before.replace(OLD, NEW) + "jobs: [\n"
        pins = [pin_for(before, 0), pin_for(before, 1)]

        failures = pin_proof.prove_files({PATH: before}, {PATH: after}, pins, NEW)
        self.assertIn(f"{PATH}:invalid-yaml", failures)

    def test_file_set_change_is_rejected(self):
        before = workflow_text()
        after = before.replace(OLD, NEW)
        pins = [pin_for(before, 0), pin_for(before, 1)]

        failures = pin_proof.prove_files(
            {PATH: before}, {PATH: after, ".github/workflows/other.yml": "jobs: {}\n"}, pins, NEW
        )
        self.assertEqual(failures, ["file-set-changed"])


class _VerifyFakeGitHub:
    def __init__(self, *, target_on_main=True, old_descends=True, queue_state=None):
        self.target_on_main = target_on_main
        self.old_descends = old_descends
        self.arm_calls = []
        self.observed_queue_state = queue_state if queue_state is not None else {
            "headRefOid": PR_HEAD, "state": "OPEN", "isInMergeQueue": False,
            "autoMergeRequest": {"enabledAt": "2026-11-07T06:00:00Z", "mergeMethod": "SQUASH"},
        }

    def pages(self, path):
        self.assert_path(path, "/files")
        return [{"filename": PATH, "status": "modified"}]

    def text(self, repo, path, ref):
        self.assert_path(path, PATH)
        self.assert_path(ref, PR_HEAD)
        return workflow_text(NEW)

    def request(self, path, **kwargs):
        if path.endswith("/commits/main"):
            return {"sha": SOURCE_MAIN}
        if "/pulls/17" in path:
            return {"head": {"sha": PR_HEAD}, "state": "open"}
        raise AssertionError(f"unexpected request: {path}")

    def forward(self, old, new):
        if (old, new) == (NEW, SOURCE_MAIN):
            return self.target_on_main
        if (old, new) == (OLD, NEW):
            return self.old_descends
        return old == new

    def arm(self, repo, number, head):
        self.arm_calls.append((repo, number, head))

    def queue_state(self, repo, number):
        return self.observed_queue_state

    @staticmethod
    def assert_path(actual, expected):
        # Fake method keeps assertions in the test while matching the adapter's
        # normal call shape.
        if expected == "/files":
            if not actual.endswith("/files"):
                raise AssertionError(actual)
        elif actual != expected:
            raise AssertionError((actual, expected))


class TestVerifyAndArmAncestry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # pin_plan can be absent during the parent handoff.  Keep this import
        # lazy so proof/transport tests remain runnable in that interval.
        try:
            cls.shared_pins = importlib.import_module("shared_pins")
        except ModuleNotFoundError as error:
            if error.name == "pin_plan":
                cls.shared_pins = None
            else:
                raise

    def setUp(self):
        if self.shared_pins is None:
            self.skipTest("pin_plan dependency not present yet")

    def _row_and_pr(self):
        before = workflow_text()
        pins = [pin_for(before, 0), pin_for(before, 1)]
        row = {"repo": "SylphxAI/example", "files": {PATH: before}, "pins": pins}
        pr = {"number": 17, "html_url": "https://github.com/SylphxAI/example/pull/17",
              "head": {"sha": PR_HEAD}}
        return row, pr

    def test_forward_sha_proof_arms_once_at_exact_opened_head(self):
        row, pr = self._row_and_pr()
        gh = _VerifyFakeGitHub()
        with tempfile.TemporaryDirectory() as directory:
            receipt = self.shared_pins.verify_and_arm(
                gh, row, pr, [row["repo"]], NEW, Path(directory)
            )
            repeated = self.shared_pins.verify_and_arm(
                gh, row, pr, [row["repo"]], NEW, Path(directory)
            )

        self.assertEqual(receipt["proof"], [])
        self.assertTrue(receipt["armed"])
        self.assertEqual(gh.arm_calls, [(row["repo"], pr["number"], PR_HEAD)])
        self.assertEqual(repeated["proof"], ["prior-arm-attempt-needs-reconciliation"])

    def test_successful_arm_requires_positive_exact_head_readback(self):
        row, pr = self._row_and_pr()
        cases = [
            ({"headRefOid": PR_HEAD, "state": "OPEN", "isInMergeQueue": True,
              "autoMergeRequest": None}, True),
            ({"headRefOid": PR_HEAD, "state": "MERGED", "isInMergeQueue": False,
              "autoMergeRequest": None}, True),
            ({"headRefOid": PR_HEAD, "state": "OPEN", "isInMergeQueue": False,
              "autoMergeRequest": None}, False),
            ({"headRefOid": NEW, "state": "OPEN", "isInMergeQueue": True,
              "autoMergeRequest": {"mergeMethod": "SQUASH"}}, False),
        ]
        for observed, admitted in cases:
            with self.subTest(observed=observed):
                gh = _VerifyFakeGitHub(queue_state=observed)
                # Every scenario gets a distinct durable state directory so a
                # prior claim cannot satisfy or short-circuit another case.
                with tempfile.TemporaryDirectory() as directory:
                    state = Path(directory)
                    receipt = self.shared_pins.verify_and_arm(
                        gh, row, pr, [row["repo"]], NEW, state
                    )
                    saved = json.loads(next(state.glob("arm-*.json")).read_text())
                self.assertIs(receipt["armed"], admitted)
                self.assertEqual(receipt["proof"], [] if admitted else ["arm-not-observed"])
                self.assertEqual(saved, receipt)
                self.assertEqual(saved["is_in_merge_queue"], observed["isInMergeQueue"])
                self.assertEqual(gh.arm_calls, [(row["repo"], 17, PR_HEAD)])

    def test_target_not_on_source_main_stays_unarmed(self):
        row, pr = self._row_and_pr()
        gh = _VerifyFakeGitHub(target_on_main=False)
        with tempfile.TemporaryDirectory() as directory:
            receipt = self.shared_pins.verify_and_arm(
                gh, row, pr, [row["repo"]], NEW, Path(directory)
            )

        self.assertIn("new-sha-not-on-source-main", receipt["proof"])
        self.assertEqual(gh.arm_calls, [])

    def test_replaced_sha_not_ancestor_of_target_stays_unarmed(self):
        row, pr = self._row_and_pr()
        gh = _VerifyFakeGitHub(old_descends=False)
        with tempfile.TemporaryDirectory() as directory:
            receipt = self.shared_pins.verify_and_arm(
                gh, row, pr, [row["repo"]], NEW, Path(directory)
            )

        self.assertIn("not-forward-source-ancestry", receipt["proof"])
        self.assertEqual(gh.arm_calls, [])


class TestGitTransportPureGuards(unittest.TestCase):
    def test_push_args_translates_only_the_expected_new_branch_request(self):
        self.assertEqual(
            git_transport.push_args(["origin", "--force-with-lease", BRANCH], BRANCH),
            ["origin", BRANCH],
        )

    def test_push_args_rejects_force_delete_tags_alternate_refs_and_bypass(self):
        bad_args = [
            ["origin", "--force", BRANCH],
            ["origin", "-f", BRANCH],
            ["origin", "--delete", BRANCH],
            ["origin", "--mirror", BRANCH],
            ["origin", "--all", BRANCH],
            ["origin", "--tags", BRANCH],
            ["origin", "--no-verify", BRANCH],
            ["origin", "+" + BRANCH],
            ["origin", "refs/tags/v1"],
            ["origin", "renovate/shared-ci-week-2026-44"],
            ["-c", "core.hooksPath=/tmp", "origin", BRANCH],
            ["origin", BRANCH, "unrelated-ref"],
        ]
        for args in bad_args:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    git_transport.push_args(args, BRANCH)

    def test_push_args_rejects_invalid_branch_key(self):
        with self.assertRaises(ValueError):
            git_transport.push_args(["origin", "main"], "main")
        with self.assertRaises(ValueError):
            git_transport.push_args(["origin", "renovate/shared-ci-fix-" + "G" * 40],
                                    "renovate/shared-ci-fix-" + "G" * 40)

    def test_clone_args_adds_sparse_safe_clone_flags_and_hides_credentials(self):
        args = ["clone", "-b", "main", "https://github.com/SylphxAI/example.git", "."]
        self.assertEqual(
            git_transport.clone_args(args),
            ["clone", "--depth=1", "--filter=blob:none", "--no-checkout", *args[1:]],
        )
        with self.assertRaises(ValueError):
            git_transport.clone_args(["clone", "https://token@example.invalid/repo", "."])

    def test_clone_args_never_combines_duplicate_native_filters_or_depth(self):
        args = ["clone", "--filter=blob:none", "--depth=5", "--no-checkout", "-b", "main",
                "https://github.com/SylphxAI/example.git", "."]
        effective = git_transport.clone_args(args)
        self.assertEqual([arg for arg in effective if arg.startswith("--filter=")], ["--filter=blob:none"])
        self.assertEqual([arg for arg in effective if arg.startswith("--depth=")], ["--depth=1"])
        self.assertEqual(effective.count("--no-checkout"), 1)

    def test_clone_args_rejects_hook_disabling_config(self):
        for config in (["-c", "core.hooksPath=/dev/null"],
                       ["-ccore.hooksPath=/dev/null"],
                       ["--config=core.hooksPath=/dev/null"],
                       ["--conf=core.hooksPath=/dev/null"]):
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    git_transport.clone_args(["clone", *config, "https://github.com/SylphxAI/example.git", "."])

    def test_main_rejects_hook_disabling_config_subcommand(self):
        # A subprocess capture proves what the transport admits without
        # changing Git configuration or executing any outside command.
        with mock.patch.object(git_transport, "call", return_value=_RunResult()) as call:
            with self.assertRaises(ValueError):
                git_transport.main(["config", "core.hooksPath", "/dev/null"])
        call.assert_not_called()

    def test_main_rejects_alternate_effective_pushurl_before_any_push(self):
        expected = "https://github.com/SylphxAI/example.git"
        for push_result in (_RunResult(stdout="git@github.com:Other/unapproved.git\n"),
                            _RunResult(stdout=expected + "\n" + expected + "\n"),
                            _RunResult(returncode=1)):
            with self.subTest(push_url=push_result.stdout, returncode=push_result.returncode):
                with tempfile.TemporaryDirectory() as directory:
                    manifest = Path(directory) / "manifest.json"
                    claim = Path(directory) / "push-claim"
                    manifest.write_text(json.dumps({"repo": "SylphxAI/example"}))
                    env = {"SHARED_PINS_BRANCH": BRANCH, "SHARED_PINS_MANIFEST": str(manifest),
                           "SHARED_PINS_PUSH_CLAIM": str(claim)}
                    calls = [_RunResult(stdout=str(Path.cwd()) + "\n"),
                             _RunResult(stdout=expected + "\n"), push_result]
                    with mock.patch.dict(os.environ, env, clear=True):
                        with mock.patch.object(git_transport, "call", side_effect=calls) as call:
                            with self.assertRaisesRegex(ValueError, "push remote changed"):
                                git_transport.main(["push", "origin", BRANCH])
                    self.assertEqual(call.call_count, 3)
                    self.assertEqual(call.call_args_list[2].args[0],
                                     ["remote", "get-url", "--push", "--all", "origin"])
                    self.assertFalse(claim.exists())

    def test_main_allows_only_required_origin_setup_not_alternate_push_remote(self):
        denied = [
            ["remote", "set-url", "--push", "origin", "git@github.com:Other/unapproved.git"],
            ["remote", "add", "alternate", "git@github.com:Other/unapproved.git"],
            ["remote", "set-url", "origin", "git@github.com:SylphxAI/example.git", "old-pattern"],
        ]
        for args in denied:
            with self.subTest(args=args):
                with mock.patch.object(git_transport, "call") as call:
                    with self.assertRaises(ValueError):
                        git_transport.main(args)
                call.assert_not_called()
        with mock.patch.object(git_transport, "call", return_value=_RunResult()) as call:
            self.assertEqual(git_transport.main(
                ["remote", "set-url", "origin", "git@github.com:SylphxAI/example.git"]), 0)
        call.assert_called_once()

    def test_main_rejects_unapproved_leading_command_config(self):
        with self.assertRaises(ValueError):
            git_transport.main(["-c", "core.sshCommand=evil", "status"])
        with self.assertRaises(ValueError):
            git_transport.main(["-c", "credential.helper=store", "status"])

    def test_main_rejects_no_verify_and_force_for_non_push_commands(self):
        with self.assertRaises(ValueError):
            git_transport.main(["status", "--no-verify"])
        with self.assertRaises(ValueError):
            git_transport.main(["fetch", "--force"])


class _RunResult:
    def __init__(self, *, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestGitHubConnectedUserGuards(unittest.TestCase):
    def setUp(self):
        # Constructor identity/scope tests do not depend on the host's CLI
        # installation; every subprocess is a mock below.
        patcher = mock.patch.object(github_io.Path, "is_file", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _mock_run(self, *, login="shtse8", user_type="User", scopes="repo, workflow"):
        calls = []
        token = "secret-token-not-for-argv"
        user_response = "HTTP/2 200 OK\nx-oauth-scopes: " + scopes + "\n\n" + (
            '{"login": "' + login + '", "type": "' + user_type + '"}'
        )

        def run(argv, **kwargs):
            calls.append((list(argv), kwargs))
            if len(argv) >= 4 and argv[-4:] == ["auth", "token", "--hostname", "github.com"]:
                return _RunResult(stdout=token + "\n")
            if argv[:3] == ["gh", "api", "--method"]:
                return _RunResult(stdout=user_response if "--include" in argv else '{"ok": true}')
            if argv[:3] == ["gh", "pr", "merge"]:
                return _RunResult()
            raise AssertionError(f"unexpected subprocess: {argv}")

        return token, calls, run

    def test_ambient_credentials_do_not_override_connected_user_token(self):
        token, calls, run = self._mock_run()
        with mock.patch.dict(os.environ, GH_TOKEN="ambient-gh", GITHUB_TOKEN="ambient-github",
                             RENOVATE_TOKEN="ambient-renovate"):
            with mock.patch.object(github_io.subprocess, "run", side_effect=run):
                gh = github_io.GitHub()
        auth_environment = calls[0][1]["env"]
        self.assertFalse({"GH_TOKEN", "GITHUB_TOKEN", "RENOVATE_TOKEN"} & auth_environment.keys())
        self.assertEqual(gh.env["GH_TOKEN"], token)
        self.assertNotIn("GITHUB_TOKEN", gh.env)
        self.assertNotIn("RENOVATE_TOKEN", gh.env)

    def test_forward_requires_ahead_and_exact_merge_base(self):
        gh = github_io.GitHub.__new__(github_io.GitHub)
        for response, expected in (({"status": "ahead", "merge_base_commit": {"sha": OLD}}, True),
                                   ({"status": "behind", "merge_base_commit": {"sha": NEW}}, False),
                                   ({"status": "diverged", "merge_base_commit": {"sha": SOURCE_MAIN}}, False),
                                   ({"status": "ahead", "merge_base_commit": {"sha": SOURCE_MAIN}}, False),
                                   ({"status": "identical", "merge_base_commit": {"sha": OLD}}, False)):
            with self.subTest(response=response):
                with mock.patch.object(gh, "compare", return_value=response):
                    self.assertIs(gh.forward(OLD, NEW), expected)
        with mock.patch.object(gh, "compare") as compare:
            self.assertTrue(gh.forward(OLD, OLD))
        compare.assert_not_called()

    def test_missing_scope_refuses_connected_user(self):
        _, _, run = self._mock_run(scopes="repo")
        with mock.patch.object(github_io.subprocess, "run", side_effect=run):
            with self.assertRaisesRegex(github_io.Refused, "scopes-missing"):
                github_io.GitHub()

    def test_app_or_wrong_identity_refuses_without_fallback(self):
        for login, user_type in (("shtse8", "Bot"), ("other-user", "User")):
            with self.subTest(login=login, user_type=user_type):
                _, _, run = self._mock_run(login=login, user_type=user_type)
                with mock.patch.object(github_io.subprocess, "run", side_effect=run):
                    with self.assertRaisesRegex(github_io.Refused, "identity-mismatch"):
                        github_io.GitHub()

    def test_connected_token_is_only_in_child_environment_not_argv(self):
        token, calls, run = self._mock_run()
        with mock.patch.object(github_io.subprocess, "run", side_effect=run):
            gh = github_io.GitHub()
            # Exercise a normal API call and arm path as well as constructor
            # authentication; none may put the token in argv.
            gh.request("rate_limit")
            gh.arm("SylphxAI/example", 17, PR_HEAD)

        self.assertTrue(calls)
        for argv, kwargs in calls:
            self.assertFalse(any(token in str(part) for part in argv), argv)
            self.assertNotIn(token, kwargs.get("input") or "")
        self.assertEqual(gh.env["GH_TOKEN"], token)

    def test_remote_and_absolute_paths_are_rejected_before_subprocess(self):
        token, _, run = self._mock_run()
        with mock.patch.object(github_io.subprocess, "run", side_effect=run):
            gh = github_io.GitHub()
            with self.assertRaises(github_io.Refused):
                gh.request("https://github.com/repos/SylphxAI/example")
            with self.assertRaises(github_io.Refused):
                gh.request("/user")


if __name__ == "__main__":
    unittest.main()
