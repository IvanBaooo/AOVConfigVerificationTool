from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence
from urllib.parse import quote

from packer_core import ParsedSvnEntry, parse_svn_entries
from svn_cli_log_auth import decode_svn_console_output
from svn_commit_validation import parse_revision_spec


LogCallback = Callable[[str, str], None]


class PackSourceError(RuntimeError):
	pass


@dataclass
class PackSourceInspection:
	mode: str
	target_revision: int
	head_revision: int
	selected_file_count: int
	local_root: str
	local_url: str = ""
	warnings: List[str] = field(default_factory=list)
	errors: List[str] = field(default_factory=list)

	@property
	def historical(self) -> bool:
		return self.mode == "historical_revision"

	def to_report(self) -> Dict[str, object]:
		return {
			"mode": self.mode,
			"content_source": "svn_revision_export" if self.historical else "local_latest",
			"target_revision": self.target_revision,
			"repository_head_revision": self.head_revision,
			"selected_file_count": self.selected_file_count,
			"local_root": self.local_root,
			"local_url": self.local_url,
			"warnings": list(self.warnings),
			"errors": list(self.errors),
		}


def _auth_args(*, username: str, password: str, use_auth_cache: bool) -> List[str]:
	args = ["--non-interactive"]
	if not use_auth_cache:
		args.append("--no-auth-cache")
	if username.strip():
		args.extend(["--username", username.strip()])
	if password:
		args.extend(["--password", password])
	return args


def _run(command: Sequence[str], *, timeout: int = 180) -> subprocess.CompletedProcess[bytes]:
	return subprocess.run(list(command), capture_output=True, check=False, timeout=timeout)


def _parse_info(xml_text: str) -> tuple[int, str]:
	try:
		root = ET.fromstring(xml_text)
	except ET.ParseError as error:
		raise PackSourceError(f"无法解析 SVN info：{error}") from error
	entry = root.find("entry")
	if entry is None:
		raise PackSourceError("SVN info 未返回工作副本信息。")
	revision_text = entry.get("revision", "0")
	url = (entry.findtext("url") or "").strip()
	try:
		revision = int(revision_text)
	except ValueError as error:
		raise PackSourceError(f"SVN info 返回了无效 revision：{revision_text}") from error
	return revision, url


def _svn_info(
	target: str,
	*,
	svn_exe: str,
	revision: str = "",
	username: str = "",
	password: str = "",
	use_auth_cache: bool = True,
) -> tuple[int, str]:
	command = [svn_exe, "info", "--xml"]
	if revision:
		command.extend(["-r", revision])
	command.extend(_auth_args(username=username, password=password, use_auth_cache=use_auth_cache))
	command.append(target)
	completed = _run(command)
	if completed.returncode != 0:
		message = decode_svn_console_output(completed.stderr).strip() or "svn info 执行失败"
		raise PackSourceError(message)
	return _parse_info(decode_svn_console_output(completed.stdout))


def _status_errors(xml_text: str) -> List[str]:
	try:
		root = ET.fromstring(xml_text)
	except ET.ParseError as error:
		raise PackSourceError(f"无法解析 SVN status：{error}") from error
	errors: List[str] = []
	for entry in root.findall(".//entry"):
		path = entry.get("path", "")
		wc = entry.find("wc-status")
		if wc is None:
			continue
		item = wc.get("item", "normal")
		if item not in {"normal", "none"}:
			errors.append(f"本地文件状态异常：{path} ({item})")
		if wc.get("switched") == "true":
			errors.append(f"本地文件存在 switched 路径：{path}")
		repository = entry.find("repos-status")
		if repository is not None:
			repository_item = repository.get("item", "none")
			if repository_item not in {"normal", "none"}:
				errors.append(f"本地文件不是仓库最新版本：{path} ({repository_item})")
	return errors


def _check_selected_working_files(
	entries: Sequence[ParsedSvnEntry],
	*,
	local_root: str,
	svn_exe: str,
	username: str,
	password: str,
	use_auth_cache: bool,
) -> List[str]:
	paths = [
		str(Path(local_root, *entry.fixed_path.strip("/").split("/")))
		for entry in entries
		if entry.action != "D"
	]
	missing = [path for path in paths if not Path(path).is_file()]
	if missing:
		return [f"本地打包文件不存在：{path}" for path in missing]
	if not paths:
		return []
	command = [svn_exe, "status", "--xml", "--show-updates"]
	command.extend(_auth_args(username=username, password=password, use_auth_cache=use_auth_cache))
	command.extend(paths)
	completed = _run(command, timeout=300)
	if completed.returncode != 0:
		message = decode_svn_console_output(completed.stderr).strip() or "svn status 执行失败"
		return [message]
	return _status_errors(decode_svn_console_output(completed.stdout))


def inspect_pack_source(
	*,
	svn_text: str,
	current_revision_spec: str,
	content_mode: str = "local_latest",
	local_root: str,
	svn_target: str,
	svn_exe: str = "svn",
	username: str = "",
	password: str = "",
	use_auth_cache: bool = True,
) -> PackSourceInspection:
	entries = parse_svn_entries(svn_text)
	if not entries:
		raise PackSourceError("未找到可检查的 ServerBytes 文件。")
	revisions = parse_revision_spec(current_revision_spec) if current_revision_spec.strip() else []
	target_revision = max(revisions) if revisions else 0
	head_revision, _ = _svn_info(
		svn_target,
		svn_exe=svn_exe,
		revision="HEAD",
		username=username,
		password=password,
		use_auth_cache=use_auth_cache,
	)
	requested_mode = (content_mode or "local_latest").strip().lower()
	if requested_mode not in {"local_latest", "historical_revision"}:
		raise PackSourceError(f"不支持的打包内容模式：{content_mode}")
	mode = requested_mode
	inspection = PackSourceInspection(
		mode=mode,
		target_revision=target_revision,
		head_revision=head_revision,
		selected_file_count=len(entries),
		local_root=local_root,
	)
	if target_revision > head_revision:
		inspection.errors.append(
			f"本次目标 r{target_revision} 高于仓库 HEAD r{head_revision}，请确认 revision 或分支。"
		)
		return inspection
	if inspection.historical:
		if not target_revision:
			inspection.errors.append("历史精确模式必须提供目标 revision。")
			return inspection
		inspection.warnings.append(
			f"历史精确模式：目标 r{target_revision}，仓库 HEAD r{head_revision}；将按 r{target_revision} 精确导出。"
		)
		return inspection
	if target_revision and target_revision < head_revision:
		inspection.warnings.append(
			f"本次选择 r{target_revision}，仓库 HEAD 为 r{head_revision}；Revision 仅用于选文件，包内内容使用已检查的本地最新版本。"
		)

	try:
		_, local_url = _svn_info(local_root, svn_exe=svn_exe)
	except PackSourceError as error:
		inspection.errors.append(f"无法读取本地工作副本：{error}")
		return inspection
	inspection.local_url = local_url
	if local_url.rstrip("/").casefold() != svn_target.rstrip("/").casefold():
		inspection.errors.append(
			f"本地工作副本分支不匹配：本地 {local_url or '未知'}，配置 {svn_target}。"
		)
		return inspection
	inspection.errors.extend(
		_check_selected_working_files(
			entries,
			local_root=local_root,
			svn_exe=svn_exe,
			username=username,
			password=password,
			use_auth_cache=use_auth_cache,
		)
	)
	return inspection


def _cache_path(cache_root: Path, svn_target: str, revision: int, fixed_path: str) -> Path:
	key = f"{svn_target.rstrip('/')}\n{revision}\n{fixed_path}".encode("utf-8")
	return cache_root / str(revision) / f"{hashlib.sha256(key).hexdigest()}.snapshot"


def _file_url(svn_target: str, fixed_path: str) -> str:
	encoded_path = quote(fixed_path.replace("\\", "/"), safe="/:@()+,;=$!~*'")
	return svn_target.rstrip("/") + "/" + encoded_path.lstrip("/")


def _fetch_historical_file(
	entry: ParsedSvnEntry,
	*,
	revision: int,
	svn_target: str,
	svn_exe: str,
	username: str,
	password: str,
	use_auth_cache: bool,
	cache_root: Path,
	destination_root: Path,
) -> bool:
	cache_path = _cache_path(cache_root, svn_target, revision, entry.fixed_path)
	cache_hit = cache_path.is_file()
	if not cache_hit:
		command = [svn_exe, "cat", "-r", str(revision)]
		command.extend(_auth_args(username=username, password=password, use_auth_cache=use_auth_cache))
		command.append(_file_url(svn_target, entry.fixed_path))
		completed = _run(command, timeout=300)
		if completed.returncode != 0:
			message = decode_svn_console_output(completed.stderr).strip() or "svn cat 执行失败"
			raise PackSourceError(f"历史文件导出失败 {entry.fixed_path}：{message}")
		cache_path.parent.mkdir(parents=True, exist_ok=True)
		temp_path = cache_path.with_name(f".{cache_path.name}.{os.getpid()}.tmp")
		temp_path.write_bytes(completed.stdout)
		os.replace(temp_path, cache_path)
	destination = destination_root.joinpath(*entry.fixed_path.strip("/").split("/"))
	destination.parent.mkdir(parents=True, exist_ok=True)
	shutil.copy2(cache_path, destination)
	return cache_hit


@contextmanager
def historical_pack_root(
	inspection: PackSourceInspection,
	*,
	svn_text: str,
	svn_target: str,
	cache_root: str | Path,
	svn_exe: str = "svn",
	username: str = "",
	password: str = "",
	use_auth_cache: bool = True,
	workers: int = 4,
	log: Optional[LogCallback] = None,
) -> Iterator[tuple[str, Dict[str, int]]]:
	if not inspection.historical or not inspection.target_revision:
		raise PackSourceError("只有历史版本模式可以导出 revision 工作目录。")
	entries = [entry for entry in parse_svn_entries(svn_text) if entry.action != "D"]
	log = log or (lambda _message, _level="info": None)
	with tempfile.TemporaryDirectory(prefix=f"aov-pack-r{inspection.target_revision}-") as temporary_directory:
		destination_root = Path(temporary_directory) / "ServerBytes"
		destination_root.mkdir(parents=True, exist_ok=True)
		cache_hits = 0
		completed_count = 0
		with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 8))) as executor:
			futures = [
				executor.submit(
					_fetch_historical_file,
					entry,
					revision=inspection.target_revision,
					svn_target=svn_target,
					svn_exe=svn_exe,
					username=username,
					password=password,
					use_auth_cache=use_auth_cache,
					cache_root=Path(cache_root),
					destination_root=destination_root,
				)
				for entry in entries
			]
			for future in as_completed(futures):
				if future.result():
					cache_hits += 1
				completed_count += 1
				log(f"历史文件导出：{completed_count}/{len(entries)}", "info")
		stats = {
			"file_count": len(entries),
			"cache_hit_count": cache_hits,
			"download_count": len(entries) - cache_hits,
		}
		yield str(destination_root), stats
