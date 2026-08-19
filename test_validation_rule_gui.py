from __future__ import annotations

import unittest

from test_validation_rule_sets import sample_rule_set
from validation_rule_client import RuleLoadResult
from validation_rule_gui import apply_rule_set_to_validation_config
from validation_rule_sets import effective_rule_set


class ValidationRuleGuiMergeTests(unittest.TestCase):
	def test_remote_rules_merge_with_local_whitelist_and_record_metadata(self) -> None:
		rule_set = effective_rule_set(sample_rule_set(), "TW")
		result = apply_rule_set_to_validation_config(
			{
				"commit_record": {
					"enabled": True,
					"whitelist_paths": ["LocalIgnored.xml", "CommonIgnored.xml"],
				}
			},
			RuleLoadResult(rule_set, "remote"),
		)

		commit_record = result["commit_record"]
		self.assertEqual(
			["/CommonIgnored.xml", "/TwIgnored.xml", "/LocalIgnored.xml"],
			commit_record["whitelist_paths"],
		)
		self.assertEqual("TW 活动表", commit_record["path_mappings"][0]["table_name"])
		self.assertEqual("skin_sale_window", result["content_checks"][0]["type"])
		self.assertEqual("2026.07.27.1", result["rule_set"]["version"])
		self.assertEqual("remote", result["rule_set"]["source"])
		self.assertEqual(rule_set["rule_hash"], result["rule_set"]["rule_hash"])


if __name__ == "__main__":
	unittest.main()
