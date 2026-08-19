from __future__ import annotations

import copy
import unittest

from validation_rule_sets import (
	ValidationRuleSetError,
	effective_rule_set,
	validate_effective_rule_set,
	validate_rule_set,
)


def sample_rule_set() -> dict[str, object]:
	return {
		"schema_version": "1.0",
		"rule_set_id": "aov-main",
		"version": "2026.07.27.1",
		"published_at": "2026-07-27T13:00:00Z",
		"notes": "MVP rules",
		"common": {
			"path_mappings": [{
				"path_suffix": "/Databin/Server/Event/SvrEvent.xml",
				"module": "活动",
				"table_name": "公共活动表",
			}],
			"whitelist_paths": ["CommonIgnored.xml"],
			"content_checks": [{
				"id": "skin-sale-window",
				"type": "skin_sale_window",
				"enabled": True,
				"name": "英雄皮肤上下架与促销关联",
				"dtxml_path": "/Xml/Garena/{region}/CommonCore/英雄皮肤促销表.dtxml",
				"main_sheet": "svr下发皮肤上下架表",
				"promotion_sheet": "svr下发皮肤促销特卖",
				"trigger_paths": [
					"/Databin/Server/Shop/SvrHeroSkinShop.xml",
					"/Databin/Server/Shop/SvrHeroSkinShop.bytes",
				],
			}],
		},
		"regions": {
			"TW": {
				"path_mappings": [{
					"path_suffix": "/Databin/Server/Event/SvrEvent.xml",
					"module": "活动",
					"table_name": "TW 活动表",
				}],
				"whitelist_paths": ["TwIgnored.xml"],
			}
		},
	}


class ValidationRuleSetTests(unittest.TestCase):
	def test_region_mapping_overrides_common_and_whitelist_is_merged(self) -> None:
		effective = effective_rule_set(sample_rule_set(), "tw")
		rules = effective["rules"]

		self.assertEqual("TW", effective["region_code"])
		self.assertEqual("TW 活动表", rules["path_mappings"][0]["table_name"])
		self.assertEqual(
			["/CommonIgnored.xml", "/TwIgnored.xml"],
			rules["whitelist_paths"],
		)
		self.assertEqual(64, len(effective["rule_hash"]))
		self.assertEqual(effective, validate_effective_rule_set(effective))

	def test_regional_content_check_overrides_common_by_id(self) -> None:
		rule_set = copy.deepcopy(sample_rule_set())
		override = copy.deepcopy(rule_set["common"]["content_checks"][0])
		override["enabled"] = False
		rule_set["regions"]["TW"]["content_checks"] = [override]

		effective = effective_rule_set(rule_set, "TW")

		self.assertEqual(1, len(effective["rules"]["content_checks"]))
		self.assertFalse(effective["rules"]["content_checks"][0]["enabled"])
	def test_effective_hash_tampering_is_rejected(self) -> None:
		effective = effective_rule_set(sample_rule_set(), "TH")
		effective["notes"] = "tampered"

		with self.assertRaisesRegex(ValidationRuleSetError, "hash verification"):
			validate_effective_rule_set(effective)

	def test_unknown_fields_and_regions_are_rejected(self) -> None:
		rule_set = copy.deepcopy(sample_rule_set())
		rule_set["regions"]["XX"] = {}

		with self.assertRaisesRegex(ValidationRuleSetError, "Unsupported regions"):
			validate_rule_set(rule_set)


if __name__ == "__main__":
	unittest.main()
