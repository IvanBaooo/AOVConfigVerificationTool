"""rules.registry 注册表与调度的单元测试。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rules.registry import (
    _RULE_SPECS,
    _resolve_runner,
    all_rule_specs,
    apply_disabled_rules,
    apply_rule_name_overrides,
    default_content_checks,
    registered_check_types,
    run_content_check,
    spec_for_type,
)
from rules_fixtures import (
    ITEM_TOUCH_PATHS,
    make_changeset,
    make_config,
    write_item_dtxml,
)


class RegistryMetadataTests(unittest.TestCase):
    def test_all_specs_have_required_fields(self) -> None:
        required = {"id", "type", "name", "description", "default_enabled", "scope", "tables", "trigger_paths"}
        for spec in _RULE_SPECS:
            self.assertTrue(required <= set(spec), f"{spec.get('id')} 缺字段: {required - set(spec)}")
            self.assertIn(spec["scope"], ("changeset", "package"))
            self.assertIn(":", str(spec["runner"]))
            self.assertTrue(all(isinstance(t, str) and t for t in spec["tables"]))

    def test_ids_and_types_unique(self) -> None:
        ids = [spec["id"] for spec in _RULE_SPECS]
        types = [spec["type"] for spec in _RULE_SPECS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(types), len(set(types)))

    def test_runners_resolvable(self) -> None:
        for spec in _RULE_SPECS:
            self.assertTrue(callable(_resolve_runner(spec)))

    def test_metadata_excludes_runner(self) -> None:
        for spec in all_rule_specs():
            self.assertNotIn("runner", spec)

    def test_spec_for_type_unknown_returns_none(self) -> None:
        self.assertIsNone(spec_for_type("no_such_type"))


class DefaultContentChecksTests(unittest.TestCase):
    def test_generated_from_registry(self) -> None:
        checks = default_content_checks()
        self.assertEqual([s["id"] for s in _RULE_SPECS], [c["id"] for c in checks])
        for check in checks:
            self.assertIn(check["type"], registered_check_types())
            self.assertIs(check["enabled"], True)
            self.assertTrue(check["trigger_paths"])

    def test_apply_disabled_rules(self) -> None:
        checks = default_content_checks()
        out = apply_disabled_rules(checks, ["expiry-activity-cross-check"])
        by_id = {c["id"]: c for c in out}
        self.assertIs(by_id["expiry-activity-cross-check"]["enabled"], False)
        self.assertIs(by_id["hidden-item-tab"]["enabled"], True)
        # 原列表不被修改
        self.assertIs(checks[1]["enabled"], True)

    def test_apply_disabled_rules_ignores_invalid_input(self) -> None:
        checks = default_content_checks()
        self.assertIs(apply_disabled_rules(checks, None), checks)
        self.assertIs(apply_disabled_rules(checks, "not-a-list"), checks)
        out = apply_disabled_rules(checks, ["unknown-id"])
        self.assertTrue(all(c["enabled"] for c in out))

    def test_apply_rule_name_overrides(self) -> None:
        checks = default_content_checks()
        out = apply_rule_name_overrides(checks, {"hidden-item-tab": "隐藏道具检查", "blank": "  "})
        by_id = {c["id"]: c for c in out}
        self.assertEqual("隐藏道具检查", by_id["hidden-item-tab"]["name"])
        # 空白覆盖不生效，其他规则名不变
        self.assertNotEqual("  ", by_id["expiry-activity-cross-check"]["name"])
        # 非 dict 输入原样返回
        self.assertIs(apply_rule_name_overrides(checks, None), checks)


class RegistryDispatchTests(unittest.TestCase):
    def test_unknown_type_skipped(self) -> None:
        result = run_content_check({"type": "no_such_type", "id": "x"})
        self.assertEqual("skipped", result["status"])
        self.assertEqual("unknown_check_type", result["reason"])

    def test_dispatch_filters_context_by_runner_signature(self) -> None:
        # hidden runner 不接受 package_files/module_context，调度器应按签名剔除
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_item_dtxml(tdr_root, [
                {"ID": "90001", "名称": "测试道具", "是否是隐藏道具": "1"},
            ])
            check = next(c for c in default_content_checks() if c["type"] == "hidden_item_listing")
            result = run_content_check(
                check,
                fixed_paths=ITEM_TOUCH_PATHS,
                local_root=str(tdr_root / "ServerBytes"),
                validation_config=make_config(tdr_root),
                changeset_changes=make_changeset("90001"),
                module_context=None,   # 多余参数应被剔除
                package_files=[],      # 多余参数应被剔除
            )
        self.assertEqual("warning", result["status"])
        self.assertEqual(1, result["item_count"])

    def test_dispatch_injects_spec_identity_and_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_item_dtxml(tdr_root, [
                {"ID": "90001", "名称": "测试道具", "是否是隐藏道具": "1"},
            ])
            check = next(c for c in default_content_checks() if c["type"] == "hidden_item_listing")
            result = run_content_check(
                check,
                fixed_paths=ITEM_TOUCH_PATHS,
                local_root=str(tdr_root / "ServerBytes"),
                validation_config=make_config(tdr_root),
                changeset_changes=make_changeset("90001"),
            )
        self.assertEqual("hidden-item-tab", result["id"])
        self.assertEqual("隐藏道具识别与单独标注", result["name"])
        self.assertEqual(["道具信息表"], result["tables"])

    def test_dispatch_prefers_check_name_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdr_root = Path(tmp)
            write_item_dtxml(tdr_root, [
                {"ID": "90001", "名称": "测试道具", "是否是隐藏道具": "1"},
            ])
            check = next(c for c in default_content_checks() if c["type"] == "hidden_item_listing")
            renamed = apply_rule_name_overrides([check], {"hidden-item-tab": "自定义隐藏道具检查"})[0]
            result = run_content_check(
                renamed,
                fixed_paths=ITEM_TOUCH_PATHS,
                local_root=str(tdr_root / "ServerBytes"),
                validation_config=make_config(tdr_root),
                changeset_changes=make_changeset("90001"),
            )
        self.assertEqual("自定义隐藏道具检查", result["name"])


if __name__ == "__main__":
    unittest.main()
