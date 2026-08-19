from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as XmlET
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from svn_commit_validation import RevisionSpecError, parse_revision_spec


CHANGESET_SCHEMA_VERSION = "aov-dtxml-changeset/v1"
DEFAULT_KEY_CANDIDATES = (
	"ID",
	"配置ID",
	"活动ID",
	"任务ID",
	"道具ID",
	"皮肤ID",
	"促销特卖ID",
	"随机奖励ID",
	"序号",
)
DEFAULT_PROJECT_KEY_MAPPINGS: Dict[str, object] = {
	"日常活动表.dtxml::兑换活动表": ["活动ID", "活动索引"],
}
DEFAULT_DEFERRED_SHEETS = (
	"活动抽奖表.dtxml::*",
	"用户活跃标签.dtxml::*",
)


@dataclass(frozen=True)
class RepositoryChangedPath:
	revision: int
	action: str
	path: str


class SvnContentReadError(RuntimeError):
	pass


ContentLoader = Callable[[str, int], bytes]


def _clean_changed_path(path: str) -> str:
	return re.sub(r"\s+\(from\s+.+\)$", "", (path or "").strip()).replace("\\", "/")


def infer_tdr_svn_target(svn_target: str) -> str:
	"""Collapse a ServerBytes target back to the enclosing TdrTable URL."""
	target = (svn_target or "").strip().rstrip("/")
	if not target:
		return ""
	match = re.search(r"/ServerBytes(?:/.*)?$", target, flags=re.IGNORECASE)
	if match:
		return target[:match.start()]
	return target


def resolve_changed_path_url(tdr_svn_target: str, changed_path: str) -> str:
	target = infer_tdr_svn_target(tdr_svn_target)
	path = _clean_changed_path(changed_path)
	if not target or not path:
		raise ValueError("SVN target and changed path are required.")
	if re.match(r"^https?://", path, flags=re.IGNORECASE):
		return path

	marker = "/Tools/TdrTable"
	marker_index = path.casefold().find(marker.casefold())
	if marker_index >= 0:
		suffix = path[marker_index + len(marker):].lstrip("/")
		return target.rstrip("/") + ("/" + suffix if suffix else "")

	parsed = urlsplit(target)
	target_path = parsed.path.rstrip("/")
	if path.startswith(target_path + "/") or path == target_path:
		return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
	raise ValueError(f"Cannot resolve changed path below TdrTable: {changed_path}")


def encode_svn_url(url: str) -> str:
	"""Encode non-ASCII SVN URL paths before passing them to Windows svn.exe."""
	parsed = urlsplit(url)
	encoded_path = quote(unquote(parsed.path), safe="/%:@!$&'()*+,;=-._~")
	return urlunsplit((parsed.scheme, parsed.netloc, encoded_path, parsed.query, parsed.fragment))


def _parse_text_changed_paths(log_text: str) -> List[RepositoryChangedPath]:
	results: List[RepositoryChangedPath] = []
	current_revision: Optional[int] = None
	in_changed_paths = False
	for raw_line in log_text.splitlines():
		line = raw_line.rstrip()
		header = re.match(r"^r(\d+)\s+\|", line.strip())
		if header:
			current_revision = int(header.group(1))
			in_changed_paths = False
			continue
		if current_revision is None:
			continue
		if line.strip() == "Changed paths:":
			in_changed_paths = True
			continue
		if not in_changed_paths:
			continue
		if not line.strip():
			in_changed_paths = False
			continue
		match = re.match(r"^\s*([AMDR])\s+(.+?)\s*$", line)
		if match:
			results.append(RepositoryChangedPath(current_revision, match.group(1), _clean_changed_path(match.group(2))))
	return results


def _parse_xml_changed_paths(log_text: str) -> List[RepositoryChangedPath]:
	root = XmlET.fromstring(log_text)
	results: List[RepositoryChangedPath] = []
	for entry in root.findall(".//logentry"):
		revision = entry.get("revision")
		if not revision:
			continue
		for node in entry.findall("./paths/path"):
			path = (node.text or "").strip()
			if path:
				results.append(RepositoryChangedPath(int(revision), node.get("action") or "M", _clean_changed_path(path)))
	return results


def parse_repository_changed_paths(log_text: str) -> List[RepositoryChangedPath]:
	text = (log_text or "").strip()
	if not text:
		return []
	if text.startswith("<"):
		return _parse_xml_changed_paths(text)
	return _parse_text_changed_paths(text)


class SvnCatClient:
	def __init__(
		self,
		*,
		tdr_svn_target: str,
		svn_exe: str = "svn",
		username: str = "",
		password: str = "",
		use_auth_cache: bool = True,
	) -> None:
		self.tdr_svn_target = infer_tdr_svn_target(tdr_svn_target)
		self.svn_exe = (svn_exe or "svn").strip() or "svn"
		self.username = username.strip()
		self.password = password
		self.use_auth_cache = use_auth_cache

	def read(self, changed_path: str, revision: int) -> bytes:
		url = encode_svn_url(resolve_changed_path_url(self.tdr_svn_target, changed_path))
		command = [self.svn_exe, "cat", "--non-interactive", "-r", str(revision)]
		safe_command = list(command)
		if not self.use_auth_cache:
			command.append("--no-auth-cache")
			safe_command.append("--no-auth-cache")
		if self.username:
			command.extend(["--username", self.username])
			safe_command.extend(["--username", self.username])
		if self.password:
			command.extend(["--password", self.password])
			safe_command.extend(["--password", "***"])
		command.append(url)
		safe_command.append(url)
		completed = subprocess.run(command, capture_output=True, check=False)
		if completed.returncode != 0:
			message = completed.stderr.decode("utf-8", errors="replace").strip()
			raise SvnContentReadError(
				f"svn cat failed at r{revision}: {message or 'unknown error'}; "
				f"command={' '.join(safe_command)}"
			)
		return completed.stdout


def _cell_text(cell: XmlET.Element) -> str:
	return "".join(cell.itertext()).strip()


def parse_dtxml_snapshot(content: bytes) -> Dict[str, Dict[str, object]]:
	root = XmlET.fromstring(content)
	sheets: Dict[str, Dict[str, object]] = {}
	for sheet in root.findall("Sheet"):
		name = (sheet.get("Name") or "").strip()
		if not name:
			continue
		columns_node = sheet.find("Columns")
		columns = [
			(col.get("Name") or "").strip()
			for col in columns_node.findall("Column")
		] if columns_node is not None else []
		rows: List[Dict[str, str]] = []
		for row in sheet.findall("Row"):
			values = {
				(cell.get("Name") or "").strip(): _cell_text(cell)
				for cell in row.findall("Cell")
				if (cell.get("Name") or "").strip()
			}
			if any(values.values()):
				rows.append(values)
		sheets[name] = {"columns": columns, "rows": rows}
	return sheets


def _explicit_key_columns(
	key_mappings: Mapping[str, object],
	file_name: str,
	sheet_name: str,
) -> List[str]:
	for key in (f"{file_name}::{sheet_name}", sheet_name):
		value = key_mappings.get(key)
		if isinstance(value, str) and value.strip():
			return [value.strip()]
		if isinstance(value, list):
			columns = [str(item).strip() for item in value if str(item).strip()]
			if columns:
				return columns
	return []


def _is_deferred_sheet(
	deferred_sheets: Sequence[str],
	file_name: str,
	sheet_name: str,
) -> bool:
	return any(
		rule in (f"{file_name}::{sheet_name}", f"{file_name}::*", sheet_name)
		for rule in deferred_sheets
	)


def _choose_key_columns(
	*,
	file_name: str,
	sheet_name: str,
	before_columns: Sequence[str],
	after_columns: Sequence[str],
	key_mappings: Mapping[str, object],
) -> Tuple[List[str], str]:
	explicit = _explicit_key_columns(key_mappings, file_name, sheet_name)
	available = list(after_columns or before_columns)
	if explicit and all(column in available for column in explicit):
		return explicit, "explicit"
	if "ID" in available:
		return ["ID"], "heuristic"
	for column in available:
		if column in DEFAULT_KEY_CANDIDATES or column.endswith("ID"):
			return [column], "heuristic"
	if available:
		return [available[0]], "first_column"
	return [], "row_index"


def _index_rows(
	rows: Sequence[Mapping[str, str]],
	key_columns: Sequence[str],
	key_source: str,
) -> Dict[Tuple[object, ...], Tuple[Dict[str, object], Dict[str, str]]]:
	indexed: Dict[Tuple[object, ...], Tuple[Dict[str, object], Dict[str, str]]] = {}
	occurrences: Dict[Tuple[str, ...], int] = {}
	for index, raw_row in enumerate(rows):
		row = {str(key): str(value).strip() for key, value in raw_row.items()}
		values = tuple(row.get(column, "") for column in key_columns)
		if not key_columns or not any(values):
			identity: Tuple[object, ...] = ("@row", index)
			business_key = {
				"columns": [],
				"values": [str(index + 1)],
				"display": f"row={index + 1}",
				"source": "row_index",
			}
		else:
			occurrence = occurrences.get(values, 0) + 1
			occurrences[values] = occurrence
			identity = tuple(values) + (occurrence,)
			display = ", ".join(f"{column}={value}" for column, value in zip(key_columns, values))
			if occurrence > 1:
				display += f" (#{occurrence})"
			business_key = {
				"columns": list(key_columns),
				"values": list(values),
				"display": display,
				"source": key_source,
				"occurrence": occurrence,
			}
		indexed[identity] = (business_key, row)
	return indexed


def _field_changes(
	before: Optional[Mapping[str, str]],
	after: Optional[Mapping[str, str]],
	column_order: Sequence[str],
) -> List[Dict[str, str]]:
	before = before or {}
	after = after or {}
	ordered = list(column_order)
	for field in list(before) + list(after):
		if field not in ordered:
			ordered.append(field)
	return [
		{"field": field, "before": before.get(field, ""), "after": after.get(field, "")}
		for field in ordered
		if before.get(field, "") != after.get(field, "")
	]


def diff_dtxml_snapshots(
	*,
	repository_path: str,
	revision: int,
	action: str,
	before: Optional[Dict[str, Dict[str, object]]],
	after: Optional[Dict[str, Dict[str, object]]],
	key_mappings: Optional[Mapping[str, object]] = None,
) -> List[Dict[str, object]]:
	key_mappings = key_mappings or {}
	file_name = PurePosixPath(repository_path).name
	before = before or {}
	after = after or {}
	events: List[Dict[str, object]] = []
	for sheet_name in sorted(set(before) | set(after)):
		before_sheet = before.get(sheet_name, {})
		after_sheet = after.get(sheet_name, {})
		before_columns = list(before_sheet.get("columns", []))
		after_columns = list(after_sheet.get("columns", []))
		key_columns, key_source = _choose_key_columns(
			file_name=file_name,
			sheet_name=sheet_name,
			before_columns=before_columns,
			after_columns=after_columns,
			key_mappings=key_mappings,
		)
		before_rows = _index_rows(list(before_sheet.get("rows", [])), key_columns, key_source)
		after_rows = _index_rows(list(after_sheet.get("rows", [])), key_columns, key_source)
		for identity in sorted(set(before_rows) | set(after_rows), key=lambda value: repr(value)):
			before_item = before_rows.get(identity)
			after_item = after_rows.get(identity)
			before_row = before_item[1] if before_item else None
			after_row = after_item[1] if after_item else None
			if before_row == after_row:
				continue
			business_key = (after_item or before_item)[0]  # type: ignore[index]
			change_type = "modified"
			if before_row is None:
				change_type = "added"
			elif after_row is None:
				change_type = "deleted"
			events.append({
				"revision": revision,
				"svn_action": action,
				"repository_path": repository_path,
				"file_name": file_name,
				"sheet": sheet_name,
				"business_key": business_key,
				"change_type": change_type,
				"before": before_row,
				"after": after_row,
				"changed_fields": _field_changes(before_row, after_row, after_columns or before_columns),
			})
	return events


def _aggregate_events(events: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
	groups: Dict[Tuple[str, str, str], List[Dict[str, object]]] = {}
	for event in events:
		business_key = event.get("business_key", {})
		identity = json.dumps(business_key, ensure_ascii=False, sort_keys=True)
		key = (str(event.get("repository_path", "")), str(event.get("sheet", "")), identity)
		groups.setdefault(key, []).append(event)

	changes: List[Dict[str, object]] = []
	for grouped_events in groups.values():
		ordered = sorted(grouped_events, key=lambda event: int(event.get("revision", 0)))
		first = ordered[0]
		last = ordered[-1]
		external_intermediate_change = any(
			previous.get("after") != current.get("before")
			for previous, current in zip(ordered, ordered[1:])
		)
		before = first.get("before")
		after = last.get("after")
		change_type = "modified"
		if before is None and after is not None:
			change_type = "added"
		elif before is not None and after is None:
			change_type = "deleted"
		elif before is None and after is None:
			change_type = "transient"
		changed_fields: List[str] = []
		for event in ordered:
			for field_change in event.get("changed_fields", []):
				if isinstance(field_change, dict):
					field = str(field_change.get("field", ""))
					if field and field not in changed_fields:
						changed_fields.append(field)
		changes.append({
			"repository_path": first.get("repository_path"),
			"file_name": first.get("file_name"),
			"sheet": first.get("sheet"),
			"business_key": first.get("business_key"),
			"change_type": change_type,
			"revisions": [int(event.get("revision", 0)) for event in ordered],
			"before": before,
			"after": after,
			"changed_fields": changed_fields,
			"semantic_analysis": first.get("semantic_analysis", {"status": "eligible"}),
			"has_external_intermediate_change": external_intermediate_change,
			"events": ordered,
		})
	return sorted(
		changes,
		key=lambda change: (
			str(change.get("repository_path", "")),
			str(change.get("sheet", "")),
			str(change.get("business_key", {})),
		),
	)


def _is_dtxml_path(path: str, region_code: str) -> bool:
	normalized = _clean_changed_path(path)
	lower = normalized.casefold()
	if not lower.endswith(".dtxml") or "/xml/" not in lower:
		return False
	region = region_code.strip().casefold()
	if region and "/xml/garena/" in lower:
		return f"/xml/garena/{region}/" in lower
	return True


def build_dtxml_changeset(
	*,
	log_text: str,
	revision_spec: str,
	tdr_svn_target: str,
	region_code: str = "",
	svn_exe: str = "svn",
	username: str = "",
	password: str = "",
	use_auth_cache: bool = True,
	key_mappings: Optional[Mapping[str, object]] = None,
	deferred_sheets: Optional[Sequence[str]] = None,
	content_loader: Optional[ContentLoader] = None,
) -> Dict[str, object]:
	merged_key_mappings = dict(DEFAULT_PROJECT_KEY_MAPPINGS)
	merged_key_mappings.update(key_mappings or {})
	key_mappings = merged_key_mappings
	deferred_sheets = tuple(deferred_sheets or DEFAULT_DEFERRED_SHEETS)
	try:
		selected_revisions = parse_revision_spec(revision_spec)
	except RevisionSpecError as error:
		return {
			"schema_version": CHANGESET_SCHEMA_VERSION,
			"status": "error",
			"reason": "invalid_revision_spec",
			"message": str(error),
			"changes": [],
			"errors": [],
		}
	if not selected_revisions:
		return {
			"schema_version": CHANGESET_SCHEMA_VERSION,
			"status": "skipped",
			"reason": "missing_revision_spec",
			"changes": [],
			"errors": [],
		}
	if not log_text.strip():
		return {
			"schema_version": CHANGESET_SCHEMA_VERSION,
			"status": "skipped",
			"reason": "missing_svn_log",
			"changes": [],
			"errors": [],
		}

	selected = set(selected_revisions)
	paths = [
		item for item in parse_repository_changed_paths(log_text)
		if item.revision in selected and _is_dtxml_path(item.path, region_code)
	]
	if not paths:
		return {
			"schema_version": CHANGESET_SCHEMA_VERSION,
			"status": "passed",
			"reason": "no_selected_dtxml_changes",
			"selection": {"revision_spec": revision_spec, "revisions": selected_revisions},
			"summary": {"file_count": 0, "sheet_count": 0, "change_count": 0, "event_count": 0},
			"changes": [],
			"errors": [],
		}

	if content_loader is None:
		if not tdr_svn_target.strip():
			return {
				"schema_version": CHANGESET_SCHEMA_VERSION,
				"status": "skipped",
				"reason": "missing_tdr_svn_target",
				"changes": [],
				"errors": [],
			}
		content_loader = SvnCatClient(
			tdr_svn_target=tdr_svn_target,
			svn_exe=svn_exe,
			username=username,
			password=password,
			use_auth_cache=use_auth_cache,
		).read

	cache: Dict[Tuple[str, int], bytes] = {}
	events: List[Dict[str, object]] = []
	deferred_changes: List[Dict[str, object]] = []
	errors: List[Dict[str, object]] = []
	for changed in sorted(paths, key=lambda item: (item.revision, item.path)):
		try:
			before_content = None
			after_content = None
			if changed.action != "A":
				cache_key = (changed.path, changed.revision - 1)
				if cache_key not in cache:
					cache[cache_key] = content_loader(changed.path, changed.revision - 1)
				before_content = cache[cache_key]
			if changed.action != "D":
				cache_key = (changed.path, changed.revision)
				if cache_key not in cache:
					cache[cache_key] = content_loader(changed.path, changed.revision)
				after_content = cache[cache_key]
			before_snapshot = parse_dtxml_snapshot(before_content) if before_content is not None else {}
			after_snapshot = parse_dtxml_snapshot(after_content) if after_content is not None else {}
			file_name = PurePosixPath(changed.path).name
			deferred_names = {
				sheet_name
				for sheet_name in set(before_snapshot) | set(after_snapshot)
				if _is_deferred_sheet(deferred_sheets, file_name, sheet_name)
			}
			for sheet_name in sorted(deferred_names):
				if before_snapshot.get(sheet_name) != after_snapshot.get(sheet_name):
					deferred_changes.append({
						"revision": changed.revision,
						"svn_action": changed.action,
						"repository_path": changed.path,
						"file_name": file_name,
						"sheet": sheet_name,
						"status": "deferred",
						"reason": "semantic_analysis_deferred",
					})
			file_events = diff_dtxml_snapshots(
				repository_path=changed.path,
				revision=changed.revision,
				action=changed.action,
				before=before_snapshot,
				after=after_snapshot,
				key_mappings=key_mappings,
			)
			for event in file_events:
				if event.get("sheet") in deferred_names:
					event["semantic_analysis"] = {
						"status": "deferred",
						"reason": "module_not_enabled",
					}
			events.extend(file_events)
		except Exception as error:
			errors.append({
				"revision": changed.revision,
				"action": changed.action,
				"repository_path": changed.path,
				"message": str(error),
			})

	changes = _aggregate_events(events)
	changed_files = {str(event.get("repository_path", "")) for event in events}
	changed_files.update(str(item.get("repository_path", "")) for item in deferred_changes)
	changed_sheets = {
		(str(event.get("repository_path", "")), str(event.get("sheet", "")))
		for event in events
	}
	changed_sheets.update(
		(str(item.get("repository_path", "")), str(item.get("sheet", "")))
		for item in deferred_changes
	)
	return {
		"schema_version": CHANGESET_SCHEMA_VERSION,
		"status": "warning" if errors or deferred_changes else "passed",
		"selection": {
			"revision_spec": revision_spec,
			"revisions": selected_revisions,
			"strategy": "per_revision_diff",
		},
		"scope": {
			"region_code": region_code.upper(),
			"file_type": ".dtxml",
			"source_side": "unfiltered",
		},
		"summary": {
			"file_count": len(changed_files),
			"sheet_count": len(changed_sheets),
			"change_count": len(changes),
			"event_count": len(events),
			"added_count": sum(change.get("change_type") == "added" for change in changes),
			"modified_count": sum(change.get("change_type") == "modified" for change in changes),
			"deleted_count": sum(change.get("change_type") == "deleted" for change in changes),
			"external_intermediate_change_count": sum(
				bool(change.get("has_external_intermediate_change")) for change in changes
			),
			"deferred_change_count": len(deferred_changes),
			"deferred_row_change_count": sum(
				change.get("semantic_analysis", {}).get("status") == "deferred"
				for change in changes
				if isinstance(change.get("semantic_analysis"), dict)
			),
			"error_count": len(errors),
		},
		"changes": changes,
		"deferred_changes": deferred_changes,
		"errors": errors,
	}


def run_dtxml_changeset(validation_config: Optional[Dict[str, object]]) -> Dict[str, object]:
	config = validation_config or {}
	diff_value = config.get("dtxml_diff")
	if not isinstance(diff_value, dict) or diff_value.get("enabled") is False:
		return {
			"schema_version": CHANGESET_SCHEMA_VERSION,
			"status": "skipped",
			"reason": "dtxml_diff_disabled",
			"changes": [],
			"errors": [],
		}
	return build_dtxml_changeset(
		log_text=str(diff_value.get("svn_log_text") or ""),
		revision_spec=str(diff_value.get("current_revision_spec") or ""),
		tdr_svn_target=str(diff_value.get("tdr_svn_target") or diff_value.get("svn_target") or ""),
		region_code=str(diff_value.get("region_code") or config.get("region_code") or ""),
		svn_exe=str(diff_value.get("svn_exe") or "svn"),
		username=str(diff_value.get("svn_username") or ""),
		password=str(diff_value.get("svn_password") or ""),
		use_auth_cache=bool(diff_value.get("svn_auth_cache", True)),
		key_mappings=(
			diff_value.get("key_mappings")
			if isinstance(diff_value.get("key_mappings"), dict)
			else None
		),
		deferred_sheets=(
			[str(item) for item in diff_value.get("deferred_sheets", [])]
			if isinstance(diff_value.get("deferred_sheets"), list)
			else None
		),
	)
