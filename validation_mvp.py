from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

try:
	from lxml import etree as ET  # type: ignore
except Exception:  # pragma: no cover - fallback for minimal local Python envs.
	import xml.etree.ElementTree as ET  # type: ignore


SKIN_TABLE_NAME = "英雄皮肤促销表"
SKIN_DFXML_NAME = "英雄皮肤促销表.dtxml"
SKIN_MAIN_SHEET = "svr下发皮肤上下架表"
SKIN_PROMO_SHEET = "svr下发皮肤促销特卖"

SKIN_MAIN_FIELDS = [
	"ID",
	"英雄ID",
	"英雄名",
	"皮肤ID",
	"皮肤名称",
	"上架时间",
	"下架时间",
	"是否可点券购买",
	"点券价格",
	"是否可皮肤点购买",
	"皮肤点价格",
	"是否可钻石购买",
	"钻石价格",
	"是否支持混合支付",
	"是否在商店显示",
	"促销特卖1",
	"促销特卖2",
	"促销特卖3",
	"促销特卖4",
	"促销特卖5",
]

SKIN_PROMO_FIELDS = [
	"促销特卖ID",
	"皮肤ID",
	"是否可点券购买",
	"点券价格",
	"是否可皮肤点购买",
	"皮肤点价格",
	"是否可钻石购买",
	"钻石价格",
	"是否支持混合支付",
	"上架时间",
	"下架时间",
	"促销标签",
	"折扣比例",
	"购买排序ID",
	"排序不受动态规则影响",
	"皮肤获取方式跳转入口",
	"获取途径",
]


@dataclass
class CheckWindow:
	start: datetime
	end: datetime
	raw_start: str
	raw_end: str


def infer_tdr_root_from_serverbytes(local_root: str) -> Optional[str]:
	"""Infer Tools/TdrTable root from a ServerBytes root."""
	norm = os.path.normpath(local_root)
	if os.path.basename(norm).lower() == "serverbytes":
		return os.path.dirname(norm)
	return None


def infer_region_code(fixed_paths: Iterable[str]) -> str:
	for path in fixed_paths:
		normalized = path.replace("\\", "/").strip("/")
		first_part = normalized.split("/", 1)[0] if normalized else ""
		if first_part == "Taiwan":
			return "TW"
		if first_part == "Thailand":
			return "TH"
		if first_part == "Vietnam":
			return "VN"
		if first_part == "Indonesia":
			return "ID"
	return "TW"


def region_to_serverbytes_dir(region_code: str) -> str:
	return {
		"TW": "Taiwan",
		"TH": "Thailand",
		"VN": "Vietnam",
		"ID": "Indonesia",
	}.get(region_code.upper(), "Taiwan")


def parse_compact_datetime(value: str) -> Optional[datetime]:
	value = (value or "").strip()
	if not value or value in {"0", "0x0"}:
		return None
	for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
		try:
			return datetime.strptime(value, fmt)
		except ValueError:
			continue
	return None


def parse_check_window(start: str, end: str) -> CheckWindow:
	start_dt = parse_compact_datetime(start)
	end_dt = parse_compact_datetime(end)
	if start_dt is None:
		raise ValueError(f"检查窗口开始时间格式不支持：{start}")
	if end_dt is None:
		raise ValueError(f"检查窗口结束时间格式不支持：{end}")
	if end_dt < start_dt:
		raise ValueError("检查窗口结束时间不能早于开始时间。")
	return CheckWindow(start=start_dt, end=end_dt, raw_start=start, raw_end=end)


def interval_overlaps_window(start_value: str, end_value: str, window: CheckWindow) -> Tuple[bool, Optional[str]]:
	start_dt = parse_compact_datetime(start_value)
	end_dt = parse_compact_datetime(end_value)
	if start_value and start_dt is None:
		return False, f"上架时间格式无法解析：{start_value}"
	if end_value and end_dt is None:
		return False, f"下架时间格式无法解析：{end_value}"
	if start_dt is None:
		return False, None
	if start_dt > window.end:
		return False, None
	if end_dt is not None and end_dt < window.start:
		return False, None
	return True, None


def _parse_xml(path: str):
	parser = None
	if hasattr(ET, "XMLParser"):
		try:
			parser = ET.XMLParser(remove_blank_text=False, recover=False)  # type: ignore[call-arg]
		except TypeError:
			parser = None
	if parser is not None:
		return ET.parse(path, parser)  # type: ignore[arg-type]
	return ET.parse(path)


def read_dtxml_sheet(dtxml_path: str, sheet_name: str) -> Tuple[List[str], List[Dict[str, str]]]:
	tree = _parse_xml(dtxml_path)
	root = tree.getroot()
	for sheet in root.findall("Sheet"):
		if sheet.get("Name") != sheet_name:
			continue
		columns_node = sheet.find("Columns")
		columns = []
		if columns_node is not None:
			columns = [(col.get("Name") or "").strip() for col in columns_node.findall("Column")]

		rows: List[Dict[str, str]] = []
		for row in sheet.findall("Row"):
			row_data: Dict[str, str] = {}
			for cell in row.findall("Cell"):
				name = (cell.get("Name") or "").strip()
				if not name:
					continue
				row_data[name] = (cell.text or "").strip()
			if any(value for value in row_data.values()):
				rows.append(row_data)
		return columns, rows
	raise ValueError(f"找不到 dtxml sheet：{sheet_name}")


def skin_module_touched(
	fixed_paths: Iterable[str],
	trigger_paths: Optional[Iterable[str]] = None,
	region_code: str = "TW",
) -> bool:
	triggers = list(trigger_paths or [
		f"/{SKIN_DFXML_NAME}",
		"/Databin/Server/Shop/SvrHeroSkinShop.xml",
		"/Databin/Server/Shop/SvrHeroSkinShop.bytes",
	])
	normalized_triggers = [
		trigger.replace("{region}", region_code.upper()).replace("\\", "/").casefold()
		for trigger in triggers
	]
	for path in fixed_paths:
		normalized = path.replace("\\", "/").casefold()
		if any(normalized.endswith(trigger) for trigger in normalized_triggers):
			return True
	return False


def default_skin_dtxml_path(tdr_root: str, region_code: str) -> str:
	return os.path.join(tdr_root, "Xml", "Garena", region_code.upper(), "CommonCore", SKIN_DFXML_NAME)


def default_skin_xml_path(tdr_root: str, region_code: str) -> str:
	region_dir = region_to_serverbytes_dir(region_code)
	return os.path.join(tdr_root, "ServerBytes", region_dir, "Databin", "Server", "Shop", "SvrHeroSkinShop.xml")


def resolve_rule_dtxml_path(tdr_root: str, relative_path: str, region_code: str) -> str:
	relative = relative_path.replace("{region}", region_code.upper()).replace("/", os.sep).replace("\\", os.sep)
	relative = relative.lstrip(os.sep)
	resolved_root = os.path.abspath(tdr_root)
	resolved_path = os.path.abspath(os.path.join(resolved_root, relative))
	if os.path.commonpath([resolved_root, resolved_path]) != resolved_root:
		raise ValueError("DTXML 规则路径不能离开 TdrTable 根目录。")
	return resolved_path


def _pick(row: Dict[str, str], fields: Iterable[str]) -> Dict[str, str]:
	return {field: row.get(field, "") for field in fields}


def _promotion_ids(main_row: Dict[str, str]) -> List[str]:
	ids: List[str] = []
	for field in ("促销特卖1", "促销特卖2", "促销特卖3", "促销特卖4", "促销特卖5"):
		value = (main_row.get(field) or "").strip()
		if value and value not in {"0", "0x0"}:
			ids.append(value)
	return ids


def run_skin_precheck(
	*,
	fixed_paths: List[str],
	local_root: str,
	check_window_start: str,
	check_window_end: str,
	tdr_root: Optional[str] = None,
	region_code: Optional[str] = None,
	dtxml_relative_path: Optional[str] = None,
	main_sheet: str = SKIN_MAIN_SHEET,
	promotion_sheet: str = SKIN_PROMO_SHEET,
	trigger_paths: Optional[List[str]] = None,
) -> Dict[str, object]:
	"""Run the MVP skin precheck against dtxml rows.

	The check is skipped unless this package touches the skin dtxml/exported xml paths.
	"""
	resolved_region = (region_code or infer_region_code(fixed_paths)).upper()
	if not skin_module_touched(fixed_paths, trigger_paths, resolved_region):
		return {
			"status": "skipped",
			"reason": "package_not_touch_skin_module",
			"items": [],
			"warnings": [],
		}

	region = resolved_region
	resolved_tdr_root = tdr_root or infer_tdr_root_from_serverbytes(local_root)
	if not resolved_tdr_root:
		return {
			"status": "error",
			"reason": "missing_tdr_root",
			"message": "无法从 ServerBytes 根目录推导 TdrTable 根目录，请配置 tdr_root。",
			"items": [],
			"warnings": [],
		}

	window = parse_check_window(check_window_start, check_window_end)
	dtxml_path = (
		resolve_rule_dtxml_path(resolved_tdr_root, dtxml_relative_path, region)
		if dtxml_relative_path
		else default_skin_dtxml_path(resolved_tdr_root, region)
	)
	xml_path = default_skin_xml_path(resolved_tdr_root, region)
	if not os.path.isfile(dtxml_path):
		return {
			"status": "error",
			"reason": "missing_dtxml",
			"message": f"找不到皮肤 dtxml：{dtxml_path}",
			"items": [],
			"warnings": [],
			"source": {
				"dtxml": dtxml_path,
				"xml": xml_path,
			},
		}

	main_columns, main_rows = read_dtxml_sheet(dtxml_path, main_sheet)
	promo_columns, promo_rows = read_dtxml_sheet(dtxml_path, promotion_sheet)
	if "ID" not in main_columns:
		return {
			"status": "error",
			"reason": "missing_main_key",
			"message": "皮肤主表缺少 ID 字段。",
			"items": [],
			"warnings": [],
		}
	if "促销特卖ID" not in promo_columns:
		return {
			"status": "error",
			"reason": "missing_promo_key",
			"message": "皮肤促销表缺少 促销特卖ID 字段。",
			"items": [],
			"warnings": [],
		}

	promo_by_id = {row.get("促销特卖ID", ""): row for row in promo_rows if row.get("促销特卖ID")}
	items: List[Dict[str, object]] = []
	warnings: List[Dict[str, object]] = []

	for main_row in main_rows:
		main_id = main_row.get("ID", "")
		if not main_id or main_id == "0":
			continue

		main_overlaps, main_time_warning = interval_overlaps_window(
			main_row.get("上架时间", ""),
			main_row.get("下架时间", ""),
			window,
		)
		if main_time_warning:
			warnings.append({
				"type": "skin_time_parse_warning",
				"level": "warning",
				"id": main_id,
				"message": main_time_warning,
			})

		promotions: List[Dict[str, object]] = []
		promo_overlaps = False
		for promo_id in _promotion_ids(main_row):
			promo_row = promo_by_id.get(promo_id)
			if promo_row is None:
				warnings.append({
					"type": "skin_missing_promotion_warning",
					"level": "warning",
					"id": main_id,
					"promo_id": promo_id,
					"message": "主表关联了促销特卖ID，但促销表找不到对应记录。",
				})
				continue

			overlaps, promo_time_warning = interval_overlaps_window(
				promo_row.get("上架时间", ""),
				promo_row.get("下架时间", ""),
				window,
			)
			if promo_time_warning:
				warnings.append({
					"type": "skin_promo_time_parse_warning",
					"level": "warning",
					"id": main_id,
					"promo_id": promo_id,
					"message": promo_time_warning,
				})
			if overlaps:
				promo_overlaps = True
				promotions.append({
					"promo_id": promo_id,
					"fields": _pick(promo_row, SKIN_PROMO_FIELDS),
				})

		if not main_overlaps and not promo_overlaps:
			continue

		items.append({
			"type": "skin_precheck_confirm",
			"level": "confirm",
			"module": "皮肤",
			"table": SKIN_TABLE_NAME,
			"main_sheet": main_sheet,
			"promo_sheet": promotion_sheet,
			"id": main_id,
			"hero_id": main_row.get("英雄ID", ""),
			"hero_name": main_row.get("英雄名", ""),
			"skin_id": main_row.get("皮肤ID", ""),
			"skin_name": main_row.get("皮肤名称", ""),
			"match_reason": {
				"long_term_overlaps_window": main_overlaps,
				"promotion_overlaps_window": promo_overlaps,
			},
			"long_term_status": _pick(main_row, SKIN_MAIN_FIELDS),
			"promotions": promotions,
		})

	status = "confirm" if items else "passed"
	if warnings and not items:
		status = "warning"
	return {
		"status": status,
		"check_window": {
			"start_time": window.raw_start,
			"end_time": window.raw_end,
		},
		"source": {
			"dtxml": dtxml_path,
			"xml": xml_path,
			"xml_exists": os.path.isfile(xml_path),
			"main_sheet": main_sheet,
			"promo_sheet": promotion_sheet,
		},
		"item_count": len(items),
		"warning_count": len(warnings),
		"items": items,
		"warnings": warnings,
	}


def _skin_precheck_result(
	*,
	fixed_paths: List[str],
	local_root: str,
	validation_config: Optional[Dict[str, object]],
) -> Dict[str, object]:
	if not validation_config:
		return {
			"status": "skipped",
			"reason": "missing_validation_config",
			"items": [],
			"warnings": [],
		}

	content_check: Optional[Dict[str, object]] = None
	if "content_checks" in validation_config:
		content_checks = validation_config.get("content_checks")
		if isinstance(content_checks, list):
			content_check = next((
				dict(item) for item in content_checks
				if isinstance(item, dict)
				and item.get("type") == "skin_sale_window"
				and item.get("enabled") is True
			), None)
		if content_check is None:
			return {
				"status": "skipped",
				"reason": "content_check_disabled",
				"items": [],
				"warnings": [],
			}
	check_window = validation_config.get("check_window") or {}
	if not isinstance(check_window, dict):
		check_window = {}
	start = str(check_window.get("start_time", "")).strip()
	end = str(check_window.get("end_time", "")).strip()
	if not start or not end:
		return {
			"status": "skipped",
			"reason": "missing_check_window",
			"items": [],
			"warnings": [],
		}

	return run_skin_precheck(
		fixed_paths=fixed_paths,
		local_root=local_root,
		check_window_start=start,
		check_window_end=end,
		tdr_root=validation_config.get("tdr_root") if isinstance(validation_config.get("tdr_root"), str) else None,
		region_code=validation_config.get("region_code") if isinstance(validation_config.get("region_code"), str) else None,
		dtxml_relative_path=(
			str(content_check.get("dtxml_path"))
			if content_check and isinstance(content_check.get("dtxml_path"), str)
			else None
		),
		main_sheet=(
			str(content_check.get("main_sheet"))
			if content_check and isinstance(content_check.get("main_sheet"), str)
			else SKIN_MAIN_SHEET
		),
		promotion_sheet=(
			str(content_check.get("promotion_sheet"))
			if content_check and isinstance(content_check.get("promotion_sheet"), str)
			else SKIN_PROMO_SHEET
		),
		trigger_paths=(
			list(content_check.get("trigger_paths", []))
			if content_check and isinstance(content_check.get("trigger_paths"), list)
			else None
		),
	)


def _summary_contribution(result: Dict[str, object]) -> Tuple[int, int, int, int]:
	error = 1 if result.get("status") == "error" else 0
	warning = int(result.get("warning_count", 0) or 0)
	if result.get("status") == "warning":
		warning += 1
	confirm = int(result.get("item_count", 0) or 0)
	skipped = 1 if result.get("status") == "skipped" else 0
	return error, warning, confirm, skipped


def run_mvp_validations(
	*,
	fixed_paths: List[str],
	local_root: str,
	validation_config: Optional[Dict[str, object]],
	changeset_changes: Optional[List[Dict[str, object]]] = None,
	module_context: Optional[object] = None,
) -> Dict[str, object]:
	from rules.registry import run_content_check, spec_for_type

	checks: Dict[str, object] = {
		"skin_precheck": _skin_precheck_result(
			fixed_paths=fixed_paths,
			local_root=local_root,
			validation_config=validation_config,
		),
	}

	if isinstance(validation_config, dict):
		content_checks = validation_config.get("content_checks")
		if isinstance(content_checks, list):
			for check in content_checks:
				if not isinstance(check, dict) or check.get("enabled") is not True:
					continue
				check_type = check.get("type")
				spec = spec_for_type(check_type)
				# 本层只调度 changeset 驱动的规则；包级规则在
				# validation_full_mvp_optimized 中调度（需要 package_files）。
				if spec is None or spec.get("scope") != "changeset":
					continue
				checks[str(check_type)] = run_content_check(
					check,
					fixed_paths=fixed_paths,
					local_root=local_root,
					validation_config=validation_config,
					changeset_changes=changeset_changes,
					module_context=module_context,
				)

	summary = {"error_count": 0, "warning_count": 0, "confirm_count": 0, "skipped_count": 0}
	for result in checks.values():
		if not isinstance(result, dict):
			continue
		error, warning, confirm, skipped = _summary_contribution(result)
		summary["error_count"] += error
		summary["warning_count"] += warning
		summary["confirm_count"] += confirm
		summary["skipped_count"] += skipped
	return {
		"summary": summary,
		"checks": checks,
	}
