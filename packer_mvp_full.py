from __future__ import annotations

import json
from typing import Dict, Optional

from packer_core import LogCallback, PackResult, pack_incremental_package, parse_svn_entries
from validation_full_mvp import run_full_mvp_validations


def apply_full_validation_to_report(
	*,
	result: PackResult,
	local_root: str,
	svn_text: str,
	validation_config: Optional[Dict[str, object]],
	log: Optional[LogCallback] = None,
) -> PackResult:
	if validation_config is None:
		return result

	log = log or (lambda _message, _level="info": None)
	log("正在执行本地 MVP 校验...", "info")
	fixed_paths = [entry.fixed_path for entry in parse_svn_entries(svn_text)]
	validation = run_full_mvp_validations(
		fixed_paths=fixed_paths,
		local_root=local_root,
		validation_config=validation_config,
	)
	result.report["validation"] = validation

	summary = validation.get("summary", {})
	error_count = int(summary.get("error_count", 0) or 0)
	warning_count = int(summary.get("warning_count", 0) or 0)
	confirm_count = int(summary.get("confirm_count", 0) or 0)
	if error_count:
		result.report["status"]["validation_status"] = "failed"  # type: ignore[index]
	elif warning_count:
		result.report["status"]["validation_status"] = "warning"  # type: ignore[index]
	elif confirm_count:
		result.report["status"]["validation_status"] = "confirm"  # type: ignore[index]
	else:
		result.report["status"]["validation_status"] = "passed"  # type: ignore[index]

	with open(result.report_path, "w", encoding="utf-8") as f:
		json.dump(result.report, f, ensure_ascii=False, indent=2)
		f.write("\n")

	log(
		"校验结果："
		f"error={error_count}，"
		f"warning={warning_count}，"
		f"confirm={confirm_count}，"
		f"skipped={summary.get('skipped_count', 0)}",
		"info",
	)
	return result


def pack_incremental_package_mvp_full(
	*,
	svn_text: str,
	local_root: str,
	output_parent: str,
	validation_config: Optional[Dict[str, object]] = None,
	log: Optional[LogCallback] = None,
) -> PackResult:
	result = pack_incremental_package(
		svn_text=svn_text,
		local_root=local_root,
		output_parent=output_parent,
		log=log,
	)
	return apply_full_validation_to_report(
		result=result,
		local_root=local_root,
		svn_text=svn_text,
		validation_config=validation_config,
		log=log,
	)
