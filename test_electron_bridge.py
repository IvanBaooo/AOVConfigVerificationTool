from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from electron_bridge import (
	ElectronBridgeService,
	build_validation_config,
	merge_settings,
	renderer_settings,
)
from local_settings import save_local_settings
from svn_pack_source import PackSourceInspection


class ElectronBridgeSettingsTests(unittest.TestCase):
	def test_renderer_settings_never_exposes_ftp_password(self) -> None:
		settings = {
			"package_region": "TW",
			"svn_password": "legacy-secret",
			"ftp_profiles": {
				"TW": {
					"host": "ftp.example.test",
					"username": "shared",
					"password": "secret",
				}
			},
		}

		result = renderer_settings(settings)

		profile = result["ftp_profiles"]["TW"]
		self.assertNotIn("password", profile)
		self.assertNotIn("svn_password", result)
		self.assertTrue(profile["password_configured"])

	def test_merge_settings_preserves_password_when_renderer_leaves_it_blank(self) -> None:
		existing = {
			"svn_password": "legacy-secret",
			"ftp_profiles": {
				"TW": {"host": "old", "password": "secret", "passive": True},
			}
		}
		incoming = {
			"svn_password": "runtime-secret",
			"ftp_profiles": {
				"TW": {"host": "new", "password": "", "password_configured": True},
			}
		}

		result = merge_settings(existing, incoming)

		self.assertEqual(result["ftp_profiles"]["TW"]["host"], "new")
		self.assertEqual(result["ftp_profiles"]["TW"]["password"], "secret")
		self.assertNotIn("svn_password", result)

	def test_build_validation_config_keeps_explicit_revision_semantics(self) -> None:
		config = build_validation_config(
			{
				"region": "TW",
				"current_revision_spec": "r10001,r10003",
				"last_external_revision_spec": "r9999",
				"input_method": "revision_spec",
				"svn_target": "https://svn.example.test/project/Tools/TdrTable/ServerBytes",
				"scope_roots": "/Taiwan",
				"enable_commit_check": True,
				"enable_region_filter": True,
			},
			"svn log body",
		)

		commit = config["commit_record"]
		self.assertEqual(commit["current_revision_spec"], "r10001,r10003")
		self.assertEqual(commit["scope_roots"], ["/Taiwan"])
		self.assertEqual(config["package_region_code"], "TW")
		diff_config = config["dtxml_diff"]
		self.assertTrue(diff_config["enabled"])
		self.assertEqual("r10001,r10003", diff_config["current_revision_spec"])
		self.assertEqual("svn log body", diff_config["svn_log_text"])
		self.assertTrue(str(diff_config["tdr_svn_target"]).endswith("/Tools/TdrTable"))

	def test_bootstrap_returns_safe_settings_and_queue_count(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			save_local_settings(
				{
					"package_region": "TW",
					"ftp_profiles": {"TW": {"host": "ftp", "password": "secret"}},
				},
				root / "settings.json",
			)
			service = ElectronBridgeService(root)

			result = service.command_bootstrap({}, lambda _event, _data: None)

			self.assertEqual(result["pending_sync_count"], 0)
			self.assertNotIn("password", result["settings"]["ftp_profiles"]["TW"])

	def test_packaging_input_reads_tdr_root_and_preserves_serverbytes_anchor(self) -> None:
		log_text = "\n".join([
			"------------------------------------------------------------------------",
			"r10003 | user | 2026-01-01 | 1 line",
			"Changed paths:",
			"   M /HON_proj/branches/PUB/Beta54/Tools/TdrTable/Xml/Garena/TW/CommonCore/table.dtxml",
			"   M /HON_proj/branches/PUB/Beta54/Tools/TdrTable/ServerBytes/Taiwan/Databin/Server/table.xml",
			"",
			"message",
		])
		fetch_result = SimpleNamespace(
			returncode=0,
			stdout=log_text,
			stderr="",
			safe_command=["svn", "log"],
		)
		with tempfile.TemporaryDirectory() as temporary_directory:
			service = ElectronBridgeService(Path(temporary_directory))
			with patch("electron_bridge.fetch_svn_log_with_auth", return_value=fetch_result) as fetch:
				file_list, resolved_log = service._packaging_input(
					{
						"input_method": "revision_spec",
						"svn_log_source": "auto",
						"current_revision_spec": "r10003",
						"svn_target": "http://example.test/repo/Tools/TdrTable/ServerBytes/Taiwan",
						"region": "TW",
					},
					lambda _event, _data: None,
				)
		self.assertEqual(log_text, resolved_log)
		self.assertEqual("M ServerBytes/Taiwan/Databin/Server/table.xml", file_list)
		self.assertEqual(
			"http://example.test/repo/Tools/TdrTable",
			fetch.call_args.kwargs["svn_target"],
		)

	def test_pack_response_exposes_module_overview_and_compact_activity_details(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			save_local_settings({"package_region": "TW"}, root / "settings.json")
			service = ElectronBridgeService(root)
			pack_result = SimpleNamespace(
				tar_path=str(root / "sgame_TW_Beta54_1.tar.gz"),
				base_name="sgame_TW_Beta54_1",
				report_path=str(root / "report.json"),
				output_dir=str(root / "output"),
				md5="abc",
				success_count=1,
				failure_count=0,
				skipped_count=0,
				report={
					"validation": {"summary": {"error_count": 0, "warning_count": 0}},
					"input": {"region_filter": {}},
					"module_analysis": {
						"overview": {
							"activity_updates": [{"label": "签到活动", "count": 1}],
							"related_activity_count": 2,
							"has_structural_risk": False,
							"business_rule_status": "not_enabled",
						},
						"modules": [{
							"module": "activity",
							"name": "活动",
							"items": [{
								"object_id": "400",
								"name": "七日签到",
								"activity_type": "签到活动表",
								"changes": [{"change_type": "modified"}],
								"display_lines": ["第1天: 钻石 ×20"],
							}],
						}, {
							"module": "item",
							"name": "道具",
							"items": [{
								"object_id": "5001",
								"name": "活动币",
								"object_type": "item",
								"changes": [{"change_type": "added"}],
								"display_lines": ["隐藏道具: 是"],
							}],
						}],
						"uninterpreted_changes": [{"file_name": "other.dtxml"}],
						"deferred_changes": [{"file_name": "later.dtxml"}],
					},
				},
			)
			with (
				patch.object(service, "_packaging_input", return_value=("M file.xml", "svn log")),
				patch(
					"electron_bridge.inspect_pack_source",
					return_value=PackSourceInspection(
						mode="local_latest",
						target_revision=0,
						head_revision=100,
						selected_file_count=1,
						local_root="local",
					),
				),
				patch("electron_bridge.pack_incremental_package_mvp_region_named", return_value=pack_result) as pack,
			):
				result = service.command_pack({"region": "TW", "test_mode": True}, lambda _event, _data: None)

		self.assertEqual("签到活动", result["module_overview"]["activity_updates"][0]["label"])
		self.assertEqual("400", result["activity_details"][0]["activity_id"])
		self.assertTrue(result["activity_details"][0]["direct_change"])
		self.assertEqual(["第1天: 钻石 ×20"], result["activity_details"][0]["display_lines"])
		self.assertEqual(2, len(result["content_details"]))
		self.assertEqual("item", result["content_details"][1]["module"])
		self.assertEqual("5001", result["content_details"][1]["object_id"])
		self.assertEqual("道具", result["content_details"][1]["module_name"])
		self.assertTrue(result["test_mode"])
		self.assertFalse(result["can_archive"])
		self.assertEqual(1, result["module_overview"]["uninterpreted_change_count"])
		self.assertEqual(1, result["module_overview"]["deferred_change_count"])
		self.assertTrue(str(pack.call_args.kwargs["output_parent"]).endswith("output\\tests"))


if __name__ == "__main__":
	unittest.main()
