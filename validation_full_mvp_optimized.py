from __future__ import annotations

from typing import Dict, List, Optional

from svn_commit_validation_optimized import run_commit_record_check_optimized
from validation_mvp import run_mvp_validations


def _empty_summary() -> Dict[str, int]:
	return {
		"error_count": 0,
		"warning_count": 0,
		"confirm_count": 0,
		"skipped_count": 0,
	}


def _merge_summary(base: Dict[str, object], *extra_results: Dict[str, object]) -> Dict[str, int]:
	summary = _empty_summary()
	base_summary = base.get("summary", {})
	if isinstance(base_summary, dict):
		for key in summary:
			summary[key] += int(base_summary.get(key, 0) or 0)

	for extra in extra_results:
		if not isinstance(extra, dict):
			continue
		status = str(extra.get("status") or "")
		if status == "error":
			summary["error_count"] += 1
		elif status == "warning":
			summary["warning_count"] += int(extra.get("warning_count", 0) or 0) or 1
		elif status == "confirm":
			summary["confirm_count"] += int(extra.get("item_count", 0) or 0) or 1
		elif status == "skipped":
			summary["skipped_count"] += 1
	return summary


def run_full_mvp_validations_optimized(
	*,
	fixed_paths: List[str],
	local_root: str,
	validation_config: Optional[Dict[str, object]],
	package_files: Optional[List[Dict[str, object]]] = None,
	changeset_changes: Optional[List[Dict[str, object]]] = None,
	module_context: Optional[object] = None,
) -> Dict[str, object]:
	from rules.registry import all_rule_specs, run_content_check

	base = run_mvp_validations(
		fixed_paths=fixed_paths,
		local_root=local_root,
		validation_config=validation_config,
		changeset_changes=changeset_changes,
		module_context=module_context,
	)
	commit_result = run_commit_record_check_optimized(
		fixed_paths=fixed_paths,
		validation_config=validation_config,
	)

	checks = {}
	base_checks = base.get("checks", {})
	if isinstance(base_checks, dict):
		checks.update(base_checks)
	checks["commit_record"] = commit_result

	package_results: List[Dict[str, object]] = []
	content_checks = validation_config.get("content_checks") if isinstance(validation_config, dict) else None
	if isinstance(content_checks, list):
		# 注册表驱动的包级规则调度（scope=="package"）
		for spec in all_rule_specs():
			if spec.get("scope") != "package":
				continue
			package_check = next((
				check for check in content_checks
				if isinstance(check, dict)
				and check.get("type") == spec.get("type")
				and check.get("enabled") is True
			), None)
			if package_check is None:
				continue
			package_result = run_content_check(
				package_check,
				fixed_paths=fixed_paths,
				validation_config=validation_config,
				package_files=package_files,
			)
			checks[str(spec["type"])] = package_result
			package_results.append(package_result)

	rule_set_value = validation_config.get("rule_set") if isinstance(validation_config, dict) else None
	rule_set = dict(rule_set_value) if isinstance(rule_set_value, dict) else {}
	return {
		"summary": _merge_summary(base, commit_result, *package_results),
		"rule_set": rule_set,
		"checks": checks,
	}
