from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

try:
	from lxml import etree as ET  # type: ignore
except Exception:  # pragma: no cover - fallback for minimal local Python envs.
	import xml.etree.ElementTree as ET  # type: ignore


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


def resolve_rule_dtxml_path(tdr_root: str, relative_path: str, region_code: str) -> str:
	relative = relative_path.replace("{region}", region_code.upper()).replace("/", os.sep).replace("\\", os.sep)
	relative = relative.lstrip(os.sep)
	resolved_root = os.path.abspath(tdr_root)
	resolved_path = os.path.abspath(os.path.join(resolved_root, relative))
	if os.path.commonpath([resolved_root, resolved_path]) != resolved_root:
		raise ValueError("DTXML 规则路径不能离开 TdrTable 根目录。")
	return resolved_path


def _status_item_count(result: Dict[str, object]) -> int:
	item_count = result.get("item_count")
	if isinstance(item_count, int) and not isinstance(item_count, bool) and item_count > 0:
		return item_count
	if result.get("status") == "warning":
		warning_count = result.get("warning_count")
		if isinstance(warning_count, int) and not isinstance(warning_count, bool) and warning_count > 0:
			return warning_count
	return 1


def _summary_contribution(result: Dict[str, object]) -> Tuple[int, int, int, int]:
	status = result.get("status")
	if status == "error":
		return _status_item_count(result), 0, 0, 0
	if status == "warning":
		return 0, _status_item_count(result), 0, 0
	if status == "confirm":
		return 0, 0, _status_item_count(result), 0
	if status == "skipped":
		return 0, 0, 0, 1
	return 0, 0, 0, 0


def run_mvp_validations(
	*,
	fixed_paths: List[str],
	local_root: str,
	validation_config: Optional[Dict[str, object]],
	changeset_changes: Optional[List[Dict[str, object]]] = None,
	module_context: Optional[object] = None,
) -> Dict[str, object]:
	from rules.registry import run_content_check, spec_for_type

	checks: Dict[str, object] = {}

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
