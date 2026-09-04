"""注册表规则的 schema 与管道集成测试。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rules.sets import validate_rule_set
from rules_fixtures import (
    FIXTURE_PATH,
    ITEM_TOUCH_PATHS,
    make_changeset,
    make_config,
    write_item_dtxml,
)
from validation_full_mvp_optimized import run_full_mvp_validations_optimized
from validation_mvp import run_mvp_validations


class IncidentRuleSetSchemaTests(unittest.TestCase):
    def test_incident_fixture_content_checks_are_accepted(self) -> None:
        doc = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        rule_set = {
            "schema_version": "1.0",
            "rule_set_id": "aov-incident-derived",
            "version": "2026.08.26.1",
            "published_at": "2026-08-26T11:56:00Z",
            "notes": "incident derived",
            "common": {
                "path_mappings": [],
                "whitelist_paths": [],
                "content_checks": doc["common"]["content_checks"],
            },
        }
        validated = validate_rule_set(rule_set)
        checks = validated["common"]["content_checks"]
        self.assertEqual(
            ["hidden-item-tab", "expiry-activity-cross-check", "package-completeness-manual"],
            [check["id"] for check in checks],
        )
        self.assertEqual(
            ["hidden_item_listing", "expiry_time_cross_check", "package_completeness"],
            [check["type"] for check in checks],
        )

    def test_unknown_check_type_is_rejected(self) -> None:
        rule_set = {
            "schema_version": "1.0",
            "rule_set_id": "demo",
            "version": "1",
            "published_at": "2026-08-26T11:56:00Z",
            "common": {
                "content_checks": [{
                    "id": "bad",
                    "type": "item_id_uniqueness",
                    "enabled": True,
                    "name": "已被移除的规则",
                    "trigger_paths": ["/x"],
                }],
            },
        }
        with self.assertRaises(Exception):
            validate_rule_set(rule_set)


class IncidentRuleIntegrationTests(unittest.TestCase):
    def test_run_mvp_validations_includes_incident_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_item_dtxml(tdr_root, [
                {"ID": "11018381", "名称": "隐藏", "是否是隐藏道具": "1"},
            ])
            result = run_mvp_validations(
                fixed_paths=ITEM_TOUCH_PATHS,
                local_root=str(tdr_root / "ServerBytes"),
                validation_config=make_config(tdr_root),
                changeset_changes=make_changeset("11018381"),
            )
        self.assertIn("hidden_item_listing", result["checks"])
        self.assertIn("expiry_time_cross_check", result["checks"])
        self.assertEqual("warning", result["checks"]["hidden_item_listing"]["status"])
        self.assertGreaterEqual(result["summary"]["warning_count"], 1)

    def test_run_mvp_validations_without_content_checks_keeps_legacy_shape(self) -> None:
        result = run_mvp_validations(
            fixed_paths=ITEM_TOUCH_PATHS,
            local_root="/nonexistent",
            validation_config=None,
        )
        self.assertEqual({"skin_precheck"}, set(result["checks"]))
        self.assertEqual(1, result["summary"]["skipped_count"])

    def test_full_validations_run_completeness_in_manual_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_item_dtxml(tdr_root, [{"ID": "20001", "名称": "普通道具", "是否是隐藏道具": "0"}])
            config = make_config(tdr_root)
            config["commit_record"] = {"enabled": True, "input_method": "pasted_svn_file_list"}
            result = run_full_mvp_validations_optimized(
                fixed_paths=ITEM_TOUCH_PATHS,
                local_root=str(tdr_root / "ServerBytes"),
                validation_config=config,
                package_files=[{"fixed_path": "/Taiwan/Databin/Server/Item/SvrItem.bytes", "status": "packaged", "size": 2048}],
            )
        self.assertIn("package_completeness", result["checks"])
        self.assertEqual("passed", result["checks"]["package_completeness"]["status"])

    def test_validation_alerts_do_not_block_packaging(self) -> None:
        # 爆红告警只体现在状态与计数上：告警类状态不含 error，can_archive 语义不受影响。
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_item_dtxml(tdr_root, [
                {"ID": "11018381", "名称": "隐藏", "是否是隐藏道具": "1", "活动ID": "act1", "限时道具有效期": "20260515000000"},
            ])
            result = run_mvp_validations(
                fixed_paths=ITEM_TOUCH_PATHS,
                local_root=str(tdr_root / "ServerBytes"),
                validation_config=make_config(
                    tdr_root,
                    activity_windows={"act1": {"start_time": "20260515000000", "end_time": "20260615000000"}},
                ),
                changeset_changes=make_changeset("11018381"),
            )
        self.assertEqual(0, result["summary"]["error_count"])
        self.assertGreaterEqual(result["summary"]["warning_count"], 2)


if __name__ == "__main__":
    unittest.main()
