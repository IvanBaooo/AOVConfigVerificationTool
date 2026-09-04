"""electron_bridge 打包前规则拉取（pull）接线测试：remote / local_cache / built_in。"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError

from backend_archive_contract_v1 import SAFE_ID_PATTERN
from electron_bridge import ElectronBridgeService
from local_settings import save_local_settings
from rules.client import ValidationRuleCache, ValidationRuleClient
from rules.sets import effective_rule_set
from svn_pack_source import PackSourceInspection
from test_validation_rule_sets import sample_rule_set


class FakeResponse:
	def __init__(self, body: dict[str, object]) -> None:
		self.body = body

	def __enter__(self):
		return self

	def __exit__(self, *_args):
		return False

	def read(self) -> bytes:
		return json.dumps(self.body, ensure_ascii=False).encode("utf-8")


def _offline_opener(*_args, **_kwargs):
	raise URLError("offline")


class RulePullWiringTests(unittest.TestCase):
	def _run_pack(
		self,
		root: Path,
		client: ValidationRuleClient,
		settings: dict[str, object] | None = None,
	) -> dict[str, object]:
		save_local_settings(settings or {"region": "TW"}, root / "settings.json")
		service = ElectronBridgeService(root)
		pack_result = SimpleNamespace(
			tar_path=str(root / "pkg.tar.gz"),
			base_name="pkg",
			report_path=str(root / "report.json"),
			output_dir=str(root / "output"),
			md5="abc",
			success_count=1,
			failure_count=0,
			skipped_count=0,
			report={
				"validation": {"summary": {"error_count": 0, "warning_count": 0}},
				"input": {"region_filter": {}},
				"status": {"validation_status": "passed"},
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
			patch("electron_bridge.ValidationRuleClient", return_value=client),
			patch("electron_bridge.pack_incremental_package_mvp_region_named", return_value=pack_result) as pack,
		):
			service.command_pack({"region": "TW", "test_mode": True}, lambda _event, _data: None)
		return pack.call_args.kwargs["validation_config"]

	def test_remote_rules_override_defaults_and_write_report_metadata(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			effective = effective_rule_set(sample_rule_set(), "TW")
			client = ValidationRuleClient(
				cache=ValidationRuleCache(root / "cache.json"),
				opener=lambda _request, **_kwargs: FakeResponse({"rule_set": effective}),
			)

			config = self._run_pack(root, client, settings={"region": "TW", "backend_url": "http://127.0.0.1:8780"})

		rule_set = config["rule_set"]
		self.assertEqual("remote", rule_set["source"])
		self.assertEqual("aov-main", rule_set["rule_set_id"])
		self.assertEqual("2026.07.27.1", rule_set["version"])
		# 后端规则的 content_checks/path_mappings/whitelist_paths 覆盖内置默认
		self.assertEqual(["skin-sale-window"], [check["id"] for check in config["content_checks"]])
		commit_record = config["commit_record"]
		self.assertEqual(["/CommonIgnored.xml", "/TwIgnored.xml"], commit_record["whitelist_paths"])
		self.assertEqual("TW 活动表", commit_record["path_mappings"][0]["table_name"])
		# 归档契约字段格式（backend_archive_contract_v1）
		self.assertTrue(SAFE_ID_PATTERN.fullmatch(rule_set["rule_set_id"]))
		self.assertTrue(SAFE_ID_PATTERN.fullmatch(rule_set["version"]))
		self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", rule_set["rule_hash"]))
		self.assertTrue(str(rule_set["published_at"]).endswith("Z"))
		self.assertIn(rule_set["region_code"], {"TW", "TH", "VN", "ID"})

	def test_local_switches_overlay_remote_content_checks(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			effective = effective_rule_set(sample_rule_set(), "TW")
			client = ValidationRuleClient(
				cache=ValidationRuleCache(root / "cache.json"),
				opener=lambda _request, **_kwargs: FakeResponse({"rule_set": effective}),
			)

			config = self._run_pack(root, client, settings={
				"region": "TW",
				"backend_url": "http://127.0.0.1:8780",
				"disabled_rule_ids": ["skin-sale-window"],
				"rule_name_overrides": {"skin-sale-window": "皮肤窗口（本地改名）"},
			})

		check = config["content_checks"][0]
		self.assertIs(check["enabled"], False)
		self.assertEqual("皮肤窗口（本地改名）", check["name"])
		self.assertEqual("remote", config["rule_set"]["source"])

	def test_remote_failure_falls_back_to_local_cache(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			cache = ValidationRuleCache(root / "cache.json")
			cache.save(effective_rule_set(sample_rule_set(), "TW"))
			client = ValidationRuleClient(cache=cache, opener=_offline_opener)

			config = self._run_pack(root, client, settings={"region": "TW", "backend_url": "http://127.0.0.1:8780"})

		self.assertEqual("local_cache", config["rule_set"]["source"])
		self.assertEqual("2026.07.27.1", config["rule_set"]["version"])
		self.assertEqual(["skin-sale-window"], [check["id"] for check in config["content_checks"]])

	def test_offline_without_cache_uses_built_in_defaults(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			client = ValidationRuleClient(
				cache=ValidationRuleCache(root / "cache.json"),
				opener=_offline_opener,
			)

			config = self._run_pack(root, client, settings={"region": "TW", "backend_url": "http://127.0.0.1:8780"})

		rule_set = config["rule_set"]
		self.assertEqual("built_in", rule_set["source"])
		self.assertEqual("built-in", rule_set["rule_set_id"])
		self.assertEqual("1", rule_set["version"])
		self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", rule_set["rule_hash"]))
		# 内置规则不覆盖注册表默认 content_checks
		self.assertEqual(
			["hidden-item-tab", "expiry-activity-cross-check", "skin-sale-change-check", "package-completeness-manual"],
			[check["id"] for check in config["content_checks"]],
		)

	def test_missing_backend_url_uses_cache_or_built_in_without_network(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			with patch.dict("os.environ", {"AOV_VALIDATION_RULE_CACHE": str(root / "empty_cache.json")}):
				service = ElectronBridgeService(root)
				load = service._pull_validation_rules({"region": "TW"}, "TW")

		self.assertEqual("built_in", load.source)
		self.assertEqual("built-in", load.rule_set["rule_set_id"])


if __name__ == "__main__":
	unittest.main()
