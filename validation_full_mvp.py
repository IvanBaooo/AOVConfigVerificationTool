from __future__ import annotations

from typing import Dict, List, Optional

from svn_commit_validation import run_commit_record_check
from validation_mvp import run_mvp_validations


def _empty_summary() -> Dict[str, int]:
	return {
		"error_count": 0,
		"warning_count": 0,
		"confirm_count": 0,
		"skipped_count": 0,
	}


def _merge_summary(base: Dict[str, object], commit_result: Dict[str, object]) -> Dict[str, int]:
	summary = _empty_summary()
	base_summary = base.get("summary", {})
	if isinstance(base_summary, dict):
		for key in summary:
			summary[key] += int(base_summary.get(key, 0) or 0)

	status = str(commit_result.get("status") or "")
	if status == "error":
		summary["error_count"] += 1
	elif status == "warning":
		summary["warning_count"] += int(commit_result.get("warning_count", 0) or 0) or 1
	elif status == "skipped":
		summary["skipped_count"] += 1
	return summary


def run_full_mvp_validations(
	*,
	fixed_paths: List[str],
	local_root: str,
	validation_config: Optional[Dict[str, object]],
) -> Dict[str, object]:
	base = run_mvp_validations(
		fixed_paths=fixed_paths,
		local_root=local_root,
		validation_config=validation_config,
	)
	commit_result = run_commit_record_check(
		fixed_paths=fixed_paths,
		validation_config=validation_config,
	)

	checks = {}
	base_checks = base.get("checks", {})
	if isinstance(base_checks, dict):
		checks.update(base_checks)
	checks["commit_record"] = commit_result

	return {
		"summary": _merge_summary(base, commit_result),
		"checks": checks,
	}
