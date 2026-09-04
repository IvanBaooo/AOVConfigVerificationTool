"""skin_sale_change_check 规则（rules.impl.skin_sale_change）单元测试。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rules.impl.skin_sale_change import run_skin_sale_change_check
from rules_fixtures import (
    SKIN_LISTING_SHEET,
    SKIN_PROMO_SHEET,
    make_config,
    skin_changeset,
    skin_check,
    write_skin_dtxml,
)


class SkinSaleChangeCheckTests(unittest.TestCase):
    def _run(
        self,
        tdr_root: Path,
        entries: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return run_skin_sale_change_check(
            fixed_paths=["Taiwan/Xml/Garena/TW/CommonCore/英雄皮肤促销表.dtxml"],
            local_root=str(tdr_root / "ServerBytes"),
            validation_config=make_config(tdr_root),
            check=skin_check(),
            changeset_changes=None if entries is None else skin_changeset(entries),
        )

    def test_sale_mode_flip_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_skin_dtxml(tdr_root, [])
            before = {"皮肤ID": "13109", "皮肤名称": "好运信使", "是否可点券购买": "否", "点券价格": "9999"}
            after = dict(before, **{"是否可点券购买": "是"})
            result = self._run(tdr_root, [{
                "sheet": SKIN_LISTING_SHEET, "before": before, "after": after,
                "changed_fields": ["是否可点券购买"],
            }])
        self.assertEqual("warning", result["status"])
        self.assertEqual("skin_sale_mode_changed", result["warnings"][0]["type"])
        self.assertIn("是否可点券购买", result["warnings"][0]["change_summary"])

    def test_low_coupon_price_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_skin_dtxml(tdr_root, [])
            before = {"皮肤ID": "13109", "皮肤名称": "好运信使", "是否可点券购买": "是", "点券价格": "588"}
            after = dict(before, **{"点券价格": "60"})
            result = self._run(tdr_root, [{
                "sheet": SKIN_LISTING_SHEET, "before": before, "after": after,
                "changed_fields": ["点券价格"],
            }])
        self.assertEqual("warning", result["status"])
        self.assertEqual("skin_low_price", result["warnings"][0]["type"])

    def test_price_change_above_threshold_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_skin_dtxml(tdr_root, [])
            before = {"皮肤ID": "13109", "皮肤名称": "好运信使", "是否可点券购买": "是", "点券价格": "999"}
            after = dict(before, **{"点券价格": "588"})
            result = self._run(tdr_root, [{
                "sheet": SKIN_LISTING_SHEET, "before": before, "after": after,
                "changed_fields": ["点券价格"],
            }])
        self.assertEqual("passed", result["status"])
        self.assertEqual([], result["warnings"])
        self.assertEqual(1, result["passed_count"])

    def test_listing_added_does_not_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_skin_dtxml(tdr_root, [])
            after = {"皮肤ID": "13109", "皮肤名称": "好运信使", "是否可点券购买": "是", "点券价格": "60"}
            result = self._run(tdr_root, [{
                "sheet": SKIN_LISTING_SHEET, "change_type": "added", "after": after,
            }])
        self.assertEqual("passed", result["status"])
        self.assertEqual([], result["warnings"])
        self.assertEqual([], result["items"])
        self.assertEqual(1, result["passed_count"])

    def test_promo_added_confirm_with_linked_skin_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            # 促销 sheet 的「皮肤ID」引用上下架 sheet 的行 ID（51015），
            # 目录按行 ID 建键后应能关联出皮肤名称。
            write_skin_dtxml(
                tdr_root,
                [{"ID": "51015", "皮肤ID": "13109", "皮肤名称": "安奈特-好运信使", "是否可点券购买": "是"}],
            )
            after = {"促销特卖ID": "510152", "皮肤ID": "51015", "是否可点券购买": "是", "点券价格": "60"}
            result = self._run(tdr_root, [{
                "sheet": SKIN_PROMO_SHEET, "change_type": "added", "after": after,
            }])
        self.assertEqual("confirm", result["status"])
        self.assertEqual([], result["warnings"])
        confirm = result["items"][0]
        self.assertEqual("skin_promo_added", confirm["type"])
        self.assertEqual("安奈特-好运信使", confirm["skin_name"])
        self.assertIn("510152", confirm["message"])

    def test_deleted_row_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_skin_dtxml(tdr_root, [{"ID": "1", "皮肤ID": "13109", "皮肤名称": "好运信使"}])
            before = {"促销特卖ID": "131094", "皮肤ID": "13109", "是否可点券购买": "是"}
            result = self._run(tdr_root, [{
                "sheet": SKIN_PROMO_SHEET, "change_type": "deleted", "before": before,
            }])
        self.assertEqual("warning", result["status"])
        self.assertEqual("skin_row_deleted", result["warnings"][0]["type"])

    def test_no_skin_table_change_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            result = run_skin_sale_change_check(
                fixed_paths=["Taiwan/Databin/Server/Item/SvrItem.bytes"],
                local_root=str(tdr_root / "ServerBytes"),
                validation_config=make_config(tdr_root),
                check=skin_check(),
                changeset_changes=[{
                    "sheet": "道具信息",
                    "file_name": "Item/SvrItem.bytes",
                    "change_type": "modified",
                    "business_key": {"columns": ["ID"], "values": ["1"], "display": "ID=1"},
                }],
            )
        self.assertEqual("skipped", result["status"])
        self.assertEqual("no_skin_table_change", result["reason"])

    def test_changeset_unavailable_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(Path(tmp), None)
        self.assertEqual("skipped", result["status"])
        self.assertEqual("changeset_unavailable", result["reason"])

    def test_registry_dispatch_runs_skin_rule(self) -> None:
        from rules.registry import run_content_check

        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_skin_dtxml(tdr_root, [])
            before = {"皮肤ID": "13109", "皮肤名称": "好运信使", "是否可钻石购买": "否"}
            after = dict(before, **{"是否可钻石购买": "是"})
            result = run_content_check(
                skin_check(),
                fixed_paths=["Taiwan/Xml/Garena/TW/CommonCore/英雄皮肤促销表.dtxml"],
                local_root=str(tdr_root / "ServerBytes"),
                validation_config=make_config(tdr_root),
                changeset_changes=skin_changeset([{
                    "sheet": SKIN_LISTING_SHEET, "before": before, "after": after,
                    "changed_fields": ["是否可钻石购买"],
                }]),
            )
        self.assertEqual("warning", result["status"])
        self.assertEqual("skin-sale-change-check", result["rule_id"])


if __name__ == "__main__":
    unittest.main()
