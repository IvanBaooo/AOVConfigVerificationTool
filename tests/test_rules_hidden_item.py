"""hidden_item_listing 规则（rules.impl.hidden_item）单元测试。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rules.impl.hidden_item import run_hidden_item_listing
from rules.registry import default_incident_content_checks
from rules_fixtures import (
    ITEM_TOUCH_PATHS,
    make_changeset,
    make_config,
    write_item_dtxml,
)


class HiddenItemListingTests(unittest.TestCase):
    def test_hidden_items_produce_warning_and_tab_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_item_dtxml(tdr_root, [
                {"ID": "11018381", "名称": "儲值送活動道具", "是否是隐藏道具": "1", "活动ID": "act1001", "限时道具有效期": ""},
                {"ID": "20001", "名称": "普通道具", "是否是隐藏道具": "0"},
            ])
            result = run_hidden_item_listing(
                fixed_paths=ITEM_TOUCH_PATHS,
                local_root=str(tdr_root / "ServerBytes"),
                validation_config=make_config(tdr_root),
                check=default_incident_content_checks()[0],
                changeset_changes=make_changeset("11018381"),
            )
        self.assertEqual("warning", result["status"])
        self.assertEqual("隐藏道具", result["display_tab"])
        self.assertEqual(1, result["item_count"])
        self.assertEqual("11018381", result["items"][0]["item_id"])
        self.assertEqual("act1001", result["items"][0]["linked_activity"])
        self.assertIn("请与 QA 同步确认", result["warnings"][0]["message"])

    def test_no_hidden_items_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_item_dtxml(tdr_root, [{"ID": "20001", "名称": "普通道具", "是否是隐藏道具": "0"}])
            result = run_hidden_item_listing(
                fixed_paths=ITEM_TOUCH_PATHS,
                local_root=str(tdr_root / "ServerBytes"),
                validation_config=make_config(tdr_root),
                check=default_incident_content_checks()[0],
                changeset_changes=make_changeset("20001"),
            )
        self.assertEqual("passed", result["status"])
        self.assertEqual([], result["warnings"])

    def test_missing_changeset_skips(self) -> None:
        result = run_hidden_item_listing(
            fixed_paths=["Taiwan/Databin/Server/Actor/Hero.bytes"],
            local_root="/nonexistent",
            validation_config={"region_code": "TW"},
            check=default_incident_content_checks()[0],
        )
        self.assertEqual("skipped", result["status"])
        self.assertEqual("changeset_unavailable", result["reason"])


class HiddenItemChangesetScopeTests(unittest.TestCase):
    def test_changeset_scopes_hidden_check_to_changed_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_item_dtxml(tdr_root, [
                {"ID": "11018381", "名称": "隐藏道具A", "是否是隐藏道具": "1"},
                {"ID": "11018417", "名称": "隐藏道具B", "是否是隐藏道具": "1"},
            ])
            result = run_hidden_item_listing(
                fixed_paths=ITEM_TOUCH_PATHS,
                local_root=str(tdr_root / "ServerBytes"),
                validation_config=make_config(tdr_root),
                check=default_incident_content_checks()[0],
                changeset_changes=make_changeset("11018417"),
            )
        self.assertEqual("changeset", result["scope"])
        self.assertEqual(1, result["item_count"])
        self.assertEqual("11018417", result["items"][0]["item_id"])

    def test_changeset_without_item_table_change_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_item_dtxml(tdr_root, [{"ID": "11018381", "名称": "隐藏道具", "是否是隐藏道具": "1"}])
            result = run_hidden_item_listing(
                fixed_paths=ITEM_TOUCH_PATHS,
                local_root=str(tdr_root / "ServerBytes"),
                validation_config=make_config(tdr_root),
                check=default_incident_content_checks()[0],
                changeset_changes=[{
                    "sheet": "英雄信息",
                    "file_name": "Actor/Hero.bytes",
                    "change_type": "modified",
                    "business_key": {"columns": ["ID"], "values": ["123"], "display": "ID=123"},
                }],
            )
        self.assertEqual("skipped", result["status"])
        self.assertEqual("no_item_table_change", result["reason"])
        self.assertEqual("changeset", result["scope"])

    def test_fallback_without_changeset_skips_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_item_dtxml(tdr_root, [
                {"ID": "11018381", "名称": "隐藏道具A", "是否是隐藏道具": "1"},
                {"ID": "11018417", "名称": "隐藏道具B", "是否是隐藏道具": "1"},
            ])
            result = run_hidden_item_listing(
                fixed_paths=ITEM_TOUCH_PATHS,
                local_root=str(tdr_root / "ServerBytes"),
                validation_config=make_config(tdr_root),
                check=default_incident_content_checks()[0],
                changeset_changes=None,
            )
        # 只校验提交内容：changeset 不可用时不扫描整个文件，直接跳过。
        self.assertEqual("skipped", result["status"])
        self.assertEqual("changeset_unavailable", result["reason"])


if __name__ == "__main__":
    unittest.main()
