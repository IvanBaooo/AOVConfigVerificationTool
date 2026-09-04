from __future__ import annotations

import copy
import unittest

from rules.sets import (
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
	def test_incident_rule_types_and_extended_fields_are_accepted(self) -> None:
		rule_set = sample_rule_set()
		rule_set["common"]["content_checks"] = [
			{
				"id": "hidden-item-tab",
				"type": "hidden_item_listing",
				"enabled": True,
				"name": "隐藏道具识别与单独标注",
				"trigger_paths": ["/Databin/Server/Item/SvrItem.bytes"],
				"severity": "warning",
				"blocking": False,
				"source_incident": "I7",
				"verify": {"method": "manual"},
			},
			{
				"id": "package-completeness-manual",
				"type": "package_completeness",
				"enabled": True,
				"name": "输入清单与包内容一一对应",
				"trigger_paths": ["*"],
				"applies_to": "manual_bytes_list_only",
				"params": {"min_file_count": 1, "min_total_bytes": 1024},
			},
		]

		validated = validate_rule_set(rule_set)
		checks = validated["common"]["content_checks"]

		self.assertEqual("hidden_item_listing", checks[0]["type"])
		self.assertEqual("warning", checks[0]["severity"])
		self.assertFalse(checks[0]["blocking"])
		self.assertEqual("I7", checks[0]["source_incident"])
		self.assertEqual({"method": "manual"}, checks[0]["verify"])
		self.assertNotIn("dtxml_path", checks[0])
		self.assertEqual("manual_bytes_list_only", checks[1]["applies_to"])
		self.assertEqual({"min_file_count": 1, "min_total_bytes": 1024}, checks[1]["params"])

	def test_non_skin_check_type_with_dtxml_path_is_optional_but_validated(self) -> None:
		rule_set = sample_rule_set()
		rule_set["common"]["content_checks"] = [{
			"id": "expiry-activity-cross-check",
			"type": "expiry_time_cross_check",
			"enabled": True,
			"name": "道具有效期与活动时间关联校验",
			"trigger_paths": ["/Databin/Server/Item/SvrItem.bytes"],
			"dtxml_path": "/Xml/Garena/{region}/CommonCore/41.svr下发道具信息表.dtxml",
		}]

		validated = validate_rule_set(rule_set)

		self.assertEqual(
			"/Xml/Garena/{region}/CommonCore/41.svr下发道具信息表.dtxml",
			validated["common"]["content_checks"][0]["dtxml_path"],
		)

	def test_unsupported_check_type_and_bad_severity_are_rejected(self) -> None:
		for patch in (
			{"type": "item_id_uniqueness"},
			{"type": "hidden_item_listing", "severity": "fatal"},
			{"type": "hidden_item_listing", "blocking": "yes"},
		):
			rule_set = sample_rule_set()
			check = {
				"id": "demo-check",
				"type": "hidden_item_listing",
				"enabled": True,
				"name": "demo",
				"trigger_paths": ["/x"],
			}
			check.update(patch)
			rule_set["common"]["content_checks"] = [check]
			with self.subTest(patch=patch), self.assertRaises(ValidationRuleSetError):
				validate_rule_set(rule_set)

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
