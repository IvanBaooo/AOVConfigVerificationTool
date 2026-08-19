from __future__ import annotations

import unittest
from unittest.mock import patch

from validation_mvp import run_mvp_validations


class ValidationContentRuleTests(unittest.TestCase):
	def test_web_content_rule_drives_skin_precheck_source(self) -> None:
		config = {
			"check_window": {
				"start_time": "20260701000000",
				"end_time": "20260731235959",
			},
			"region_code": "TW",
			"content_checks": [{
				"id": "skin-sale-window",
				"type": "skin_sale_window",
				"enabled": True,
				"name": "英雄皮肤上下架与促销关联",
				"dtxml_path": "/Xml/Garena/{region}/CommonCore/英雄皮肤促销表.dtxml",
				"main_sheet": "主表",
				"promotion_sheet": "促销表",
				"trigger_paths": ["/Databin/Server/Shop/SvrHeroSkinShop.xml"],
			}],
		}
		passed = {
			"status": "passed",
			"item_count": 0,
			"warning_count": 0,
			"items": [],
			"warnings": [],
		}

		with patch("validation_mvp.run_skin_precheck", return_value=passed) as runner:
			result = run_mvp_validations(
				fixed_paths=["Taiwan/Databin/Server/Shop/SvrHeroSkinShop.xml"],
				local_root="G:/Branches/B54/Tools/TdrTable/ServerBytes",
				validation_config=config,
			)

		self.assertEqual("passed", result["checks"]["skin_precheck"]["status"])
		kwargs = runner.call_args.kwargs
		self.assertEqual(config["content_checks"][0]["dtxml_path"], kwargs["dtxml_relative_path"])
		self.assertEqual("主表", kwargs["main_sheet"])
		self.assertEqual("促销表", kwargs["promotion_sheet"])
		self.assertEqual(config["content_checks"][0]["trigger_paths"], kwargs["trigger_paths"])

	def test_empty_or_disabled_content_rules_skip_table_read(self) -> None:
		for checks in ([], [{
			"id": "skin-sale-window",
			"type": "skin_sale_window",
			"enabled": False,
		}]):
			with self.subTest(checks=checks), patch("validation_mvp.run_skin_precheck") as runner:
				result = run_mvp_validations(
					fixed_paths=["Taiwan/Databin/Server/Shop/SvrHeroSkinShop.xml"],
					local_root="G:/Branches/B54/Tools/TdrTable/ServerBytes",
					validation_config={"content_checks": checks},
				)
				self.assertEqual("content_check_disabled", result["checks"]["skin_precheck"]["reason"])
				runner.assert_not_called()


if __name__ == "__main__":
	unittest.main()