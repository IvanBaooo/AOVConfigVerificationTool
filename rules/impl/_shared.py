"""道具类规则（hidden_item / expiry_cross_check）的共享常量与前置 helper。

规则来源：`_incident_analysis/incident_derived_rules.json`（2026-08-26 修订）。
全局约定：时间一律按服务器时间直接比较，不做时区校验；所有规则只产生
warning / confirm，不阻断打包流程。
"""
from __future__ import annotations

import glob
import os
from typing import Dict, List, Mapping, Optional, Tuple

from validation_mvp import (
    infer_region_code,
    infer_tdr_root_from_serverbytes,
    read_dtxml_sheet,
    resolve_rule_dtxml_path,
)


ITEM_TABLE_SHEET = "道具信息"
ITEM_ID_COLUMN = "ID"
ITEM_NAME_COLUMN = "名称"
ITEM_HIDDEN_COLUMN = "是否是隐藏道具"
ITEM_ACTIVITY_ID_COLUMN = "活动ID"
ITEM_EXPIRY_COLUMN = "限时道具有效期"
ITEM_EXPIRY_FALLBACK_COLUMNS = ("可使用结束日期",)

DEFAULT_HIDDEN_ITEM_TRIGGERS = [
    "/Databin/Server/Item/SvrItem.bytes",
    "/Databin/Server/Item/SvrItem.xml",
    "/Databin/Server/Ilua/",
]
DEFAULT_EXPIRY_TRIGGERS = [
    "/Databin/Server/Item/SvrItem.bytes",
    "/Databin/Server/Item/SvrItem.xml",
    "/Databin/Server/Shop/",
    "/Databin/Server/Ilua/",
]

ITEM_DFXML_GLOB = os.path.join("Xml", "Garena", "*", "CommonCore", "*道具信息表*.dtxml")

TRUTHY_VALUES = {"1", "true", "yes", "y", "是", "TRUE", "True"}
EMPTY_VALUES = {"", "0", "0x0"}

ITEM_TABLE_FILE_MARKER = "道具信息表"


def _truthy(value: object) -> bool:
    return str(value or "").strip() in TRUTHY_VALUES


def _is_empty_value(value: object) -> bool:
    return str(value or "").strip() in EMPTY_VALUES


def _item_table_changes(
    changeset_changes: List[Dict[str, object]],
) -> Tuple[bool, set]:
    """从 changeset 提取道具信息表的行级变更。

    返回 (touched, changed_ids)：
    - touched：道具信息表是否有任何变更（含删除）
    - changed_ids：新增/修改行的道具 ID 集合（删除行无需校验有效期/隐藏标记）
    """
    touched = False
    ids: set = set()
    for change in changeset_changes:
        if not isinstance(change, dict):
            continue
        sheet = str(change.get("sheet") or "")
        file_name = str(change.get("file_name") or "")
        if sheet != ITEM_TABLE_SHEET and ITEM_TABLE_FILE_MARKER not in file_name:
            continue
        touched = True
        if str(change.get("change_type") or "") == "deleted":
            continue
        business_key = change.get("business_key")
        values: List[object] = []
        if isinstance(business_key, dict):
            raw_values = business_key.get("values")
            if isinstance(raw_values, list):
                values = raw_values
        elif isinstance(business_key, str) and "=" in business_key:
            values = [business_key.split("=", 1)[1]]
        for value in values:
            text = str(value).strip()
            if text:
                ids.add(text)
    return touched, ids


def _resolve_item_dtxml(
    *,
    tdr_root: str,
    region_code: str,
    dtxml_relative_path: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    """定位道具信息表 dtxml；返回 (path, error_message)。"""
    if dtxml_relative_path:
        try:
            resolved = resolve_rule_dtxml_path(tdr_root, dtxml_relative_path, region_code)
        except ValueError as error:
            return None, str(error)
        if not os.path.isfile(resolved):
            return None, f"找不到道具 dtxml：{resolved}"
        return resolved, None

    common_core = os.path.join(tdr_root, "Xml", "Garena", region_code.upper(), "CommonCore")
    # 优先服务器道具表（41.svr下发道具信息表），客户端运营配置表仅作兜底。
    candidates = sorted(glob.glob(os.path.join(common_core, "*svr下发道具信息表*.dtxml")))
    if not candidates:
        candidates = sorted(glob.glob(os.path.join(common_core, "*道具信息表*.dtxml")))
    if not candidates:
        candidates = sorted(glob.glob(os.path.join(tdr_root, ITEM_DFXML_GLOB)))
    if not candidates:
        return None, f"找不到道具信息表 dtxml（已搜索 {common_core}）。"
    return candidates[0], None


def _read_item_rows(
    *,
    fixed_paths: List[str],
    local_root: str,
    validation_config: Optional[Dict[str, object]],
    check: Mapping[str, object],
    changeset_changes: Optional[List[Dict[str, object]]] = None,
) -> Dict[str, object]:
    """公共前置：触发判断 + 道具表读取。返回含 status 的结果骨架。

    触发与校验范围：只对提交内容做校验，以 changeset 行级变更为唯一触发源：
    - changeset_changes 不为 None：道具信息表有变更才校验，范围收敛到变更行 ID。
    - changeset_changes 为 None（diff 不可用）：跳过，不扫描整个文件。
    """
    resolved_region = str(validation_config.get("region_code") or "") if isinstance(validation_config, dict) else ""
    region = (resolved_region or infer_region_code(fixed_paths)).upper()

    scope_ids: Optional[set] = None
    if changeset_changes is None:
        return {
            "status": "skipped",
            "reason": "changeset_unavailable",
            "scope": "changeset",
            "message": "DTXML ChangeSet 不可用，为遵循「只校验提交内容」原则，本规则跳过。",
            "items": [],
            "warnings": [],
        }
    touched, scope_ids = _item_table_changes(changeset_changes)
    if not touched:
        return {"status": "skipped", "reason": "no_item_table_change", "scope": "changeset", "items": [], "warnings": []}

    tdr_root_value = validation_config.get("tdr_root") if isinstance(validation_config, dict) else None
    tdr_root = tdr_root_value if isinstance(tdr_root_value, str) and tdr_root_value.strip() else None
    resolved_tdr_root = tdr_root or infer_tdr_root_from_serverbytes(local_root)
    if not resolved_tdr_root:
        return {
            "status": "error",
            "reason": "missing_tdr_root",
            "message": "无法从 ServerBytes 根目录推导 TdrTable 根目录，请配置 tdr_root。",
            "items": [],
            "warnings": [],
        }

    dtxml_value = check.get("dtxml_path")
    dtxml_path, error = _resolve_item_dtxml(
        tdr_root=resolved_tdr_root,
        region_code=region,
        dtxml_relative_path=str(dtxml_value) if isinstance(dtxml_value, str) and dtxml_value.strip() else None,
    )
    if dtxml_path is None:
        return {"status": "error", "reason": "missing_dtxml", "message": error, "items": [], "warnings": []}

    try:
        columns, rows = read_dtxml_sheet(dtxml_path, ITEM_TABLE_SHEET)
    except (ValueError, OSError) as read_error:
        return {
            "status": "error",
            "reason": "unreadable_dtxml",
            "message": f"道具表读取失败：{read_error}",
            "items": [],
            "warnings": [],
        }
    return {
        "status": "ok",
        "region": region,
        "tdr_root": resolved_tdr_root,
        "dtxml_path": dtxml_path,
        "columns": columns,
        "scope": "changeset",
        "scope_ids": scope_ids,
        "rows": rows,
    }
