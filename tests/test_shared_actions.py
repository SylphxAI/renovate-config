"""Only the supervised desk pass may publish owned shared-action pin rolls."""
import json
from pathlib import Path
import unittest


class SharedActionPolicyTests(unittest.TestCase):
    def test_public_preset_disables_shared_action_competitors_without_changing_other_policy(self):
        config = json.loads((Path(__file__).resolve().parents[1] / "default.json").read_text())
        owned = [rule for rule in config["packageRules"]
                 if rule.get("matchPackageNames") == ["SylphxAI/.github"]]
        self.assertEqual(len(owned), 1)
        rule = owned[0]
        self.assertFalse(rule["enabled"])
        self.assertFalse(rule["automerge"])
        self.assertNotIn("matchManagers", rule)
        self.assertNotIn("minimumReleaseAge", rule)
        self.assertNotIn("schedule", rule)
        self.assertEqual(config["minimumReleaseAge"], "3 days")
        self.assertEqual(config["prConcurrentLimit"], 3)
        self.assertEqual(config["prHourlyLimit"], 2)


if __name__ == "__main__":
    unittest.main()
