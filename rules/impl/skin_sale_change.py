"""规则：皮肤售卖方式变更校验（skin_sale_change_check，上下架/促销表改动驱动的售卖方式与低价告警）。"""
from __future__ import annotations

import os
from typing import Dict, List, Mapping, Optional

from validation_mvp import (
    infer_region_code,
    infer_tdr_root_from_serverbytes,
    read_dtxml_sheet,
    resolve_rule_dtxml_path,
)


SKIN_TABLE_FILE_MARKER = "英雄皮肤促销表"
SKIN_LISTING_SHEET = "svr下发皮肤上下架表"
SKIN_PROMO_SHEET = "svr下发皮肤促销特卖"
SKIN_SHEETS = (SKIN_LISTING_SHEET, SKIN_PROMO_SHEET)
SKIN_SHEET_LABELS = {
    SKIN_LISTING_SHEET: "皮肤上下架表",
    SKIN_PROMO_SHEET: "皮肤促销特卖",
}
SKIN_ID_COLUMN = "皮肤ID"
SKIN_NAME_COLUMN = "皮肤名称"
PROMO_ID_COLUMN = "促销特卖ID"
SKIN_SALE_MODE_COLUMNS = ("是否可点券购买", "是否可皮肤点购买", "是否可钻石购买", "是否支持混合支付")
SKIN_COUPON_PRICE_COLUMN = "点券价格"
SKIN_LOW_PRICE_THRESHOLD = 100
DEFAULT_SKIN_DFXML_PATH = os.path.join("Xml", "Garena", "{region}", "CommonCore", "英雄皮肤促销表.dtxml")


def _skin_table_changes(changeset_changes: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """从 changeset 提取皮肤促销表两个 sheet 的行级变更。"""
    matched: List[Dict[str, object]] = []
    for change in changeset_changes:
        if not isinstance(change, dict):
            continue
        file_name = str(change.get("file_name") or "")
        sheet = str(change.get("sheet") or "")
        if SKIN_TABLE_FILE_MARKER not in file_name:
            continue
        if sheet and sheet not in SKIN_SHEETS:
            continue
        matched.append(change)
    return matched


def _skin_change_row(change: Mapping[str, object]) -> Dict[str, object]:
    """取变更行的业务值：modified/added 用 after，deleted 用 before。"""
    change_type = str(change.get("change_type") or "")
    after = change.get("after")
    before = change.get("before")
    row = after if isinstance(after, dict) else (before if isinstance(before, dict) else {})
    return {
        "change_type": change_type,
        "before": before if isinstance(before, dict) else {},
        "after": after if isinstance(after, dict) else {},
        "row": row,
    }


def _parse_price(value: object) -> Optional[int]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def run_skin_sale_change_check(
    *,
    fixed_paths: List[str],
    local_root: str,
    validation_config: Optional[Dict[str, object]],
    check: Mapping[str, object],
    changeset_changes: Optional[List[Dict[str, object]]] = None,
    module_context: Optional[object] = None,
) -> Dict[str, object]:
    """规则：皮肤售卖方式变更校验（changeset 驱动，只校验提交内容）。

    触发：changeset 中含英雄皮肤促销表（上下架 sheet / 促销 sheet）行级变更。
    判定：
    - modified：售卖方式 4 列（是否可点券购买/皮肤点/钻石/混合支付）任一变更
      → 告警 + 人工核对；点券价格变更且改后值 < 100 → 低价告警；
      其余字段变更 → 通过级记录。
    - added：上下架表新增皮肤不告警（通过级记录）；促销表新增促销转人工核对，
      并按皮肤 ID 关联上下架快照取皮肤名。
    - deleted：两个表的删行均告警。
    """
    if changeset_changes is None:
        return {
            "status": "skipped",
            "reason": "changeset_unavailable",
            "scope": "changeset",
            "message": "DTXML ChangeSet 不可用，为遵循「只校验提交内容」原则，本规则跳过。",
            "items": [],
            "warnings": [],
        }

    matched = _skin_table_changes(changeset_changes)
    if not matched:
        return {
            "status": "skipped",
            "reason": "no_skin_table_change",
            "scope": "changeset",
            "items": [],
            "warnings": [],
        }

    resolved_region = str(validation_config.get("region_code") or "") if isinstance(validation_config, dict) else ""
    region = (resolved_region or infer_region_code(fixed_paths)).upper()
    tdr_root_value = validation_config.get("tdr_root") if isinstance(validation_config, dict) else None
    tdr_root = tdr_root_value if isinstance(tdr_root_value, str) and tdr_root_value.strip() else None
    resolved_tdr_root = tdr_root or infer_tdr_root_from_serverbytes(local_root)

    # 皮肤名快照目录（懒加载）：促销 sheet 的「皮肤ID」实际引用上下架 sheet 的行 ID，
    # 且上下架 sheet 的「皮肤ID」存在一对多（同皮肤多上架行），故目录按行 ID 建键。
    catalog: Dict[str, Dict[str, object]] = {}
    catalog_error = ""
    dtxml_value = check.get("dtxml_path")
    relative = str(dtxml_value) if isinstance(dtxml_value, str) and dtxml_value.strip() else DEFAULT_SKIN_DFXML_PATH
    if resolved_tdr_root:
        try:
            dtxml_path = resolve_rule_dtxml_path(resolved_tdr_root, relative, region)
            if os.path.isfile(dtxml_path):
                _, listing_rows = read_dtxml_sheet(dtxml_path, SKIN_LISTING_SHEET)
                for listing_row in listing_rows:
                    if isinstance(listing_row, dict):
                        listing_id = str(listing_row.get("ID") or "").strip()
                        if listing_id:
                            catalog[listing_id] = listing_row
            else:
                catalog_error = f"找不到皮肤 dtxml：{dtxml_path}"
        except (ValueError, OSError) as error:
            catalog_error = f"皮肤快照读取失败：{error}"

    def _skin_display(skin_id: str, row: Mapping[str, object]) -> str:
        name = str(row.get(SKIN_NAME_COLUMN) or "").strip()
        if not name and skin_id:
            snapshot = catalog.get(skin_id)
            if isinstance(snapshot, dict):
                name = str(snapshot.get(SKIN_NAME_COLUMN) or "").strip()
        return name

    warnings: List[Dict[str, object]] = []
    confirms: List[Dict[str, object]] = []
    passed_items: List[Dict[str, object]] = []

    for change in matched:
        parsed = _skin_change_row(change)
        change_type = parsed["change_type"]
        before: Dict[str, object] = parsed["before"]  # type: ignore[assignment]
        after: Dict[str, object] = parsed["after"]  # type: ignore[assignment]
        row: Dict[str, object] = parsed["row"]  # type: ignore[assignment]
        sheet = str(change.get("sheet") or "")
        sheet_label = SKIN_SHEET_LABELS.get(sheet, sheet or "皮肤促销表")
        skin_id = str(row.get(SKIN_ID_COLUMN) or "").strip()
        skin_name = _skin_display(skin_id, row)
        skin_display = f"皮肤 {skin_id}" + (f"（{skin_name}）" if skin_name else "")
        if sheet == SKIN_PROMO_SHEET:
            promo_id = str(row.get(PROMO_ID_COLUMN) or "").strip()
            display = f"促销 {promo_id}（关联{skin_display}）" if promo_id else skin_display
        else:
            display = skin_display

        if change_type == "added":
            if sheet == SKIN_PROMO_SHEET:
                promo_id = str(row.get(PROMO_ID_COLUMN) or "").strip()
                confirms.append({
                    "type": "skin_promo_added",
                    "level": "confirm",
                    "skin_id": skin_id,
                    "skin_name": skin_name,
                    "sheet": sheet_label,
                    "change_type_label": "新增",
                    "change_summary": f"新增促销 {promo_id}" if promo_id else "新增促销",
                    "message": f"新增促销 {promo_id} 关联{skin_display}，请与皮肤配置一并人工确认。",
                })
            else:
                passed_items.append({
                    "type": "skin_listing_added",
                    "level": "passed",
                    "skin_id": skin_id,
                    "skin_name": skin_name,
                    "sheet": sheet_label,
                    "change_type_label": "新增",
                    "change_summary": "新增皮肤上架",
                    "message": f"新增{display}，按约定无需告警。",
                })
            continue

        if change_type == "deleted":
            promo_id = str(row.get(PROMO_ID_COLUMN) or "").strip()
            summary = f"删除促销 {promo_id}" if (sheet == SKIN_PROMO_SHEET and promo_id) else f"删除{sheet_label}行"
            warnings.append({
                "type": "skin_row_deleted",
                "level": "warning",
                "skin_id": skin_id,
                "skin_name": skin_name,
                "sheet": sheet_label,
                "change_type_label": "删除",
                "change_summary": summary,
                "message": f"{sheet_label}删除行：{display}，请人工确认是否有存量影响。",
            })
            continue

        # modified
        mode_diffs: List[str] = []
        for column in SKIN_SALE_MODE_COLUMNS:
            before_value = str(before.get(column) or "").strip()
            after_value = str(after.get(column) or "").strip()
            if before_value != after_value:
                mode_diffs.append(f"{column} {before_value or '∅'}→{after_value or '∅'}")
        if mode_diffs:
            warnings.append({
                "type": "skin_sale_mode_changed",
                "level": "warning",
                "skin_id": skin_id,
                "skin_name": skin_name,
                "sheet": sheet_label,
                "change_type_label": "修改",
                "change_summary": "；".join(mode_diffs),
                "message": f"{display}售卖方式变更（{'；'.join(mode_diffs)}），需人工确认。",
            })
            continue

        before_price = _parse_price(before.get(SKIN_COUPON_PRICE_COLUMN))
        after_price = _parse_price(after.get(SKIN_COUPON_PRICE_COLUMN))
        if before_price != after_price and after_price is not None and after_price < SKIN_LOW_PRICE_THRESHOLD:
            warnings.append({
                "type": "skin_low_price",
                "level": "warning",
                "skin_id": skin_id,
                "skin_name": skin_name,
                "sheet": sheet_label,
                "change_type_label": "修改",
                "change_summary": f"点券价格 {before_price if before_price is not None else '∅'}→{after_price}",
                "message": (
                    f"{display}点券价格改为 {after_price}（低于 {SKIN_LOW_PRICE_THRESHOLD}），"
                    "低价售卖风险，需人工确认。"
                ),
            })
            continue

        changed_fields = change.get("changed_fields")
        field_summary = "、".join(str(field) for field in changed_fields) if isinstance(changed_fields, list) and changed_fields else "非售卖方式字段"
        passed_items.append({
            "type": "skin_change_safe",
            "level": "passed",
            "skin_id": skin_id,
            "skin_name": skin_name,
            "sheet": sheet_label,
            "change_type_label": "修改",
            "change_summary": field_summary,
            "message": f"{display}变更未涉及售卖方式调整/低价风险。",
        })

    status = "warning" if warnings else ("confirm" if confirms else "passed")
    return {
        "status": status,
        "rule_id": check.get("id", "skin-sale-change-check"),
        "scope": "changeset",
        "changed_count": len(matched),
        "warning_count": len(warnings),
        "passed_count": len(passed_items),
        "catalog_loaded": len(catalog),
        "catalog_error": catalog_error,
        "passed_items": passed_items,
        "items": warnings + confirms,
        "warnings": warnings,
    }
