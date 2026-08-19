from __future__ import annotations

import hashlib
import json
import os
import tarfile
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional


LogCallback = Callable[[str, str], None]


@dataclass
class ParsedSvnEntry:
	action: str
	fixed_path: str
	raw_line: str


@dataclass
class PackResult:
	base_name: str
	output_dir: str
	tar_path: str
	list_path: str
	md5_path: str
	report_path: str
	md5: str
	sha256: str
	success_count: int
	failure_count: int
	skipped_count: int
	report: Dict[str, object]


class PackagingError(Exception):
	pass


def _noop_log(_message: str, _level: str = "info") -> None:
	return


def parse_svn_entries(svn_text: str) -> List[ParsedSvnEntry]:
	"""Parse SVN changed-path text into ServerBytes-relative paths."""
	results: List[ParsedSvnEntry] = []
	seen = set()

	for raw_line in svn_text.splitlines():
		line = raw_line.strip()
		if not line:
			continue

		action = "M"
		if len(line) > 2 and line[1].isspace() and line[0] in {"A", "M", "D", "R"}:
			action = line[0]
			line = line[2:].strip()

		anchor_idx = line.find("ServerBytes")
		if anchor_idx == -1:
			continue

		after_anchor = line[anchor_idx + len("ServerBytes"):]
		after_anchor = after_anchor.replace("\\", "/")
		if not after_anchor.startswith("/"):
			after_anchor = "/" + after_anchor

		fixed_path = after_anchor.strip()
		while "//" in fixed_path:
			fixed_path = fixed_path.replace("//", "/")

		if fixed_path and fixed_path not in seen:
			seen.add(fixed_path)
			results.append(ParsedSvnEntry(action=action, fixed_path=fixed_path, raw_line=raw_line))

	return results


def build_local_path(local_root: str, fixed_path: str) -> str:
	sub_parts = [p for p in fixed_path.strip("/").split("/") if p]
	return os.path.join(local_root, *sub_parts)


def build_archive_path(archive_root: str, fixed_path: str) -> str:
	arc_root = archive_root.rstrip("/")
	if fixed_path.startswith("/"):
		return f"{arc_root}{fixed_path}"
	return f"{arc_root}/{fixed_path}"


def compute_hash(file_path: str, algorithm: str, chunk_size: int = 1024 * 1024) -> str:
	hash_obj = hashlib.new(algorithm)
	with open(file_path, "rb") as f:
		while True:
			data = f.read(chunk_size)
			if not data:
				break
			hash_obj.update(data)
	return hash_obj.hexdigest()


def _file_info(local_path: str) -> Dict[str, object]:
	stat = os.stat(local_path)
	return {
		"size": stat.st_size,
		"mtime": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
	}


def create_report(
	*,
	base_name: str,
	created_at: str,
	archive_root: str,
	svn_text: str,
	entries: List[Dict[str, object]],
	tar_filename: str,
	list_filename: str,
	md5_filename: str,
	report_filename: str,
	md5: str,
	sha256: str,
	success_count: int,
	failure_count: int,
	skipped_count: int,
) -> Dict[str, object]:
	return {
		"schema_version": "0.1",
		"package_id": base_name,
		"idempotency_key": base_name,
		"created_at": created_at,
		"input": {
			"svn_line_count": len([line for line in svn_text.splitlines() if line.strip()]),
			"parsed_file_count": len(entries),
			"archive_root": archive_root,
		},
		"status": {
			"package_status": "success" if failure_count == 0 else "warning",
			"validation_status": "not_started",
			"ftp_status": "not_required",
			"archive_status": "not_started",
			"mail_status": "not_required",
		},
		"package": {
			"name": tar_filename,
			"md5": md5,
			"sha256": sha256,
			"list_file": list_filename,
			"md5_file": md5_filename,
			"report_file": report_filename,
			"file_count": success_count,
			"failed_count": failure_count,
			"skipped_count": skipped_count,
		},
		"files": entries,
		"validation": {
			"summary": {
				"error_count": 0,
				"warning_count": 0,
				"confirm_count": 0,
				"skipped_count": 0,
			},
			"checks": {},
		},
	}


def pack_incremental_package(
	*,
	svn_text: str,
	local_root: str,
	output_parent: str,
	archive_root: str = "/sgame/gamedata",
	log: Optional[LogCallback] = None,
) -> PackResult:
	log = log or _noop_log

	if not svn_text.strip():
		raise PackagingError("SVN文件列表为空。")
	if not local_root.strip():
		raise PackagingError("本地文件根目录(ServerBytes) 未填写。")
	if not os.path.isdir(local_root):
		raise PackagingError(f"本地文件根目录不存在：{local_root}")

	log("正在分析文件列表...", "info")
	parsed_entries = parse_svn_entries(svn_text)
	if not parsed_entries:
		raise PackagingError("未从 SVN 文件列表中解析到任何有效路径（未匹配到 ServerBytes 锚点）。")

	timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
	created_at = datetime.now().astimezone().isoformat(timespec="seconds")
	base_name = f"sgame_{timestamp}"
	tar_filename = f"{base_name}.tar.gz"
	list_filename = f"{base_name}.list.txt"
	md5_filename = f"{base_name}.md5.txt"
	report_filename = f"{base_name}.report.json"

	output_dir = os.path.join(output_parent, base_name)
	os.makedirs(output_dir, exist_ok=True)
	tar_path = os.path.join(output_dir, tar_filename)
	list_path = os.path.join(output_dir, list_filename)
	md5_path = os.path.join(output_dir, md5_filename)
	report_path = os.path.join(output_dir, report_filename)

	log(f"输出目录：{output_dir}", "info")
	log(f"将生成：{tar_filename}、{list_filename}、{md5_filename}、{report_filename}", "info")

	success_entries: List[Dict[str, object]] = []
	report_entries: List[Dict[str, object]] = []
	failure_count = 0
	skipped_count = 0

	with tarfile.open(tar_path, mode="w:gz") as tar:
		for entry in parsed_entries:
			local_path = build_local_path(local_root, entry.fixed_path)
			archive_path = build_archive_path(archive_root, entry.fixed_path)
			report_entry: Dict[str, object] = {
				"action": entry.action,
				"fixed_path": entry.fixed_path,
				"archive_path": archive_path,
				"raw_line": entry.raw_line,
			}

			if entry.action == "D":
				skipped_count += 1
				report_entry["status"] = "deleted_skipped"
				report_entry["local_exists"] = False
				report_entries.append(report_entry)
				log(f"[跳过] 删除项不参与打包：{entry.fixed_path}", "warning")
				continue

			if not os.path.isfile(local_path):
				failure_count += 1
				report_entry["status"] = "missing"
				report_entry["local_exists"] = False
				report_entries.append(report_entry)
				log(f"[跳过] 本地文件不存在：{local_path}", "warning")
				continue

			try:
				log(f"正在打包：{archive_path} ...", "info")
				tar.add(local_path, arcname=archive_path)
				report_entry["status"] = "packaged"
				report_entry["local_exists"] = True
				report_entry.update(_file_info(local_path))
				success_entries.append(report_entry)
				report_entries.append(report_entry)
			except Exception as add_err:
				failure_count += 1
				report_entry["status"] = "add_failed"
				report_entry["local_exists"] = True
				report_entry["error"] = str(add_err)
				report_entries.append(report_entry)
				log(f"[错误] 添加到压缩包失败：{archive_path} -> {add_err}", "error")

	log("正在生成清单、MD5与报告...", "info")
	with open(list_path, "w", encoding="utf-8") as f_list:
		for entry in success_entries:
			f_list.write(f"{entry['archive_path']}\n")
		f_list.write("\n")
		f_list.write(f"共{len(success_entries)}行\n")

	md5 = compute_hash(tar_path, "md5")
	sha256 = compute_hash(tar_path, "sha256")
	with open(md5_path, "w", encoding="utf-8") as f_md5:
		f_md5.write(f"{md5}  {os.path.basename(tar_path)}\n")

	report = create_report(
		base_name=base_name,
		created_at=created_at,
		archive_root=archive_root,
		svn_text=svn_text,
		entries=report_entries,
		tar_filename=tar_filename,
		list_filename=list_filename,
		md5_filename=md5_filename,
		report_filename=report_filename,
		md5=md5,
		sha256=sha256,
		success_count=len(success_entries),
		failure_count=failure_count,
		skipped_count=skipped_count,
	)
	with open(report_path, "w", encoding="utf-8") as f_report:
		json.dump(report, f_report, ensure_ascii=False, indent=2)
		f_report.write("\n")

	return PackResult(
		base_name=base_name,
		output_dir=output_dir,
		tar_path=tar_path,
		list_path=list_path,
		md5_path=md5_path,
		report_path=report_path,
		md5=md5,
		sha256=sha256,
		success_count=len(success_entries),
		failure_count=failure_count,
		skipped_count=skipped_count,
		report=report,
	)
