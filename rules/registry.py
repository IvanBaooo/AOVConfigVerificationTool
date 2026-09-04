"""内容校验规则注册表（Rule Registry）。

所有「03 规则校验」区块的内容校验规则都在这里注册。新增规则只需：
1. 实现一个 runner 函数（签名见文件底部说明）
2. 在 _RULE_SPECS 里加一条 spec

调度、默认规则列表、设置页开关、前端通用渲染全部从本注册表自动派生。

注意：若新增规则的 type 不在 rules.sets.SUPPORTED_CONTENT_CHECK_TYPES
白名单内，且希望归档后端能下发该规则配置，需要同步在白名单中补充该 type。
"""
from __future__ import annotations

import importlib
import inspect
from typing import Callable, Dict, List, Mapping, Optional


# ---------------------------------------------------------------------------
# 规则 spec 字段说明
# ---------------------------------------------------------------------------
# id              规则唯一 ID（规则集/设置开关/报告均以此对齐）
# type            规则类型（结果 dict 在 validation.checks 里的 key）
# name            展示名（前端规则行标题、设置页开关标题）
# description     设置页开关下的说明文字
# default_enabled 默认是否启用（用户可在设置页覆盖，见 disabled_rule_ids）
# scope           调度时机：
#                 "changeset" —— changeset 驱动，只对提交内容校验
#                              （在 validation_mvp.run_mvp_validations 中调度）
#                 "package"   —— 包级校验，需要打包结果
#                              （在 validation_full_mvp_optimized 中调度）
# tables          可读表名归因（供"哪个表出问题最多"统计），
#                 调度时随 id/name 一并注入规则结果 dict
# trigger_paths   触发路径（写入 content_checks，供规则集覆盖）
# applies_to      可选，适用场景标注（如 manual_bytes_list_only）
# params          可选，默认参数（写入 content_checks）
# runner          "module:function" 懒加载引用，避免模块间循环依赖
# detail_columns  可选，前端通用明细表的列声明 [{"key", "label"}]；
#                 未声明时前端按结果 items 第一条的键自动推导

_RULE_SPECS: List[Dict[str, object]] = [
    {
        "id": "hidden-item-tab",
        "type": "hidden_item_listing",
        "name": "隐藏道具识别与单独标注",
        "description": "识别本次变更中「是否是隐藏道具」为真的道具行，提示与 QA 同步确认。",
        "default_enabled": True,
        "scope": "changeset",
        "tables": ["道具信息表"],
        "trigger_paths": [
            "/Databin/Server/Item/SvrItem.bytes",
            "/Databin/Server/Item/SvrItem.xml",
            "/Databin/Server/Ilua/",
        ],
        "runner": "rules.impl.hidden_item:run_hidden_item_listing",
        "detail_columns": [
            {"key": "item_id", "label": "道具 ID"},
            {"key": "name", "label": "名称"},
            {"key": "linked_activity", "label": "关联活动"},
            {"key": "expire_time", "label": "expire_time"},
        ],
    },
    {
        "id": "expiry-activity-cross-check",
        "type": "expiry_time_cross_check",
        "name": "道具有效期与活动时间关联校验",
        "description": "变更道具的有效期与关联活动起止时间比对：早于活动开始或落在活动期间内告警，"
                       "晚于活动结束自动通过，找不到关联活动转人工核对。",
        "default_enabled": True,
        "scope": "changeset",
        "tables": ["道具信息表", "活动表"],
        "trigger_paths": [
            "/Databin/Server/Item/SvrItem.bytes",
            "/Databin/Server/Item/SvrItem.xml",
            "/Databin/Server/Shop/",
            "/Databin/Server/Ilua/",
        ],
        "runner": "rules.impl.expiry_cross_check:run_expiry_cross_check",
        "detail_columns": [
            {"key": "item_id", "label": "道具 ID"},
            {"key": "name", "label": "名称"},
            {"key": "expire_time", "label": "expire_time"},
            {"key": "message", "label": "结论"},
        ],
    },
    {
        "id": "skin-sale-change-check",
        "type": "skin_sale_change_check",
        "name": "皮肤售卖方式变更校验",
        "description": "皮肤上下架/促销表变更驱动：售卖方式（点券/皮肤点/钻石/混合支付）任一翻转告警；"
                       "点券价格改为低于 100 告警；删行告警；新增促销转人工确认并关联皮肤；"
                       "新增皮肤上架不告警。",
        "default_enabled": True,
        "scope": "changeset",
        "tables": ["英雄皮肤促销表"],
        "trigger_paths": [
            "/Xml/Garena/{region}/CommonCore/英雄皮肤促销表.dtxml",
            "/Databin/Server/Shop/SvrHeroSkinShop.xml",
            "/Databin/Server/Shop/SvrHeroSkinShop.bytes",
        ],
        "params": {"low_price_threshold": 100},
        "runner": "rules.impl.skin_sale_change:run_skin_sale_change_check",
        "detail_columns": [
            {"key": "skin_id", "label": "皮肤 ID"},
            {"key": "skin_name", "label": "皮肤名称"},
            {"key": "sheet", "label": "来源表"},
            {"key": "change_summary", "label": "变化明细"},
            {"key": "message", "label": "结论"},
        ],
    },
    {
        "id": "package-completeness-manual",
        "type": "package_completeness",
        "name": "输入清单与包内容一一对应（仅手动bytes list场景）",
        "description": "文件列表模式下核对输入清单与包内容一一对应，防空包/漏打；"
                       "SVN 提交模式由提交校验覆盖，自动跳过。",
        "default_enabled": True,
        "scope": "package",
        "tables": ["（包级）"],
        "trigger_paths": ["*"],
        "applies_to": "manual_bytes_list_only",
        "params": {"min_file_count": 1, "min_total_bytes": 1024},
        "runner": "rules.impl.package_completeness:run_package_completeness",
        "detail_columns": [],
    },
]


def all_rule_specs() -> List[Dict[str, object]]:
    """全部注册规则的元数据（不含 runner 引用）。"""
    return [{k: v for k, v in spec.items() if k != "runner"} for spec in _RULE_SPECS]


def spec_for_type(check_type: object) -> Optional[Dict[str, object]]:
    """按 type 查 spec；未注册返回 None。"""
    for spec in _RULE_SPECS:
        if spec["type"] == check_type:
            return spec
    return None


def registered_check_types() -> List[str]:
    """已注册的规则 type 列表（与 rules.sets 白名单对齐用）。"""
    return [str(spec["type"]) for spec in _RULE_SPECS]


def default_content_checks() -> List[Dict[str, object]]:
    """由注册表生成默认 content_checks（替代手工维护的默认列表）。"""
    checks: List[Dict[str, object]] = []
    for spec in _RULE_SPECS:
        check: Dict[str, object] = {
            "id": spec["id"],
            "type": spec["type"],
            "enabled": bool(spec.get("default_enabled", True)),
            "name": spec["name"],
            "trigger_paths": list(spec.get("trigger_paths") or []),
        }
        if spec.get("applies_to"):
            check["applies_to"] = spec["applies_to"]
        if spec.get("params"):
            check["params"] = dict(spec["params"])  # type: ignore[arg-type]
        checks.append(check)
    return checks


def default_incident_content_checks() -> List[Dict[str, object]]:
    """内置默认开启的道具校验规则（可被规则集同名 id 覆盖）。

    由注册表派生；新增规则请改注册表，不要改这里。
    """
    return default_content_checks()


def apply_disabled_rules(
    content_checks: List[Dict[str, object]],
    disabled_rule_ids: object,
) -> List[Dict[str, object]]:
    """叠加用户本地开关：disabled_rule_ids 命中的规则置 enabled=False。

    只影响本地这次打包；规则集下发/默认值不变（后端默认、本地叠加原则）。
    """
    if not isinstance(disabled_rule_ids, (list, tuple)):
        return content_checks
    disabled = {str(item) for item in disabled_rule_ids}
    if not disabled:
        return content_checks
    result: List[Dict[str, object]] = []
    for check in content_checks:
        entry = dict(check)
        if str(entry.get("id")) in disabled:
            entry["enabled"] = False
        result.append(entry)
    return result


def _resolve_runner(spec: Mapping[str, object]) -> Callable[..., Dict[str, object]]:
    ref = str(spec.get("runner") or "")
    module_name, _, func_name = ref.partition(":")
    if not module_name or not func_name:
        raise ValueError(f"规则 {spec.get('id')} 未配置 runner")
    module = importlib.import_module(module_name)
    runner = getattr(module, func_name, None)
    if not callable(runner):
        raise ValueError(f"规则 {spec.get('id')} 的 runner 不可调用：{ref}")
    return runner


def run_content_check(check: Mapping[str, object], **context: object) -> Dict[str, object]:
    """注册表驱动的规则调度。

    按 check["type"] 找 spec，懒加载 runner，并按 runner 的实际签名
    从 context 中筛选所需参数传入（不同 runner 的参数集可以不同）。
    runner 返回后把 spec 的 id/name（可被 check["name"] 覆盖）/tables
    注入结果 dict，供归档契约与前端统计归因。

    context 约定可包含：fixed_paths, local_root, validation_config,
    changeset_changes, module_context, package_files。
    """
    spec = spec_for_type(check.get("type"))
    if spec is None:
        return {
            "status": "skipped",
            "reason": "unknown_check_type",
            "message": f"未注册的规则类型：{check.get('type')}",
            "items": [],
            "warnings": [],
        }
    runner = _resolve_runner(spec)
    accepted = inspect.signature(runner).parameters
    kwargs = {key: value for key, value in context.items() if key in accepted}
    kwargs["check"] = check
    result = runner(**kwargs)
    result["id"] = spec["id"]
    result["name"] = str(check.get("name") or spec.get("name") or spec["type"])
    result["tables"] = list(spec.get("tables") or [])
    return result


def apply_rule_name_overrides(
    content_checks: List[Dict[str, object]],
    overrides: object,
) -> List[Dict[str, object]]:
    """叠加本地重命名：rule_name_overrides = {规则id: 自定义名}，只改展示名。"""
    if not isinstance(overrides, Mapping) or not overrides:
        return content_checks
    result: List[Dict[str, object]] = []
    for check in content_checks:
        entry = dict(check)
        custom = overrides.get(str(entry.get("id")))
        if isinstance(custom, str) and custom.strip():
            entry["name"] = custom.strip()
        result.append(entry)
    return result
