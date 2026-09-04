from __future__ import annotations

import json
import time
from typing import Dict, Optional

from changeset_modules import ModuleContext, run_changeset_modules
from packer_core import LogCallback, PackResult, pack_incremental_package, parse_svn_entries
from svn_dtxml_changeset import run_dtxml_changeset
from validation_full_mvp_optimized import run_full_mvp_validations_optimized


def apply_optimized_validation_to_report(
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
	performance = result.report.setdefault("performance", {})
	stages = performance.setdefault("stages", {}) if isinstance(performance, dict) else {}
	log("正在生成 DTXML ChangeSet...", "info")
	changeset_started = time.perf_counter()
	change_set = run_dtxml_changeset(validation_config)
	result.report["change_set"] = change_set
	stages["dtxml_changeset"] = round(time.perf_counter() - changeset_started, 3)
	changeset_changes = None
	if change_set.get("status") in {"passed", "warning"} and isinstance(change_set.get("changes"), list):
		changeset_changes = change_set["changes"]
	else:
		log("DTXML ChangeSet 不可用，提交内容级业务校验（规则 1/2）将跳过。", "warning")
	# 校验与模块解读共享同一个 ModuleContext：活动关联索引只构建一次。
	module_context = ModuleContext(
		tdr_root=str(validation_config.get("tdr_root") or ""),
		region_code=str(validation_config.get("region_code") or "TW"),
	)
	log("正在执行本地 MVP 校验...", "info")
	validation_started = time.perf_counter()
	fixed_paths = [entry.fixed_path for entry in parse_svn_entries(svn_text)]
	validation = run_full_mvp_validations_optimized(
		fixed_paths=fixed_paths,
		local_root=local_root,
		validation_config=validation_config,
		package_files=[entry for entry in result.report.get("files", []) if isinstance(entry, dict)],
		changeset_changes=changeset_changes,
		module_context=module_context,
	)
	result.report["validation"] = validation
	stages["validation"] = round(time.perf_counter() - validation_started, 3)
	log("正在执行 ChangeSet 业务模块解读...", "info")
	module_started = time.perf_counter()
	module_analysis = run_changeset_modules(change_set, validation_config, context=module_context)
	result.report["module_analysis"] = module_analysis
	stages["module_analysis"] = round(time.perf_counter() - module_started, 3)
	if isinstance(performance, dict):
		module_performance = module_analysis.get("performance", {})
		if isinstance(module_performance, dict):
			performance["modules"] = dict(module_performance.get("modules", {}))

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
		report_started = time.perf_counter()
		json.dump(result.report, f, ensure_ascii=False, indent=2)
		f.write("\n")
	stages["report_write"] = round(time.perf_counter() - report_started, 3)

	log(
		"校验结果："
		f"error={error_count}，"
		f"warning={warning_count}，"
		f"confirm={confirm_count}，"
		f"skipped={summary.get('skipped_count', 0)}",
		"info",
	)
	change_summary = change_set.get("summary", {})
	if isinstance(change_summary, dict):
		log(
			"DTXML ChangeSet："
			f"files={change_summary.get('file_count', 0)}，"
			f"sheets={change_summary.get('sheet_count', 0)}，"
			f"changes={change_summary.get('change_count', 0)}，"
			f"errors={change_summary.get('error_count', 0)}",
			"warning" if change_set.get("status") == "warning" else "info",
		)
	module_summary = module_analysis.get("summary", {})
	if isinstance(module_summary, dict):
		log(
			"业务模块解读："
			f"interpreted={module_summary.get('interpreted_change_count', 0)}，"
			f"module_not_found={module_summary.get('module_not_found_count', 0)}，"
			f"deferred={module_summary.get('deferred_change_count', 0)}，"
			f"failed={module_summary.get('module_failed_count', 0)}",
			"warning" if module_analysis.get("status") == "warning" else "info",
		)
	return result


def pack_incremental_package_mvp_optimized(
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
	return apply_optimized_validation_to_report(
		result=result,
		local_root=local_root,
		svn_text=svn_text,
		validation_config=validation_config,
		log=log,
	)
