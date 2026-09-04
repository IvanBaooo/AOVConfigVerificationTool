"""规则：道具有效期与活动时间关联校验（expiry_time_cross_check，I7 扩展）。"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Tuple

from validation_mvp import parse_compact_datetime

from ._shared import (
    ITEM_ACTIVITY_ID_COLUMN,
    ITEM_EXPIRY_COLUMN,
    ITEM_EXPIRY_FALLBACK_COLUMNS,
    ITEM_ID_COLUMN,
    ITEM_NAME_COLUMN,
    ITEM_TABLE_SHEET,
    _is_empty_value,
    _read_item_rows,
)


def _activity_windows(validation_config: Optional[Dict[str, object]]) -> Dict[str, Dict[str, str]]:
    """活动排期表：validation_config["activity_windows"] = {活动ID: {start_time, end_time}}。"""
    if not isinstance(validation_config, dict):
        return {}
    raw = validation_config.get("activity_windows")
    if not isinstance(raw, dict):
        return {}
    windows: Dict[str, Dict[str, str]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        windows[str(key)] = {
            "start_time": str(value.get("start_time") or ""),
            "end_time": str(value.get("end_time") or ""),
        }
    return windows


def _resolve_item_activities(
    index: object,
    item_id: str,
    linked_activity_id: str,
) -> List[Dict[str, object]]:
    """经 module 关联索引（读当前全量快照）解析道具的关联活动及起止时间。

    合并三个来源，按活动 ID 去重：
    1. 奖励/兑换关联链 impacts_for_changes —— 历史提交配置的活动也能覆盖
    2. token 进度 / ilua 聚合链 token_progress
    3. 道具行「活动ID」列在日常活动表中的直查
    """
    resolved: Dict[str, Dict[str, object]] = {}

    def _merge(activity_id: object, name: object, start: object, end: object, source: str) -> None:
        act_id = str(activity_id or "").strip()
        if not act_id:
            return
        entry = resolved.setdefault(act_id, {
            "activity_id": act_id,
            "activity_name": str(name or ""),
            "start_time": "",
            "end_time": "",
            "sources": [],
        })
        if name and not entry["activity_name"]:
            entry["activity_name"] = str(name)
        if start and not entry["start_time"]:
            entry["start_time"] = str(start).strip()
        if end and not entry["end_time"]:
            entry["end_time"] = str(end).strip()
        if source not in entry["sources"]:
            entry["sources"].append(source)

    synthetic_change = {
        "file_name": "41.svr下发道具信息表_Syndra.dtxml",
        "sheet": ITEM_TABLE_SHEET,
        "business_key": {"display": f"ID={item_id}"},
        "before": None,
        "after": {"ID": item_id},
    }
    for impacts in index.impacts_for_changes([synthetic_change]).values():
        for impact in impacts:
            impact_row = impact.get("row")
            if not isinstance(impact_row, Mapping):
                impact_row = {}
            _merge(
                impact.get("activity_id"),
                impact.get("activity_name"),
                impact_row.get("开始时间", ""),
                impact_row.get("结束时间", ""),
                "reward_exchange_chain",
            )

    progress = index.token_progress(item_id)
    for activity in progress.get("activities", []):
        _merge(
            activity.get("activity_id"),
            activity.get("activity_name"),
            activity.get("start_time_raw") or activity.get("start_time"),
            activity.get("end_time_raw") or activity.get("end_time"),
            "token_progress_chain",
        )
    for activity in progress.get("ilua_activities", []):
        _merge(
            activity.get("activity_id"),
            activity.get("activity_name"),
            activity.get("start_time"),
            activity.get("end_time"),
            "ilua_chain",
        )

    if linked_activity_id:
        for sheet_rows in index.daily_sheets.values():
            for row in sheet_rows:
                if isinstance(row, Mapping) and str(row.get("活动ID", "")).strip() == linked_activity_id:
                    _merge(
                        linked_activity_id,
                        row.get("活动名称") or row.get("活动标题", ""),
                        row.get("开始时间", ""),
                        row.get("结束时间", ""),
                        "activity_id_column",
                    )
    return list(resolved.values())


def _expiry_value(row: Mapping[str, str], expiry_column: str) -> Tuple[str, str]:
    """返回 (列名, 原始值)；主列为空时按回退列取。"""
    primary = str(row.get(expiry_column) or "").strip()
    if primary:
        return expiry_column, primary
    for fallback in ITEM_EXPIRY_FALLBACK_COLUMNS:
        value = str(row.get(fallback) or "").strip()
        if value:
            return fallback, value
    return expiry_column, ""


def run_expiry_cross_check(
    *,
    fixed_paths: List[str],
    local_root: str,
    validation_config: Optional[Dict[str, object]],
    check: Mapping[str, object],
    changeset_changes: Optional[List[Dict[str, object]]] = None,
    module_context: Optional[object] = None,
) -> Dict[str, object]:
    """规则 2：含有效期字段的道具行与关联活动时间的关联校验。

    活动时间数据源（优先级从高到低）：
    1. module 关联索引（读当前全量快照，历史提交配置的活动也能覆盖）
    2. 人工维护的 activity_windows（兜底/补全缺失的起止时间）
    都无法确定关联活动 → 转人工核对（confirm）。

    判定顺序（服务器时间直接比较，对每个关联活动独立判定，取最差结论）：
    1. expire_time 为空 → 通过
    2. expire_time > 关联活动 end_time → 该活动通过
    3. expire_time ≤ 活动 start_time → 爆红告警（I7 精确模式）
    4. expire_time 落在活动期间内 → 爆红告警
    5. 活动缺少结束时间 → 转人工核对（confirm）
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

    params = check.get("params")
    expiry_column = ITEM_EXPIRY_COLUMN
    if isinstance(params, dict) and isinstance(params.get("expiry_column"), str) and params["expiry_column"].strip():
        configured = str(params["expiry_column"]).strip()
        # 规格里的 expire_time 是逻辑字段名；真实表列名以道具表为准。
        expiry_column = configured if configured in (base.get("columns") or []) else ITEM_EXPIRY_COLUMN

    windows = _activity_windows(validation_config)
    rows = base["rows"]
    assert isinstance(rows, list)
    scope_ids = base.get("scope_ids")
    if scope_ids is not None:
        rows = [row for row in rows if isinstance(row, dict) and str(row.get(ITEM_ID_COLUMN, "")).strip() in scope_ids]

    # module 关联索引：优先复用流水线共享 context，否则按解析出的 tdr_root 自建
    if module_context is None or not getattr(module_context, "tdr_root", ""):
        from changeset_modules import ModuleContext
        module_context = ModuleContext(
            tdr_root=str(base.get("tdr_root") or ""),
            region_code=str(base.get("region") or "TW"),
        )
    reference_index = None
    activity_resolution = "manual_only"
    try:
        reference_index = module_context.activity_index  # type: ignore[union-attr]
        activity_resolution = "module_index"
    except Exception:
        reference_index = None

    warnings: List[Dict[str, object]] = []
    confirms: List[Dict[str, object]] = []
    passed_items: List[Dict[str, object]] = []
    checked_count = 0

    for row in rows:
        if not isinstance(row, dict):
            continue
        column, raw_expiry = _expiry_value(row, expiry_column)
        if _is_empty_value(raw_expiry):
            continue  # 判定 1：不过期，通过
        checked_count += 1
        item_id = str(row.get(ITEM_ID_COLUMN, ""))
        item_name = str(row.get(ITEM_NAME_COLUMN, ""))
        activity_id = str(row.get(ITEM_ACTIVITY_ID_COLUMN, "") or "").strip()

        expire_dt = parse_compact_datetime(raw_expiry)
        if expire_dt is None:
            confirms.append({
                "type": "expiry_unparseable",
                "level": "confirm",
                "item_id": item_id,
                "name": item_name,
                "expire_time": raw_expiry,
                "message": f"道具 {item_id} 的 {column}「{raw_expiry}」格式无法解析，转人工核对。",
            })
            continue

        candidates: List[Dict[str, object]] = []
        if reference_index is not None:
            try:
                candidates = _resolve_item_activities(reference_index, item_id, activity_id)
            except Exception:
                candidates = []
        # 人工排期表兜底：补充未覆盖的活动 / 填补缺失的起止时间
        manual = windows.get(activity_id) if activity_id else None
        if manual is not None:
            existing = next((cand for cand in candidates if cand["activity_id"] == activity_id), None)
            if existing is None:
                candidates.append({
                    "activity_id": activity_id,
                    "activity_name": "",
                    "start_time": str(manual.get("start_time") or ""),
                    "end_time": str(manual.get("end_time") or ""),
                    "sources": ["manual_activity_windows"],
                })
            else:
                if not existing["start_time"]:
                    existing["start_time"] = str(manual.get("start_time") or "")
                if not existing["end_time"]:
                    existing["end_time"] = str(manual.get("end_time") or "")
                if "manual_activity_windows" not in existing["sources"]:
                    existing["sources"].append("manual_activity_windows")

        if not candidates:
            confirms.append({
                "type": "expiry_activity_unknown",
                "level": "confirm",
                "item_id": item_id,
                "name": item_name,
                "expire_time": raw_expiry,
                "activity_id": activity_id,
                "message": f"道具 {item_id} 含有效期但关联链与人工排期均未找到对应活动，转人工核对。",
            })
            continue

        warn_acts: List[Tuple[str, Dict[str, object]]] = []
        confirm_acts: List[Dict[str, object]] = []
        for candidate in candidates:
            end_dt = parse_compact_datetime(str(candidate.get("end_time") or ""))
            start_dt = parse_compact_datetime(str(candidate.get("start_time") or ""))
            if end_dt is None:
                confirm_acts.append(candidate)
                continue
            if expire_dt > end_dt:
                continue  # 判定 2：该活动通过
            verdict = "expiry_before_activity_start" if (start_dt is None or expire_dt <= start_dt) else "expiry_within_activity_window"
            warn_acts.append((verdict, candidate))

        if warn_acts:
            first_verdict = warn_acts[0][0]
            warnings.append({
                "type": first_verdict,
                "level": "warning",
                "item_id": item_id,
                "name": item_name,
                "expire_time": raw_expiry,
                "activity_id": str(warn_acts[0][1]["activity_id"]),
                "activities": [
                    {
                        "verdict": verdict,
                        "activity_id": str(cand["activity_id"]),
                        "activity_name": str(cand["activity_name"]),
                        "activity_start_time": str(cand["start_time"]),
                        "activity_end_time": str(cand["end_time"]),
                        "sources": list(cand["sources"]),
                    }
                    for verdict, cand in warn_acts
                ],
                "suggestion": "建议将 expire_time 调整为活动结束之后，或置空（不过期）。",
                "message": (
                    f"道具 {item_id}（{item_name}）有效期 {raw_expiry} 早于等于活动开始时间，"
                    f"玩家将无法获得奖励（I7 模式）。命中活动："
                    + "、".join(str(cand["activity_id"]) for _, cand in warn_acts)
                    if first_verdict == "expiry_before_activity_start"
                    else f"道具 {item_id}（{item_name}）有效期 {raw_expiry} 落在活动 "
                    + "、".join(str(cand["activity_id"]) for _, cand in warn_acts)
                    + " 期间内，活动结束后道具即过期。"
                ),
            })
        elif confirm_acts:
            confirms.append({
                "type": "expiry_activity_window_missing",
                "level": "confirm",
                "item_id": item_id,
                "name": item_name,
                "expire_time": raw_expiry,
                "activity_id": str(confirm_acts[0]["activity_id"]),
                "activities": [
                    {
                        "activity_id": str(cand["activity_id"]),
                        "activity_name": str(cand["activity_name"]),
                        "sources": list(cand["sources"]),
                    }
                    for cand in confirm_acts
                ],
                "message": f"道具 {item_id} 的关联活动 "
                + "、".join(str(cand["activity_id"]) for cand in confirm_acts)
                + " 缺少结束时间，转人工核对。",
            })
        else:
            # 所有关联活动均判定通过：有效期晚于活动结束时间
            passed_items.append({
                "type": "expiry_after_activity_end",
                "level": "passed",
                "item_id": item_id,
                "name": item_name,
                "expire_time": raw_expiry,
                "activities": [
                    {
                        "activity_id": str(cand["activity_id"]),
                        "activity_name": str(cand["activity_name"]),
                        "activity_start_time": str(cand["start_time"]),
                        "activity_end_time": str(cand["end_time"]),
                        "sources": list(cand["sources"]),
                    }
                    for cand in candidates
                ],
            })

    status = "warning" if warnings else ("confirm" if confirms else "passed")
    return {
        "status": status,
        "rule_id": check.get("id", "expiry-activity-cross-check"),
        "expiry_column": expiry_column,
        "checked_count": checked_count,
        "scope": base.get("scope", "changeset"),
        "scope_ids": sorted(scope_ids) if scope_ids else [],
        "activity_resolution": activity_resolution,
        "activity_windows_loaded": len(windows),
        "item_count": len(confirms),
        "warning_count": len(warnings),
        "passed_count": len(passed_items),
        "passed_items": passed_items,
        "items": confirms,
        "warnings": warnings,
    }
