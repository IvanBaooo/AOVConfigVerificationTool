"""规则：手动粘贴 bytes list 场景的包完整性（package_completeness，I2 凡恩遗漏、I4 拉维尔空包）。"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional


def run_package_completeness(
    *,
    fixed_paths: List[str],
    validation_config: Optional[Dict[str, object]],
    package_files: Optional[List[Dict[str, object]]],
    check: Mapping[str, object],
) -> Dict[str, object]:
    """规则 3：手动粘贴 bytes list 场景的输入清单与包内容一一对应。

    SVN 提交模式（revision_spec）已由 commit_record 差异校验覆盖，本规则跳过。
    说明：D（删除）条目的 deleted_skipped 属于正常结果，不计入 skipped。
    """
    commit_config = validation_config.get("commit_record") if isinstance(validation_config, dict) else None
    input_method = str(commit_config.get("input_method") or "pasted_svn_file_list") if isinstance(commit_config, dict) else "pasted_svn_file_list"
    if input_method != "pasted_svn_file_list":
        return {
            "status": "skipped",
            "reason": "svn_mode_covered_by_commit_record",
            "message": "SVN 提交模式已由 commit_record 差异校验覆盖，包完整性校验仅适用于手动粘贴 bytes list。",
            "input_method": input_method,
            "items": [],
            "warnings": [],
        }

    params = check.get("params")
    min_file_count = 1
    min_total_bytes = 1024
    if isinstance(params, dict):
        try:
            min_file_count = int(params.get("min_file_count", min_file_count))
            min_total_bytes = int(params.get("min_total_bytes", min_total_bytes))
        except (TypeError, ValueError):
            pass

    files = [entry for entry in (package_files or []) if isinstance(entry, dict)]
    packaged = [entry for entry in files if entry.get("status") == "packaged"]
    failed = [entry for entry in files if entry.get("status") == "failed"]
    skipped = [entry for entry in files if entry.get("status") == "skipped"]
    deleted = [entry for entry in files if entry.get("status") == "deleted_skipped"]
    total_bytes = sum(int(entry.get("size", 0) or 0) for entry in packaged)

    input_count = len(fixed_paths)
    warnings: List[Dict[str, object]] = []

    missing = [entry for entry in files if entry.get("status") not in {"packaged", "deleted_skipped"}]
    if failed:
        warnings.append({
            "type": "package_files_failed",
            "level": "warning",
            "message": f"有 {len(failed)} 个文件打包失败。",
            "paths": [str(entry.get("fixed_path") or "") for entry in failed],
        })
    if skipped:
        warnings.append({
            "type": "package_files_skipped",
            "level": "warning",
            "message": f"有 {len(skipped)} 个输入文件未打入包内（被跳过）。",
            "paths": [str(entry.get("fixed_path") or "") for entry in skipped],
        })
    if len(packaged) + len(deleted) != input_count:
        warnings.append({
            "type": "package_count_mismatch",
            "level": "warning",
            "message": f"输入清单 {input_count} 个文件，包内仅 {len(packaged)} 个（另有 {len(deleted)} 个删除条目）。",
            "missing_paths": [str(entry.get("fixed_path") or "") for entry in missing],
        })
    if input_count >= 1 and (len(packaged) < min_file_count or total_bytes < min_total_bytes):
        warnings.append({
            "type": "package_suspected_empty",
            "level": "warning",
            "message": (
                f"疑似空包：输入 {input_count} 个文件，实际打入 {len(packaged)} 个、共 {total_bytes} 字节；"
                "请核对打包路径配置（历史 I4 空包问题模式）。"
            ),
            "packaged_count": len(packaged),
            "total_bytes": total_bytes,
        })

    return {
        "status": "warning" if warnings else "passed",
        "rule_id": check.get("id", "package-completeness-manual"),
        "input_method": input_method,
        "input_count": input_count,
        "packaged_count": len(packaged),
        "failed_count": len(failed),
        "skipped_count": len(skipped),
        "deleted_count": len(deleted),
        "total_bytes": total_bytes,
        "warning_count": len(warnings),
        "items": [],
        "warnings": warnings,
    }
