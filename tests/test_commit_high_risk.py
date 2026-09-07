from __future__ import annotations

import unittest

from backend_archive_contract_v1 import build_archive_record
from electron_bridge import build_validation_config
from svn_commit_validation_optimized import (
	build_commit_high_risk_check,
	run_commit_record_check_optimized,
)
from test_backend_archive_contract_v1 import final_sample_report
from validation_full_mvp_optimized import run_full_mvp_validations_optimized


SVN_LOG = """\
r102 | tester | 2026-07-27 |
Changed paths:
   M /repo/Tools/TdrTable/ServerBytes/Taiwan/Databin/Server/Global/ResSvr2CltIluaCfg.xml

r101 | tester | 2026-07-27 |
Changed paths:
   M /repo/Tools/TdrTable/ServerBytes/Taiwan/Databin/Server/Shop/Current.xml
"""


def _commit_config(**overrides: object) -> dict[str, object]:
	config: dict[str, object] = {
		"commit_record": {
			"enabled": True,
			"input_method": "revision_spec",
			"last_external_revision_spec": "r100",
			"current_revision_spec": "r102",
			"scope_roots": ["/Taiwan"],
			"svn_log_text": SVN_LOG,
		}
	}
	config["commit_record"].update(overrides)
	return config


class CommitHighRiskPipelineTests(unittest.TestCase):
	def test_hit_marks_warning_and_collects_statistics(self) -> None:
		result = run_commit_record_check_optimized(
			fixed_paths=["/Taiwan/Databin/Server/Shop/Current.xml"],
			validation_config=_commit_config(high_risk_paths=["ResSvr2CltIluaCfg*"]),
		)

		self.assertEqual("warning", result["status"])
		self.assertEqual(2, result["warning_count"])
		flagged = [w for w in result["warnings"] if w.get("high_risk")]
		self.assertEqual(1, len(flagged))
		self.assertEqual(
			"/Taiwan/Databin/Server/Global/ResSvr2CltIluaCfg.xml",
			flagged[0]["fixed_path"],
		)
		self.assertEqual("/ResSvr2CltIluaCfg*", flagged[0]["high_risk_pattern"])
		statistics = result["statistics"]
		self.assertEqual(1, statistics["high_risk_warning_count"])
		self.assertEqual(
			["/Taiwan/Databin/Server/Global/ResSvr2CltIluaCfg.xml"],
			statistics["high_risk_paths"],
		)
		self.assertEqual(["/ResSvr2CltIluaCfg*"], statistics["high_risk_patterns"])

	def test_no_hit_leaves_warnings_untouched(self) -> None:
		result = run_commit_record_check_optimized(
			fixed_paths=["/Taiwan/Databin/Server/Shop/Current.xml"],
			validation_config=_commit_config(high_risk_paths=["/Thailand/"]),
		)

		self.assertEqual(2, result["warning_count"])
		self.assertTrue(all("high_risk" not in w for w in result["warnings"]))
		self.assertEqual([], result["statistics"]["high_risk_paths"])
		self.assertEqual(0, result["statistics"]["high_risk_warning_count"])

	def test_hit_does_not_exempt_warning(self) -> None:
		result = run_commit_record_check_optimized(
			fixed_paths=["/Taiwan/Databin/Server/Shop/Current.xml"],
			validation_config=_commit_config(
				high_risk_paths=["ResSvr2CltIluaCfg*"],
				whitelist_paths=["Hero_MD5*.txt"],
			),
		)

		self.assertEqual("warning", result["status"])
		self.assertEqual([], result["ignored_changes"])
		self.assertEqual(2, len(result["warnings"]))


class CommitHighRiskCheckTests(unittest.TestCase):
	def test_hit_produces_confirm_check_with_items(self) -> None:
		config = _commit_config(high_risk_paths=["ResSvr2CltIluaCfg*"])
		result = run_commit_record_check_optimized(
			fixed_paths=["/Taiwan/Databin/Server/Shop/Current.xml"],
			validation_config=config,
		)

		check = build_commit_high_risk_check(result, config)

		self.assertIsNotNone(check)
		self.assertEqual("confirm", check["status"])
		self.assertEqual("高危路径提交确认", check["name"])
		self.assertEqual(["（提交记录）"], check["tables"])
		self.assertEqual(1, check["item_count"])
		item = check["items"][0]
		self.assertEqual("high_risk_commit", item["type"])
		self.assertEqual("confirm", item["level"])
		self.assertEqual("/Taiwan/Databin/Server/Global/ResSvr2CltIluaCfg.xml", item["fixed_path"])
		self.assertEqual([102], item["revisions"])
		self.assertEqual("/ResSvr2CltIluaCfg*", item["high_risk_pattern"])

	def test_no_hit_produces_passed_check(self) -> None:
		config = _commit_config(high_risk_paths=["/Thailand/"])
		result = run_commit_record_check_optimized(
			fixed_paths=["/Taiwan/Databin/Server/Shop/Current.xml"],
			validation_config=config,
		)

		check = build_commit_high_risk_check(result, config)

		self.assertEqual("passed", check["status"])
		self.assertEqual(0, check["item_count"])
		self.assertEqual([], check["items"])

	def test_no_patterns_produces_no_check(self) -> None:
		config = _commit_config()
		result = run_commit_record_check_optimized(
			fixed_paths=["/Taiwan/Databin/Server/Shop/Current.xml"],
			validation_config=config,
		)

		self.assertIsNone(build_commit_high_risk_check(result, config))

	def test_full_validations_expose_check_and_count_confirm(self) -> None:
		result = run_full_mvp_validations_optimized(
			fixed_paths=["/Taiwan/Databin/Server/Shop/Current.xml"],
			local_root="/nonexistent",
			validation_config=_commit_config(high_risk_paths=["ResSvr2CltIluaCfg*"]),
		)

		check = result["checks"]["commit_high_risk_confirm"]
		self.assertEqual("confirm", check["status"])
		self.assertEqual(1, check["item_count"])
		self.assertGreaterEqual(result["summary"]["confirm_count"], 1)


class CommitHighRiskPayloadTests(unittest.TestCase):
	def test_archive_payload_carries_high_risk_trace(self) -> None:
		report = final_sample_report()
		commit_record = report["validation"]["checks"]["commit_record"]
		commit_record["warnings"][0]["high_risk"] = True
		commit_record["warnings"][0]["high_risk_pattern"] = "/Hero_MD5*"
		commit_record["statistics"]["high_risk_warning_count"] = 1
		commit_record["statistics"]["high_risk_paths"] = ["/Taiwan/Databin/Server/Actor/Hero_MD5.txt"]
		report["validation"]["checks"]["commit_high_risk_confirm"] = {
			"status": "confirm",
			"name": "高危路径提交确认",
			"item_count": 1,
			"warning_count": 0,
			"tables": ["（提交记录）"],
			"items": [
				{
					"type": "high_risk_commit",
					"level": "confirm",
					"fixed_path": "/Taiwan/Databin/Server/Actor/Hero_MD5.txt",
					"revisions": [1698418],
					"high_risk_pattern": "/Hero_MD5*",
				}
			],
			"warnings": [],
		}

		payload = build_archive_record(report)

		payload_commit = payload["validation"]["commit_record"]
		self.assertEqual(1, payload_commit["high_risk_hit_count"])
		self.assertEqual(
			["/Taiwan/Databin/Server/Actor/Hero_MD5.txt"],
			payload_commit["high_risk_paths"],
		)
		self.assertTrue(payload_commit["warnings"][0]["high_risk"])
		self.assertEqual("/Hero_MD5*", payload_commit["warnings"][0]["high_risk_pattern"])
		check = next(
			entry for entry in payload["validation"]["checks"]
			if entry["type"] == "commit_high_risk_confirm"
		)
		self.assertEqual("confirm", check["status"])
		self.assertEqual("高危路径提交确认", check["name"])
		self.assertEqual(["（提交记录）"], check["tables"])

	def test_archive_payload_defaults_empty_high_risk(self) -> None:
		payload = build_archive_record(final_sample_report())

		payload_commit = payload["validation"]["commit_record"]
		self.assertEqual(0, payload_commit["high_risk_hit_count"])
		self.assertEqual([], payload_commit["high_risk_paths"])


class CommitHighRiskBridgeTests(unittest.TestCase):
	def test_build_validation_config_injects_high_risk_paths(self) -> None:
		config = build_validation_config(
			{
				"region": "TW",
				"current_revision_spec": "r102",
				"last_external_revision_spec": "r100",
				"input_method": "revision_spec",
				"commit_high_risk": "ResSvr2CltIluaCfg*\n/Taiwan/Databin/Server/Global/",
			},
			"svn log body",
		)

		self.assertEqual(
			["ResSvr2CltIluaCfg*", "/Taiwan/Databin/Server/Global/"],
			config["commit_record"]["high_risk_paths"],
		)


if __name__ == "__main__":
	unittest.main()
