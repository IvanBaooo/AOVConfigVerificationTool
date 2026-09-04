"""expiry_time_cross_check 规则（rules.impl.expiry_cross_check）单元测试。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rules.impl.expiry_cross_check import run_expiry_cross_check
from rules.registry import default_incident_content_checks
from rules_fixtures import (
    ITEM_TOUCH_PATHS,
    make_changeset,
    make_config,
    write_item_dtxml,
)


class ExpiryCrossCheckTests(unittest.TestCase):
    def _run(self, rows: list[dict[str, str]], windows: dict[str, object]) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_item_dtxml(tdr_root, rows)
            return run_expiry_cross_check(
                fixed_paths=ITEM_TOUCH_PATHS,
                local_root=str(tdr_root / "ServerBytes"),
                validation_config=make_config(tdr_root, activity_windows=windows),
                check=default_incident_content_checks()[1],
                changeset_changes=make_changeset(*[str(row["ID"]) for row in rows]),
            )

    def test_expiry_before_activity_start_warns(self) -> None:
        result = self._run(
            [{"ID": "30001", "名称": "隐形token", "活动ID": "act1", "限时道具有效期": "20260515000000"}],
            {"act1": {"start_time": "20260515000000", "end_time": "20260615000000"}},
        )
        self.assertEqual("warning", result["status"])
        warning = result["warnings"][0]
        self.assertEqual("expiry_before_activity_start", warning["type"])
        self.assertEqual("30001", warning["item_id"])
        self.assertEqual("act1", warning["activity_id"])
        self.assertTrue(warning["suggestion"])

    def test_expiry_within_activity_window_warns(self) -> None:
        result = self._run(
            [{"ID": "30002", "名称": "道具", "活动ID": "act1", "限时道具有效期": "20260601000000"}],
            {"act1": {"start_time": "20260515000000", "end_time": "20260615000000"}},
        )
        self.assertEqual("warning", result["status"])
        self.assertEqual("expiry_within_activity_window", result["warnings"][0]["type"])

    def test_expiry_empty_or_after_end_passes(self) -> None:
        result = self._run(
            [
                {"ID": "30003", "名称": "无有效期", "活动ID": "act1", "限时道具有效期": ""},
                {"ID": "30004", "名称": "晚于结束", "活动ID": "act1", "限时道具有效期": "20260701000000"},
            ],
            {"act1": {"start_time": "20260515000000", "end_time": "20260615000000"}},
        )
        self.assertEqual("passed", result["status"])
        self.assertEqual(1, result["checked_count"])

    def test_missing_activity_window_goes_to_manual_confirm(self) -> None:
        result = self._run(
            [{"ID": "30005", "名称": "道具", "活动ID": "actX", "限时道具有效期": "20260601000000"}],
            {},
        )
        self.assertEqual("confirm", result["status"])
        self.assertEqual("expiry_activity_unknown", result["items"][0]["type"])

    def test_changeset_deleted_rows_are_skipped_and_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_item_dtxml(tdr_root, [
                {"ID": "30005", "名称": "道具", "活动ID": "actX", "限时道具有效期": "20260601000000"},
            ])
            deleted_changeset = [
                {
                    "sheet": "道具信息",
                    "file_name": "Item/SvrItem.bytes",
                    "change_type": "deleted",
                    "business_key": {"columns": ["ID"], "values": ["30005"], "display": "ID=30005"},
                }
            ]
            result = run_expiry_cross_check(
                fixed_paths=ITEM_TOUCH_PATHS,
                local_root=str(tdr_root / "ServerBytes"),
                validation_config=make_config(tdr_root, activity_windows={}),
                check=default_incident_content_checks()[1],
                changeset_changes=deleted_changeset,
            )
        self.assertEqual("passed", result["status"])
        self.assertEqual("changeset", result["scope"])
        self.assertEqual(0, result["checked_count"])


class ModuleChainExpiryTests(unittest.TestCase):
    """规则 2 经 module 关联链取活动起止时间：历史提交配置的活动也能自动判定。"""

    def _run(self, limited_hours: str, windows: dict[str, object] | None = None) -> dict[str, object]:
        from test_changeset_modules import write_item_business_fixture

        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_item_business_fixture(tdr_root, limited_hours=limited_hours)
            return run_expiry_cross_check(
                fixed_paths=ITEM_TOUCH_PATHS,
                local_root=str(tdr_root / "ServerBytes"),
                validation_config=make_config(tdr_root, activity_windows=windows or {}),
                check=default_incident_content_checks()[1],
                changeset_changes=make_changeset("5001"),
            )

    def test_module_chain_resolves_times_and_warns_within_window(self) -> None:
        # 有效期 2026-08-05 落在活动 600/601/602/700（08-01 至 08-07）期间内
        result = self._run("20260805000000")
        self.assertEqual("warning", result["status"])
        self.assertEqual("module_index", result["activity_resolution"])
        warning = result["warnings"][0]
        self.assertEqual("5001", warning["item_id"])
        self.assertTrue(warning["activities"])
        self.assertIn("600", [act["activity_id"] for act in warning["activities"]])

    def test_module_chain_passes_when_expiry_after_all_activities(self) -> None:
        # 有效期晚于所有关联活动结束时间 → 无需人工排期表也通过
        result = self._run("20260810000000")
        self.assertEqual("passed", result["status"])
        self.assertEqual(1, result["checked_count"])
        # 通过的道具也应被记录到 passed_items，供前端折叠展示
        self.assertEqual(1, len(result["passed_items"]))
        self.assertEqual("5001", result["passed_items"][0]["item_id"])
        self.assertTrue(result["passed_items"][0]["activities"])

    def test_manual_windows_still_cover_unlinked_items(self) -> None:
        # module 链找不到时，人工排期表兜底：道具行带活动ID=actManual
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_item_dtxml(tdr_root, [
                {"ID": "90001", "名称": "道具", "活动ID": "actManual", "限时道具有效期": "20260601000000"},
            ])
            result = run_expiry_cross_check(
                fixed_paths=ITEM_TOUCH_PATHS,
                local_root=str(tdr_root / "ServerBytes"),
                validation_config=make_config(
                    tdr_root,
                    activity_windows={"actManual": {"start_time": "20260515000000", "end_time": "20260615000000"}},
                ),
                check=default_incident_content_checks()[1],
                changeset_changes=make_changeset("90001"),
            )
        self.assertEqual("warning", result["status"])
        self.assertEqual("expiry_within_activity_window", result["warnings"][0]["type"])
        self.assertEqual("actManual", result["warnings"][0]["activity_id"])


if __name__ == "__main__":
    unittest.main()
