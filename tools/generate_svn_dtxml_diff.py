import argparse
import json
import os
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence
from urllib.parse import quote

from changeset_modules import run_changeset_modules
from svn_dtxml_changeset import build_dtxml_changeset, infer_tdr_svn_target


PASSWORD_ENV = "AOV_SVN_PASSWORD"


def _svn_command(
	args: Sequence[str],
	*,
	svn_exe: str,
	username: str,
	password: str,
) -> List[str]:
	command = [svn_exe, *args, "--non-interactive", "--no-auth-cache"]
	if username:
		command.extend(["--username", username])
	if password:
		command.extend(["--password", password])
	return command


def _run_svn(
	args: Sequence[str],
	*,
	svn_exe: str,
	username: str,
	password: str,
) -> bytes:
	completed = subprocess.run(
		_svn_command(args, svn_exe=svn_exe, username=username, password=password),
		capture_output=True,
		check=False,
	)
	if completed.returncode != 0:
		message = completed.stderr.decode("utf-8", errors="replace").strip()
		raise RuntimeError(message or f"svn exited with code {completed.returncode}")
	return completed.stdout


def compact_changeset(changeset: Mapping[str, object], revision: int) -> Dict[str, object]:
	compact_changes: List[Dict[str, object]] = []
	for source in changeset.get("changes", []):
		if not isinstance(source, Mapping):
			continue
		change_type = str(source.get("change_type", ""))
		item: Dict[str, object] = {
			"file_name": source.get("file_name"),
			"repository_path": source.get("repository_path"),
			"sheet": source.get("sheet"),
			"business_key": source.get("business_key"),
			"change_type": change_type,
			"revisions": source.get("revisions", []),
			"semantic_analysis": source.get("semantic_analysis", {"status": "eligible"}),
		}
		before = source.get("before") if isinstance(source.get("before"), Mapping) else {}
		after = source.get("after") if isinstance(source.get("after"), Mapping) else {}
		if change_type == "added":
			item["values"] = after
		elif change_type == "deleted":
			item["previous_values"] = before
		else:
			fields: Dict[str, Dict[str, object]] = {}
			for field in source.get("changed_fields", []):
				field_name = str(field)
				fields[field_name] = {
					"before": before.get(field_name, ""),
					"after": after.get(field_name, ""),
				}
			item["fields"] = fields
		compact_changes.append(item)

	return {
		"schema_version": "aov-dtxml-compact-changeset/v1",
		"revision": revision,
		"status": changeset.get("status"),
		"selection": changeset.get("selection"),
		"scope": changeset.get("scope"),
		"summary": changeset.get("summary"),
		"changes": compact_changes,
		"deferred_changes": changeset.get("deferred_changes", []),
		"errors": changeset.get("errors", []),
	}


def _md(value: object) -> str:
	return str(value if value is not None else "").replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def _changed_field_names(change: Mapping[str, object]) -> Iterable[str]:
	fields = change.get("fields")
	if isinstance(fields, Mapping):
		return [str(field) for field in fields]
	values = change.get("values") or change.get("previous_values")
	if isinstance(values, Mapping):
		return [str(field) for field in values]
	return []


def render_summary(compact: Mapping[str, object]) -> str:
	summary = compact.get("summary") if isinstance(compact.get("summary"), Mapping) else {}
	changes = [item for item in compact.get("changes", []) if isinstance(item, Mapping)]
	file_counts: Dict[str, Counter] = defaultdict(Counter)
	sheet_counts: Dict[tuple, Counter] = defaultdict(Counter)
	field_counts: Counter = Counter()
	for change in changes:
		change_type = str(change.get("change_type", "unknown"))
		file_name = str(change.get("file_name", ""))
		sheet_name = str(change.get("sheet", ""))
		file_counts[file_name][change_type] += 1
		sheet_counts[(file_name, sheet_name)][change_type] += 1
		field_counts.update(_changed_field_names(change))

	lines = [
		f"# r{compact.get('revision')} DTXML 变更摘要",
		"",
		"> 对比范围：r{0} 与 r{1}，仅统计所选区域的 DTXML。".format(
			int(compact.get("revision", 0)) - 1,
			compact.get("revision"),
		),
		"",
		"## 总览",
		"",
		f"- 涉及文件：{summary.get('file_count', 0)}",
		f"- 涉及 Sheet：{summary.get('sheet_count', 0)}",
		f"- 行级变更：{summary.get('change_count', 0)}",
		f"- 新增：{summary.get('added_count', 0)}",
		f"- 修改：{summary.get('modified_count', 0)}",
		f"- 删除：{summary.get('deleted_count', 0)}",
		f"- 暂缓业务解读的 Sheet：{summary.get('deferred_change_count', 0)}",
		f"- 暂缓业务解读的行级变更：{summary.get('deferred_row_change_count', 0)}",
		f"- 解析错误：{summary.get('error_count', 0)}",
		"",
		"## 按文件统计",
		"",
		"| 文件 | 新增 | 修改 | 删除 | 合计 |",
		"|---|---:|---:|---:|---:|",
	]
	for file_name, counts in sorted(file_counts.items(), key=lambda item: (-sum(item[1].values()), item[0])):
		lines.append(
			f"| {_md(file_name)} | {counts['added']} | {counts['modified']} | {counts['deleted']} | {sum(counts.values())} |"
		)

	lines.extend(["", "## 按 Sheet 统计", "", "| 文件 | Sheet | 新增 | 修改 | 删除 | 合计 |", "|---|---|---:|---:|---:|---:|"])
	for (file_name, sheet_name), counts in sorted(sheet_counts.items(), key=lambda item: (-sum(item[1].values()), item[0])):
		lines.append(
			f"| {_md(file_name)} | {_md(sheet_name)} | {counts['added']} | {counts['modified']} | {counts['deleted']} | {sum(counts.values())} |"
		)

	lines.extend(["", "## 高频变更字段", "", "| 字段 | 涉及行数 |", "|---|---:|"])
	for field, count in field_counts.most_common(30):
		lines.append(f"| {_md(field)} | {count} |")

	deferred = [item for item in compact.get("deferred_changes", []) if isinstance(item, Mapping)]
	if deferred:
		lines.extend(["", "## 暂缓分析", "", "| 文件 | Sheet | Revision |", "|---|---|---:|"])
		for item in deferred:
			lines.append(
				f"| {_md(item.get('file_name'))} | {_md(item.get('sheet'))} | {item.get('revision', '')} |"
			)

	modified_changes = [change for change in changes if change.get("change_type") == "modified"]
	lines.extend(["", "## 修改明细", ""])
	lines.append("新增行的完整字段保存在 `changeset.json`，此处仅展开已有配置的字段修改。")
	lines.append("")
	for index, change in enumerate(modified_changes, start=1):
		business_key = change.get("business_key")
		if isinstance(business_key, Mapping):
			key_text = business_key.get("display", "")
		else:
			key_text = business_key or ""
		lines.append(
			f"### {index}. {_md(change.get('file_name'))} / {_md(change.get('sheet'))} / {_md(key_text)}"
		)
		lines.append("")
		lines.append(f"- 类型：{_md(change.get('change_type'))}")
		fields = change.get("fields")
		if isinstance(fields, Mapping):
			lines.extend(["", "| 字段 | 修改前 | 修改后 |", "|---|---|---|"])
			for field, values in fields.items():
				values = values if isinstance(values, Mapping) else {}
				lines.append(f"| {_md(field)} | {_md(values.get('before'))} | {_md(values.get('after'))} |")
		lines.append("")
	return "\n".join(lines)


def main() -> int:
	parser = argparse.ArgumentParser(description="Export one SVN revision as DTXML diff artifacts.")
	parser.add_argument("--revision", type=int, required=True)
	parser.add_argument("--svn-target", required=True)
	parser.add_argument("--region", required=True)
	parser.add_argument("--svn-exe", default="svn")
	parser.add_argument("--username", default="")
	parser.add_argument("--tdr-root", default="")
	parser.add_argument("--output-dir", type=Path, required=True)
	args = parser.parse_args()

	password = os.environ.get(PASSWORD_ENV, "")
	if args.username and not password:
		raise RuntimeError(f"Set {PASSWORD_ENV} for authenticated SVN access.")

	tdr_target = infer_tdr_svn_target(args.svn_target).rstrip("/")
	log_bytes = _run_svn(
		["log", "--xml", "-v", "-r", str(args.revision), tdr_target],
		svn_exe=args.svn_exe,
		username=args.username,
		password=password,
	)
	log_text = log_bytes.decode("utf-8")
	changeset = build_dtxml_changeset(
		log_text=log_text,
		revision_spec=f"r{args.revision}",
		tdr_svn_target=tdr_target,
		region_code=args.region,
		svn_exe=args.svn_exe,
		username=args.username,
		password=password,
		use_auth_cache=False,
	)
	module_analysis = run_changeset_modules(changeset, {
		"tdr_root": args.tdr_root,
		"region_code": args.region,
	})
	compact = compact_changeset(changeset, args.revision)

	region_path = quote(args.region.upper(), safe="")
	diff_target = f"{tdr_target}/Xml/Garena/{region_path}/CommonCore"
	diff_bytes = _run_svn(
		["diff", "-c", str(args.revision), diff_target],
		svn_exe=args.svn_exe,
		username=args.username,
		password=password,
	)

	args.output_dir.mkdir(parents=True, exist_ok=True)
	prefix = f"r{args.revision}"
	paths = {
		"svn_log": args.output_dir / f"{prefix}.svn-log.xml",
		"raw_diff": args.output_dir / f"{prefix}.dtxml.diff",
		"changeset": args.output_dir / f"{prefix}.changeset.json",
		"module_analysis": args.output_dir / f"{prefix}.module-analysis.json",
		"summary": args.output_dir / f"{prefix}.summary.md",
	}
	paths["svn_log"].write_bytes(log_bytes)
	paths["raw_diff"].write_bytes(diff_bytes)
	paths["changeset"].write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")
	paths["module_analysis"].write_text(
		json.dumps(module_analysis, ensure_ascii=False, indent=2),
		encoding="utf-8",
	)
	paths["summary"].write_text(render_summary(compact), encoding="utf-8")

	print(json.dumps({
		"status": compact.get("status"),
		"summary": compact.get("summary"),
		"outputs": {name: str(path.resolve()) for name, path in paths.items()},
		"sizes": {name: path.stat().st_size for name, path in paths.items()},
	}, ensure_ascii=False))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
