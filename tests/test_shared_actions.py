"""Owned rolling action pins must not wait for a release-age window."""
import json
from pathlib import Path
import unittest


class SharedActionPolicyTests(unittest.TestCase):
    def test_only_the_owned_shared_action_group_has_no_release_age_delay(self):
        config = json.loads((Path(__file__).resolve().parents[1] / "default.json").read_text())
        immediate = [rule for rule in config["packageRules"]
                     if rule.get("minimumReleaseAge") in (0, "0", "0 days")]
        self.assertEqual(len(immediate), 1)
        rule = immediate[0]
        self.assertEqual(rule["matchManagers"], ["github-actions"])
        self.assertEqual(rule["matchPackageNames"], ["SylphxAI/.github"])
        self.assertEqual(rule["groupName"], "SylphxAI/.github shared actions")
        self.assertEqual(rule["schedule"], ["after 1am and before 2am"])
        self.assertTrue(rule["automerge"])
        self.assertEqual(config["minimumReleaseAge"], "3 days")
        self.assertEqual(config["prConcurrentLimit"], 3)
        self.assertEqual(config["prHourlyLimit"], 2)


if __name__ == "__main__":
    unittest.main()
