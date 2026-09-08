from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from archive_fixtures import sample_report
from backend_archive_contract_v1 import build_archive_record
from svn_commit_validation import run_commit_record_check
from svn_commit_validation_optimized import run_commit_record_check_optimized


SVN_LOG = """\
r101 | alice | 2026-08-01 09:00:00 +0800 |
Changed paths:
   M /repo/ServerBytes/Taiwan/Databin/Server/Shop/SvrHeroSkinShop.xml
   A /repo/ServerBytes/Taiwan/Databin/Server/Shop/SvrMysterySale.xml
   M /repo/ServerBytes/Thailand/Databin/Server/Shop/Other.xml

修复皮肤商店配置
第二行备注

r102 | bob | 2026-08-01 12:00:00 +0800 |
Changed paths:
   D /repo/ServerBytes/Taiwan/Databin/Server/Shop/Old.xml

删除废弃表

r103 | bob | 2026-08-02 10:00:00 +0800 |
Changed paths:
   M /repo/ServerBytes/Taiwan/Databin/Server/Shop/Current.xml

本次打包提交
"""


def _commit_config(svn_log: str = SVN_LOG) -> dict[str, object]:
	return {
		"commit_record": {
			"enabled": True,
			"input_method": "revision_spec",
			"last_external_revision_spec": "r100",
			"current_revision_spec": "r103",
			"scope_roots": ["/Taiwan"],
			"svn_log_text": svn_log,
		}
	}


class RevisionDetailsTests(unittest.TestCase):
	def test_revision_details_aggregate_message_author_and_scoped_files(self) -> None:
		result = run_commit_record_check(
			fixed_paths=["/Taiwan/Databin/Server/Shop/Current.xml"],
			validation_config=_commit_config(),
		)

		details = result["revision_details"]
		self.assertEqual([101, 102], [detail["revision"] for detail in details])

		first = details[0]
		self.assertEqual("alice", first["author"])
		self.assertEqual("2026-08-01 09:00:00 +0800", first["date"])
		self.assertEqual("修复皮肤商店配置\n第二行备注", first["message"])
		self.assertEqual(
			[
				{
					"fixed_path": "/Taiwan/Databin/Server/Shop/SvrHeroSkinShop.xml",
					"action": "M",
					"readable_name": "英雄皮肤促销表 / SvrHeroSkinShop.xml",
				},
				{
					"fixed_path": "/Taiwan/Databin/Server/Shop/SvrMysterySale.xml",
					"action": "A",
					"readable_name": "SvrMysterySale / SvrMysterySale.xml",
				},
			],
			first["files"],
		)

		second = details[1]
		self.assertEqual("bob", second["author"])
		self.assertEqual("删除废弃表", second["message"])
		self.assertEqual(1, len(second["files"]))
		self.assertEqual("D", second["files"][0]["action"])
		self.assertEqual("/Taiwan/Databin/Server/Shop/Old.xml", second["files"][0]["fixed_path"])

	def test_unresolved_gap_revisions_are_excluded_from_revision_details(self) -> None:
		partial_log = """\
r101 | alice | 2026-08-01 09:00:00 +0800 |
Changed paths:
   M /repo/ServerBytes/Taiwan/Databin/Server/Shop/SvrHeroSkinShop.xml

只覆盖 r101
"""
		result = run_commit_record_check(
			fixed_paths=["/Taiwan/Databin/Server/Shop/Current.xml"],
			validation_config=_commit_config(partial_log),
		)

		self.assertEqual([101], [detail["revision"] for detail in result["revision_details"]])
		gap_warnings = [w for w in result["warnings"] if w.get("type") == "unresolved_revision_gap"]
		self.assertEqual(1, len(gap_warnings))
		self.assertEqual([102], gap_warnings[0]["revisions"])

	def test_optimized_wrapper_keeps_revision_details(self) -> None:
		result = run_commit_record_check_optimized(
			fixed_paths=["/Taiwan/Databin/Server/Shop/Current.xml"],
			validation_config=_commit_config(),
		)

		self.assertEqual([101, 102], [detail["revision"] for detail in result["revision_details"]])

	def test_revision_details_respect_whitelist_and_mark_high_risk(self) -> None:
		svn_log = """\
r201 | alice | 2026-08-01 09:00:00 +0800 |
Changed paths:
   M /repo/ServerBytes/Taiwan/Databin/Server/Actor/Hero_MD5_Android.txt

自动提交 MD5

r202 | bob | 2026-08-01 12:00:00 +0800 |
Changed paths:
   M /repo/ServerBytes/Taiwan/Databin/Server/Actor/Hero_MD5.txt
   M /repo/ServerBytes/Taiwan/Databin/Server/Global/ResSvr2CltIluaCfg.xml
   M /repo/ServerBytes/Taiwan/Databin/Server/Shop/Current.xml

混合提交
"""
		config = _commit_config(svn_log)
		commit = dict(config["commit_record"])
		commit["last_external_revision_spec"] = "r200"
		commit["current_revision_spec"] = "r203"
		commit["whitelist_paths"] = ["/Hero_MD5*"]
		commit["high_risk_paths"] = ["/ResSvr2CltIluaCfg*"]
		config["commit_record"] = commit

		result = run_commit_record_check_optimized(
			fixed_paths=["/Taiwan/Databin/Server/Shop/Current.xml"],
			validation_config=config,
		)

		details = result["revision_details"]
		self.assertEqual([202], [detail["revision"] for detail in details])
		files = details[0]["files"]
		self.assertEqual(
			[
				"/Taiwan/Databin/Server/Global/ResSvr2CltIluaCfg.xml",
				"/Taiwan/Databin/Server/Shop/Current.xml",
			],
			[file_info["fixed_path"] for file_info in files],
		)
		high_risk_file = files[0]
		self.assertIs(True, high_risk_file["high_risk"])
		self.assertEqual("/ResSvr2CltIluaCfg*", high_risk_file["high_risk_pattern"])
		self.assertNotIn("high_risk", files[1])
		self.assertEqual([], result["warnings"] and [
			w for w in result["warnings"] if "Hero_MD5" in str(w.get("fixed_path"))
		])

	def test_revision_details_survive_archive_contract_and_strict_schema(self) -> None:
		report = sample_report()
		report["package"]["file_count"] = 1
		report["validation"]["checks"]["commit_record"]["revision_details"] = [
			{
				"revision": 1699900,
				"author": "alice",
				"date": "2026-08-01 09:00:00 +0800",
				"message": "修复皮肤商店配置\n第二行备注",
				"files": [
					{
						"fixed_path": "/Taiwan/Databin/Server/Shop/SvrHeroSkinShop.xml",
						"action": "M",
						"readable_name": "英雄皮肤促销表 / SvrHeroSkinShop.xml",
					}
				],
			}
		]

		payload = build_archive_record(report)
		details = payload["validation"]["commit_record"]["revision_details"]
		self.assertEqual(1, len(details))
		detail = details[0]
		self.assertEqual(1699900, detail["revision"])
		self.assertEqual("alice", detail["author"])
		self.assertEqual("修复皮肤商店配置 第二行备注", detail["message"])
		self.assertEqual(
			[
				{
					"fixed_path": "/Taiwan/Databin/Server/Shop/SvrHeroSkinShop.xml",
					"action": "M",
					"readable_name": "英雄皮肤促销表 / SvrHeroSkinShop.xml",
				}
			],
			detail["files"],
		)

		schema_path = Path(__file__).parent.parent / "schemas" / "aov-package-archive-v1-strict.schema.json"
		schema = json.loads(schema_path.read_text(encoding="utf-8"))
		validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
		errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
		self.assertEqual([], errors, "\n".join(error.message for error in errors))

	def test_revision_detail_message_sanitizes_literal_escapes(self) -> None:
		report = sample_report()
		report["package"]["file_count"] = 1
		report["validation"]["checks"]["commit_record"]["revision_details"] = [
			{
				"revision": 1739764,
				"author": "mgamebuild",
				"date": "2026-08-20 03:00:00 +0800",
				"message": "bugs/view/1110124621162143734\\n--story=136680567",
				"files": [
					{
						"fixed_path": "/Taiwan/Databin/Server/Shop/SvrHeroSkinShop.xml",
						"action": "M",
						"readable_name": "英雄皮肤促销表 / SvrHeroSkinShop.xml",
					}
				],
			}
		]

		payload = build_archive_record(report)
		detail = payload["validation"]["commit_record"]["revision_details"][0]
		self.assertEqual("bugs/view/1110124621162143734 --story=136680567", detail["message"])


if __name__ == "__main__":
	unittest.main()
