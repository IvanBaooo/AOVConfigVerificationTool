from __future__ import annotations

from typing import Dict, List, Optional

from svn_commit_validation import (
	normalize_fixed_path,
	parse_revision_spec,
	parse_svn_log_text,
	run_commit_record_check,
)
from svn_path_policy import (
	matching_whitelist_pattern,
	parse_whitelist_patterns,
	path_matches_whitelist,
)


def _commit_config(validation_config: Optional[Dict[str, object]]) -> Dict[str, object]:
	if not validation_config:
		return {}
	value = validation_config.get("commit_record")
	if isinstance(value, dict):
		return value
	value = validation_config.get("commit_record_check")
	if isinstance(value, dict):
		return value
	return {}


def _as_string_list(value: object) -> List[str]:
	return parse_whitelist_patterns(value)


def _normalize_whitelist_pattern(pattern: str) -> str:
	value = pattern.strip().strip('"').replace("\\", "/")
	fixed = normalize_fixed_path(value)
	if fixed:
		return fixed
	while "//" in value:
		value = value.replace("//", "/")
	return value


def _path_matches_whitelist(fixed_path: str, pattern: str) -> bool:
	return path_matches_whitelist(fixed_path, pattern)


def _is_whitelisted_warning(warning: Dict[str, object], patterns: List[str]) -> bool:
	fixed_path = str(warning.get("fixed_path") or "").strip()
	if not fixed_path:
		return False
	return any(_path_matches_whitelist(fixed_path, pattern) for pattern in patterns)


def _append_reverse_revision_warning(result: Dict[str, object], config: Dict[str, object]) -> None:
	try:
		current_revisions = parse_revision_spec(str(config.get("current_revision_spec") or ""))
		last_external_revisions = parse_revision_spec(str(config.get("last_external_revision_spec") or ""))
	except Exception:
		return
	if not current_revisions or not last_external_revisions:
		return

	baseline_max = max(last_external_revisions)
	current_max = max(current_revisions)
	if baseline_max <= current_max:
		return

	warnings = result.setdefault("warnings", [])
	if not isinstance(warnings, list):
		return
	warnings.insert(0, {
		"type": "baseline_revision_after_current",
		"level": "warning",
		"input_method": result.get("input_method", config.get("input_method", "")),
		"message": "上次对外 revision 大于本次打包 revision，无法按正常时间线计算两次对外之间的遗漏提交，请确认输入是否写反或是否跨分支。",
		"last_external_revision": baseline_max,
		"current_max_revision": current_max,
	})


def _collect_log_statistics(config: Dict[str, object]) -> Dict[str, object]:
	svn_log_text = str(config.get("svn_log_text") or "")
	if not svn_log_text.strip():
		return {
			"svn_log_provided": False,
			"svn_log_returned_revision_count": 0,
		}
	changes = parse_svn_log_text(svn_log_text)
	revisions = sorted({change.revision for change in changes})
	return {
		"svn_log_provided": True,
		"svn_log_returned_revision_count": len(revisions),
		"svn_log_min_revision": revisions[0] if revisions else None,
		"svn_log_max_revision": revisions[-1] if revisions else None,
	}


def _table_summaries(warnings: List[Dict[str, object]]) -> List[Dict[str, object]]:
	tables: List[Dict[str, object]] = []
	seen = set()
	for warning in warnings:
		fixed_path = str(warning.get("fixed_path") or "")
		if not fixed_path or fixed_path in seen:
			continue
		seen.add(fixed_path)
		tables.append({
			"module": warning.get("module", ""),
			"table_name": warning.get("table_name", ""),
			"readable_name": warning.get("readable_name", ""),
			"directory": warning.get("directory", ""),
			"file_name": warning.get("file_name", ""),
			"fixed_path": fixed_path,
			"mapping_source": warning.get("mapping_source", "file_name"),
		})
	return tables

def run_commit_record_check_optimized(
	*,
	fixed_paths: List[str],
	validation_config: Optional[Dict[str, object]],
) -> Dict[str, object]:
	result = run_commit_record_check(
		fixed_paths=fixed_paths,
		validation_config=validation_config,
	)
	config = _commit_config(validation_config)
	_append_reverse_revision_warning(result, config)

	whitelist_patterns = _as_string_list(
		config.get("whitelist_paths")
		or config.get("ignore_paths")
		or config.get("path_whitelist")
		or []
	)
	statistics = dict(result.get("statistics", {}) if isinstance(result.get("statistics"), dict) else {})
	statistics.update(_collect_log_statistics(config))
	statistics["whitelist_patterns"] = whitelist_patterns

	warnings = result.get("warnings", [])
	if not isinstance(warnings, list):
		result["statistics"] = statistics
		return result

	kept_warnings: List[Dict[str, object]] = []
	filtered_unresolved: List[Dict[str, object]] = []
	filtered_whitelist: List[Dict[str, object]] = []

	for warning in warnings:
		if not isinstance(warning, dict):
			continue
		if warning.get("type") == "unresolved_revision_gap":
			filtered_unresolved.append(warning)
			continue
		matched_pattern = matching_whitelist_pattern(
			str(warning.get("fixed_path") or ""),
			whitelist_patterns,
		)
		if matched_pattern:
			ignored_warning = dict(warning)
			ignored_warning["resolution"] = "ignored_by_whitelist"
			ignored_warning["whitelist_pattern"] = matched_pattern
			filtered_whitelist.append(ignored_warning)
			continue
		kept_warnings.append(warning)

	unresolved_revisions: List[int] = []
	for warning in filtered_unresolved:
		revisions = warning.get("revisions")
		if isinstance(revisions, list):
			for revision in revisions:
				try:
					unresolved_revisions.append(int(revision))
				except Exception:
					continue

	statistics["filtered_unresolved_revision_count"] = len(unresolved_revisions)
	statistics["filtered_unresolved_revision_sample"] = unresolved_revisions[:20]
	statistics["whitelisted_warning_count"] = len(filtered_whitelist)
	statistics["whitelisted_paths"] = [
		str(warning.get("fixed_path") or "")
		for warning in filtered_whitelist
		if warning.get("fixed_path")
	]

	result["warnings"] = kept_warnings
	result["ignored_changes"] = filtered_whitelist
	result["affected_tables"] = _table_summaries(kept_warnings)
	result["ignored_tables"] = _table_summaries(filtered_whitelist)
	result["warning_count"] = len(kept_warnings)
	result["statistics"] = statistics
	if result.get("status") == "warning" and not kept_warnings:
		result["status"] = "passed"
	return result
