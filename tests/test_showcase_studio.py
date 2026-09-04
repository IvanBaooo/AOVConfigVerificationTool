from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import showcase_studio as sc
from svn_dtxml_changeset import parse_repository_changed_paths


COMMON_CORE = Path("Xml/Garena/TW/CommonCore")

ITEM_DFXML = (
    '<Root Schema="道具信息表"><Sheet Name="道具信息"><Columns>'
    '<Column Name="ID" /><Column Name="名称" /><Column Name="是否是隐藏道具" />'
    '<Column Name="活动ID" /><Column Name="限时道具有效期" />'
    '</Columns>'
    '<Row><Cell Name="ID">1001</Cell><Cell Name="名称">测试药水</Cell>'
    '<Cell Name="是否是隐藏道具">0</Cell><Cell Name="活动ID"></Cell>'
    '<Cell Name="限时道具有效期"></Cell></Row>'
    '<Row><Cell Name="ID">1002</Cell><Cell Name="名称">演示礼包</Cell>'
    '<Cell Name="是否是隐藏道具">0</Cell><Cell Name="活动ID"></Cell>'
    '<Cell Name="限时道具有效期"></Cell></Row>'
    '</Sheet></Root>'
)

ACTIVITY_DFXML = (
    '<Root Schema="日常活动表"><Sheet Name="日常活动"><Columns>'
    '<Column Name="活动ID" /><Column Name="活动名称" />'
    '<Column Name="开始时间" /><Column Name="结束时间" />'
    '</Columns>'
    '<Row><Cell Name="活动ID">act001</Cell><Cell Name="活动名称">测试活动</Cell>'
    '<Cell Name="开始时间">20260801000000</Cell><Cell Name="结束时间">20260831235959</Cell></Row>'
    '</Sheet></Root>'
)

SKIN_DFXML = (
    '<Root Schema="英雄皮肤促销表">'
    '<Sheet Name="svr下发皮肤上下架表"><Columns>'
    '<Column Name="ID" /><Column Name="皮肤ID" /><Column Name="皮肤名称" />'
    '<Column Name="是否可点券购买" /><Column Name="点券价格" />'
    '</Columns>'
    '<Row><Cell Name="ID">51015</Cell><Cell Name="皮肤ID">15</Cell>'
    '<Cell Name="皮肤名称">演示皮肤</Cell><Cell Name="是否可点券购买">否</Cell>'
    '<Cell Name="点券价格">999</Cell></Row>'
    '</Sheet>'
    '<Sheet Name="svr下发皮肤促销特卖"><Columns>'
    '<Column Name="促销特卖ID" /><Column Name="皮肤ID" />'
    '<Column Name="是否可点券购买" /><Column Name="点券价格" />'
    '</Columns>'
    '<Row><Cell Name="促销特卖ID">510152</Cell><Cell Name="皮肤ID">51015</Cell>'
    '<Cell Name="是否可点券购买">是</Cell><Cell Name="点券价格">588</Cell></Row>'
    '</Sheet>'
    '</Root>'
)


def make_source_tdr(root: Path) -> Path:
    """构造迷你 TdrTable 源目录。"""
    common = root / COMMON_CORE
    common.mkdir(parents=True)
    (common / sc.ITEM_DFXML_NAME).write_text(ITEM_DFXML, encoding="utf-8")
    (common / sc.DAILY_ACTIVITY_NAME).write_text(ACTIVITY_DFXML, encoding="utf-8")
    (common / sc.SKIN_DFXML_NAME).write_text(SKIN_DFXML, encoding="utf-8")
    return root


class ShowcaseWorkspaceTests(unittest.TestCase):
    def test_init_applies_all_scenes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = make_source_tdr(base / "source")
            workspace = base / "showcase"
            result = sc.init_workspace(workspace, source)
            self.assertTrue(result["initialized"])
            self.assertFalse(result["reused"])
            scenes = {s["id"]: s for s in result["scenes"]}
            for scene_id in ("hidden_item", "expiry_conflict", "skin_sale_flip", "skin_low_price", "skin_row_delete", "skin_promo_add"):
                self.assertTrue(scenes[scene_id]["applied"], f"{scene_id}: {scenes[scene_id].get('detail')}")
            # 重复初始化且不 reset → 复用
            again = sc.init_workspace(workspace, source)
            self.assertTrue(again["reused"])

    def test_diff_detects_scene_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = make_source_tdr(base / "source")
            workspace = base / "showcase"
            sc.init_workspace(workspace, source)
            changes = sc.diff_workspace(workspace)
            paths = {change["path"] for change in changes}
            self.assertIn(str(COMMON_CORE / sc.ITEM_DFXML_NAME), paths)
            self.assertIn(str(COMMON_CORE / sc.SKIN_DFXML_NAME), paths)

    def test_synthesized_log_roundtrips(self) -> None:
        changes = [{"action": "M", "path": str(COMMON_CORE / sc.SKIN_DFXML_NAME)}]
        log_text = sc.synthesize_svn_log(changes, current_revision=1738100, baseline_revision=1738000)
        entries = parse_repository_changed_paths(log_text)
        paths = [entry.path for entry in entries]
        # 当前提交的 dtxml + 对应 bytes + 间隔遗漏条目
        self.assertTrue(any("英雄皮肤促销表.dtxml" in p for p in paths))
        self.assertTrue(any("SvrHeroSkinShop.bytes" in p for p in paths))
        self.assertTrue(any("Hero_MD5_Android.txt" in p for p in paths))
        self.assertTrue(any("ResSvr2CltIluaCfg.bytes" in p for p in paths))

    def test_build_changeset_with_local_loader(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = make_source_tdr(base / "source")
            workspace = base / "showcase"
            sc.init_workspace(workspace, source)
            changes = sc.diff_workspace(workspace)
            log_text = sc.synthesize_svn_log(changes, current_revision=1738100, baseline_revision=1738000)
            change_set = sc.build_showcase_changeset(
                workspace, log_text=log_text, current_revision=1738100,
            )
            self.assertIn(change_set["status"], ("passed", "warning"))
            sheets = {c.get("sheet") for c in change_set.get("changes", [])}
            self.assertIn("道具信息", sheets)
            self.assertIn("svr下发皮肤上下架表", sheets)
            self.assertIn("svr下发皮肤促销特卖", sheets)
            # 场景内容真的进了 changeset
            skin_changes = [c for c in change_set["changes"] if c.get("sheet") == "svr下发皮肤上下架表"]
            sale_flip = [c for c in skin_changes if (c.get("after") or {}).get("是否可点券购买") == "是" and (c.get("before") or {}).get("是否可点券购买") == "否"]
            self.assertTrue(sale_flip, "售卖方式翻转未进入 changeset")


class ShowcaseRowEditorTests(unittest.TestCase):
    def _workspace(self, base: Path) -> Path:
        source = make_source_tdr(base / "source")
        workspace = base / "showcase"
        sc.init_workspace(workspace, source)
        return workspace

    def test_tables_and_sheets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(Path(tmp))
            tables = sc.list_tables(workspace)
            names = {t["file_name"] for t in tables}
            self.assertIn(sc.SKIN_DFXML_NAME, names)
            sheets = sc.list_sheets(workspace, sc.SKIN_DFXML_NAME)
            sheet_names = {s["name"] for s in sheets}
            self.assertIn("svr下发皮肤上下架表", sheet_names)
            self.assertIn("svr下发皮肤促销特卖", sheet_names)

    def test_list_rows_and_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(Path(tmp))
            result = sc.list_rows(workspace, sc.ITEM_DFXML_NAME, "道具信息")
            self.assertEqual(2, result["total"])
            filtered = sc.list_rows(workspace, sc.ITEM_DFXML_NAME, "道具信息", keyword="测试药水")
            self.assertEqual(1, filtered["total"])
            self.assertEqual("1001", filtered["rows"][0]["key"])

    def test_update_row_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(Path(tmp))
            sc.update_row(workspace, sc.ITEM_DFXML_NAME, "道具信息", 1, {"名称": "改名礼包", "是否是隐藏道具": "1"})
            result = sc.list_rows(workspace, sc.ITEM_DFXML_NAME, "道具信息", keyword="改名礼包")
            self.assertEqual(1, result["total"])
            self.assertEqual("1", result["rows"][0]["cells"]["是否是隐藏道具"])

    def test_add_and_delete_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(Path(tmp))
            before = sc.list_rows(workspace, sc.SKIN_DFXML_NAME, "svr下发皮肤促销特卖")["total"]
            added = sc.add_row(workspace, sc.SKIN_DFXML_NAME, "svr下发皮肤促销特卖", 0)
            after_add = sc.list_rows(workspace, sc.SKIN_DFXML_NAME, "svr下发皮肤促销特卖")["total"]
            self.assertEqual(before + 1, after_add)
            sc.delete_row(workspace, sc.SKIN_DFXML_NAME, "svr下发皮肤促销特卖", added["row_index"])
            after_del = sc.list_rows(workspace, sc.SKIN_DFXML_NAME, "svr下发皮肤促销特卖")["total"]
            self.assertEqual(before, after_del)

    def test_path_escape_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(Path(tmp))
            with self.assertRaises(ValueError):
                sc.list_rows(workspace, "../../../etc/passwd", "x")
            with self.assertRaises(ValueError):
                sc.list_rows(workspace, "不存在的表.dtxml", "x")


if __name__ == "__main__":
    unittest.main()
