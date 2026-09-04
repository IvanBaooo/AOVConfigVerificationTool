"""规则：隐藏道具识别与单独标注（hidden_item_listing，源自 I7 橘右京 ilua 隐形 token 问题复盘）。"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional

from ._shared import (
    ITEM_ACTIVITY_ID_COLUMN,
    ITEM_EXPIRY_COLUMN,
    ITEM_HIDDEN_COLUMN,
    ITEM_ID_COLUMN,
    ITEM_NAME_COLUMN,
    ITEM_TABLE_SHEET,
    _read_item_rows,
    _truthy,
)


def run_hidden_item_listing(
    *,
    fixed_paths: List[str],
    local_root: str,
    validation_config: Optional[Dict[str, object]],
    check: Mapping[str, object],
    changeset_changes: Optional[List[Dict[str, object]]] = None,
) -> Dict[str, object]:
    """规则 1：隐藏道具识别与单独标注。

    MVP 识别条件：道具行 `是否是隐藏道具` 为真。ilua 引用链（作为进度/计数
    引用但不作为奖励发放）的解析方式待真实配置确认后再补充。
    """
    base = _read_item_rows(
        fixed_paths=fixed_paths,
        local_root=local_root,
        validation_config=validation_config,
        check=check,
        changeset_changes=changeset_changes,
    )
    if base.get("status") != "ok":
        return base

    rows = base["rows"]
    assert isinstance(rows, list)
    scope_ids = base.get("scope_ids")
    if scope_ids is not None:
        rows = [row for row in rows if isinstance(row, dict) and str(row.get(ITEM_ID_COLUMN, "")).strip() in scope_ids]
    items: List[Dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not _truthy(row.get(ITEM_HIDDEN_COLUMN)):
            continue
        items.append({
            "type": "hidden_item",
            "level": "warning",
            "item_id": row.get(ITEM_ID_COLUMN, ""),
            "name": row.get(ITEM_NAME_COLUMN, ""),
            "linked_activity": row.get(ITEM_ACTIVITY_ID_COLUMN, "") or "",
            "expire_time": row.get(ITEM_EXPIRY_COLUMN, "") or "",
        })

    warnings: List[Dict[str, object]] = []
    if items:
        warnings.append({
            "type": "hidden_items_present",
            "level": "warning",
            "message": f"本次配置含 {len(items)} 个隐藏道具，请与 QA 同步确认。",
            "item_count": len(items),
        })
    return {
        "status": "warning" if items else "passed",
        "rule_id": check.get("id", "hidden-item-tab"),
        "display_tab": "隐藏道具",
        "scope": base.get("scope", "changeset"),
        "scope_ids": sorted(scope_ids) if scope_ids else [],
        "source": {"dtxml": base.get("dtxml_path", ""), "sheet": ITEM_TABLE_SHEET},
        "item_count": len(items),
        "warning_count": len(warnings),
        "items": items,
        "warnings": warnings,
    }
