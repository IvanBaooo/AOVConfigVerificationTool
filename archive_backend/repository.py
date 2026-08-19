from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class ArchiveConflict(RuntimeError):
	def __init__(self, code: str, message: str) -> None:
		super().__init__(message)
		self.code = code


@dataclass(frozen=True)
class CreateArchiveResult:
	result: str
	summary: dict[str, object]

@dataclass(frozen=True)
class PublishRuleSetResult:
	result: str
	rule_set_id: str
	version: str
	published_at: str
	payload_sha256: str


SUMMARY_COLUMNS = (
	"package_id",
	"schema_version",
	"idempotency_key",
	"created_at",
	"received_at",
	"region_code",
	"region_dir",
	"package_version",
	"package_status",
	"validation_status",
	"file_count",
	"warning_count",
	"deleted_at",
	"deleted_by",
	"delete_reason",
)


def _utc_now() -> str:
	return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_json_numbers(value: Any) -> Any:
	if isinstance(value, float) and value.is_integer():
		return int(value)
	if isinstance(value, dict):
		return {key: _normalize_json_numbers(item) for key, item in value.items()}
	if isinstance(value, list):
		return [_normalize_json_numbers(item) for item in value]
	return value


def _canonical_payload(payload: Mapping[str, Any]) -> tuple[dict[str, Any], str, str]:
	normalized = _normalize_json_numbers(dict(payload))
	text = json.dumps(
		normalized,
		ensure_ascii=False,
		sort_keys=True,
		separators=(",", ":"),
		allow_nan=False,
	)
	digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
	return normalized, text, digest


def _payload_summary(payload: Mapping[str, Any], received_at: str) -> dict[str, object]:
	release = payload["release"]
	package = payload["package"]
	status = payload["status"]
	validation = payload["validation"]
	return {
		"package_id": payload["package_id"],
		"schema_version": payload["schema_version"],
		"idempotency_key": payload["idempotency_key"],
		"created_at": payload["created_at"],
		"received_at": received_at,
		"region_code": release["region_code"],
		"region_dir": release["region_dir"],
		"package_version": release["package_version"],
		"package_status": status["package_status"],
		"validation_status": status["validation_status"],
		"file_count": package["file_count"],
		"warning_count": validation["summary"]["warning_count"],
	}


def _row_summary(row: sqlite3.Row) -> dict[str, object]:
	return {column: row[column] for column in SUMMARY_COLUMNS}


class ArchiveRepository:
	def __init__(self, database_path: str | Path) -> None:
		self.database_path = Path(database_path).expanduser().resolve()
		self.database_path.parent.mkdir(parents=True, exist_ok=True)
		self._initialize()

	def _connect(self) -> sqlite3.Connection:
		connection = sqlite3.connect(
			self.database_path,
			timeout=30,
			isolation_level=None,
		)
		connection.row_factory = sqlite3.Row
		connection.execute("PRAGMA busy_timeout = 30000")
		connection.execute("PRAGMA foreign_keys = ON")
		return connection

	@contextmanager
	def _open_connection(self):
		connection = self._connect()
		try:
			yield connection
		finally:
			connection.close()

	def _initialize(self) -> None:
		with self._open_connection() as connection:
			connection.execute("PRAGMA journal_mode = WAL")
			connection.executescript(
				"""
				CREATE TABLE IF NOT EXISTS package_archives (
					package_id TEXT PRIMARY KEY,
					schema_version TEXT NOT NULL,
					idempotency_key TEXT NOT NULL,
					payload_sha256 TEXT NOT NULL,
					payload_json TEXT NOT NULL,
					created_at TEXT NOT NULL,
					received_at TEXT NOT NULL,
					region_code TEXT NOT NULL,
					region_dir TEXT NOT NULL,
					package_version TEXT NOT NULL,
					package_status TEXT NOT NULL,
					validation_status TEXT NOT NULL,
					file_count INTEGER NOT NULL,
					warning_count INTEGER NOT NULL,
					UNIQUE (schema_version, idempotency_key)
				);
				CREATE INDEX IF NOT EXISTS idx_package_archives_received_at
					ON package_archives (received_at DESC);
				CREATE INDEX IF NOT EXISTS idx_package_archives_filters
					ON package_archives (region_code, package_version, validation_status);
				CREATE TABLE IF NOT EXISTS validation_rule_sets (
					rule_set_id TEXT NOT NULL,
					version TEXT NOT NULL,
					published_at TEXT NOT NULL,
					created_at TEXT NOT NULL,
					payload_sha256 TEXT NOT NULL,
					payload_json TEXT NOT NULL,
					PRIMARY KEY (rule_set_id, version)
				);
				CREATE INDEX IF NOT EXISTS idx_validation_rule_sets_latest
					ON validation_rule_sets (published_at DESC, created_at DESC);
				CREATE TABLE IF NOT EXISTS archive_admin_audit (
					id INTEGER PRIMARY KEY AUTOINCREMENT,
					package_id TEXT NOT NULL,
					action TEXT NOT NULL,
					actor TEXT NOT NULL,
					reason TEXT NOT NULL,
					created_at TEXT NOT NULL
				);
				CREATE INDEX IF NOT EXISTS idx_archive_admin_audit_created_at
					ON archive_admin_audit (created_at DESC, id DESC);
				CREATE TABLE IF NOT EXISTS release_baselines (
					region_code TEXT PRIMARY KEY,
					package_id TEXT NOT NULL UNIQUE,
					updated_at TEXT NOT NULL,
					updated_by TEXT NOT NULL,
					reason TEXT NOT NULL,
					FOREIGN KEY (package_id) REFERENCES package_archives (package_id)
				);
				"""
			)
			columns = {row["name"] for row in connection.execute("PRAGMA table_info(package_archives)")}
			for name in ("deleted_at", "deleted_by", "delete_reason"):
				if name not in columns:
					connection.execute(f"ALTER TABLE package_archives ADD COLUMN {name} TEXT")
			for row in connection.execute("SELECT DISTINCT region_code FROM package_archives"):
				latest = connection.execute(
					"""
					SELECT package_id, received_at
					FROM package_archives
					WHERE region_code = ? AND deleted_at IS NULL
					ORDER BY received_at DESC, package_id DESC
					LIMIT 1
					""",
					(row["region_code"],),
				).fetchone()
				if latest is not None:
					connection.execute(
						"""
						INSERT OR IGNORE INTO release_baselines (
							region_code, package_id, updated_at, updated_by, reason
						) VALUES (?, ?, ?, 'migration', 'Initial baseline migration')
						""",
						(row["region_code"], latest["package_id"], latest["received_at"]),
					)
			connection.execute("PRAGMA user_version = 4")

	def create_archive(self, payload: Mapping[str, Any]) -> CreateArchiveResult:
		normalized, payload_json, payload_sha256 = _canonical_payload(payload)
		received_at = _utc_now()
		summary = _payload_summary(normalized, received_at)
		connection = self._connect()
		try:
			connection.execute("BEGIN IMMEDIATE")
			existing_key = connection.execute(
				"""
				SELECT * FROM package_archives
				WHERE schema_version = ? AND idempotency_key = ?
				""",
				(summary["schema_version"], summary["idempotency_key"]),
			).fetchone()
			if existing_key is not None:
				if existing_key["payload_sha256"] != payload_sha256:
					raise ArchiveConflict(
						"idempotency_conflict",
						"The idempotency key already belongs to a different payload.",
					)
				connection.commit()
				return CreateArchiveResult("replayed", _row_summary(existing_key))

			existing_package = connection.execute(
				"SELECT * FROM package_archives WHERE package_id = ?",
				(summary["package_id"],),
			).fetchone()
			if existing_package is not None:
				raise ArchiveConflict(
					"package_id_conflict",
					"The package ID already exists under another idempotency key.",
				)

			connection.execute(
				"""
				INSERT INTO package_archives (
					package_id, schema_version, idempotency_key,
					payload_sha256, payload_json, created_at, received_at,
					region_code, region_dir, package_version,
					package_status, validation_status, file_count, warning_count
				) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
				""",
				(
					summary["package_id"],
					summary["schema_version"],
					summary["idempotency_key"],
					payload_sha256,
					payload_json,
					summary["created_at"],
					summary["received_at"],
					summary["region_code"],
					summary["region_dir"],
					summary["package_version"],
					summary["package_status"],
					summary["validation_status"],
					summary["file_count"],
					summary["warning_count"],
				),
			)
			connection.execute(
				"""
				INSERT INTO release_baselines (
					region_code, package_id, updated_at, updated_by, reason
				) VALUES (?, ?, ?, 'archive-sync', 'Archive confirmed')
				ON CONFLICT(region_code) DO UPDATE SET
					package_id = excluded.package_id,
					updated_at = excluded.updated_at,
					updated_by = excluded.updated_by,
					reason = excluded.reason
				""",
				(summary["region_code"], summary["package_id"], received_at),
			)
			connection.commit()
			return CreateArchiveResult("created", summary)
		except Exception:
			if connection.in_transaction:
				connection.rollback()
			raise
		finally:
			connection.close()

	def get_archive(self, package_id: str) -> dict[str, object] | None:
		with self._open_connection() as connection:
			row = connection.execute(
				"SELECT payload_json FROM package_archives WHERE package_id = ?",
				(package_id,),
			).fetchone()
		if row is None:
			return None
		return json.loads(row["payload_json"])

	def get_archive_management(self, package_id: str) -> dict[str, object] | None:
		with self._open_connection() as connection:
			row = connection.execute(
				"""
				SELECT
					pa.region_code,
					pa.deleted_at,
					pa.deleted_by,
					pa.delete_reason,
					CASE WHEN rb.package_id = pa.package_id THEN 1 ELSE 0 END AS is_release_baseline
				FROM package_archives AS pa
				LEFT JOIN release_baselines AS rb ON rb.region_code = pa.region_code
				WHERE pa.package_id = ?
				""",
				(package_id,),
			).fetchone()
		if row is None:
			return None
		return {
			"record_state": "deleted" if row["deleted_at"] is not None else "active",
			"region_code": row["region_code"],
			"is_release_baseline": bool(row["is_release_baseline"]),
			"deleted_at": row["deleted_at"],
			"deleted_by": row["deleted_by"],
			"delete_reason": row["delete_reason"],
		}

	def get_latest_release_baseline(self, region_code: str) -> dict[str, object] | None:
		with self._open_connection() as connection:
			row = connection.execute(
				"""
				SELECT
					pa.package_id,
					pa.created_at,
					pa.received_at,
					pa.payload_json,
					rb.updated_at AS baseline_updated_at,
					rb.updated_by AS baseline_updated_by
				FROM release_baselines AS rb
				JOIN package_archives AS pa ON pa.package_id = rb.package_id
				WHERE rb.region_code = ? AND pa.deleted_at IS NULL
				""",
				(region_code,),
			).fetchone()
		if row is None:
			return None

		payload = json.loads(row["payload_json"])
		release = payload.get("release", {})
		if not isinstance(release, dict):
			release = {}
		revisions_value = release.get("current_revisions", [])
		revisions = [
			value
			for value in revisions_value
			if isinstance(value, int) and not isinstance(value, bool) and value > 0
		] if isinstance(revisions_value, list) else []
		return {
			"region_code": region_code,
			"package_id": row["package_id"],
			"release_time": row["received_at"],
			"package_created_at": row["created_at"],
			"released_revision_spec": str(release.get("current_revision_spec") or ""),
			"released_revisions": revisions,
			"last_checked_revision": max(revisions) if revisions else None,
			"package_version": str(release.get("package_version") or ""),
			"baseline_updated_at": row["baseline_updated_at"],
			"baseline_updated_by": row["baseline_updated_by"],
		}
	def soft_delete_archive(
		self,
		package_id: str,
		*,
		actor: str,
		reason: str,
		replacement_package_id: str | None = None,
	) -> dict[str, object]:
		return self._set_archive_deleted(
			package_id,
			deleted=True,
			actor=actor,
			reason=reason,
			replacement_package_id=replacement_package_id,
		)

	def restore_archive(self, package_id: str, *, actor: str, reason: str) -> dict[str, object]:
		return self._set_archive_deleted(
			package_id,
			deleted=False,
			actor=actor,
			reason=reason,
		)

	def set_release_baseline(
		self,
		package_id: str,
		*,
		actor: str,
		reason: str,
	) -> dict[str, object]:
		changed_at = _utc_now()
		connection = self._connect()
		try:
			connection.execute("BEGIN IMMEDIATE")
			row = connection.execute(
				"""
				SELECT region_code, deleted_at
				FROM package_archives
				WHERE package_id = ?
				""",
				(package_id,),
			).fetchone()
			if row is None:
				raise ArchiveConflict("archive_not_found", "The archive record was not found.")
			if row["deleted_at"] is not None:
				raise ArchiveConflict(
					"baseline_archive_deleted",
					"A deleted archive cannot become the release baseline.",
				)
			previous = connection.execute(
				"SELECT package_id FROM release_baselines WHERE region_code = ?",
				(row["region_code"],),
			).fetchone()
			connection.execute(
				"""
				INSERT INTO release_baselines (
					region_code, package_id, updated_at, updated_by, reason
				) VALUES (?, ?, ?, ?, ?)
				ON CONFLICT(region_code) DO UPDATE SET
					package_id = excluded.package_id,
					updated_at = excluded.updated_at,
					updated_by = excluded.updated_by,
					reason = excluded.reason
				""",
				(row["region_code"], package_id, changed_at, actor, reason),
			)
			connection.execute(
				"""
				INSERT INTO archive_admin_audit (
					package_id, action, actor, reason, created_at
				) VALUES (?, 'baseline_set', ?, ?, ?)
				""",
				(package_id, actor, reason, changed_at),
			)
			connection.commit()
			return {
				"region_code": row["region_code"],
				"previous_package_id": previous["package_id"] if previous is not None else None,
				"package_id": package_id,
				"updated_at": changed_at,
				"updated_by": actor,
			}
		except Exception:
			if connection.in_transaction:
				connection.rollback()
			raise
		finally:
			connection.close()

	def _set_archive_deleted(
		self,
		package_id: str,
		*,
		deleted: bool,
		actor: str,
		reason: str,
		replacement_package_id: str | None = None,
	) -> dict[str, object]:
		changed_at = _utc_now()
		connection = self._connect()
		try:
			connection.execute("BEGIN IMMEDIATE")
			row = connection.execute(
				"""
				SELECT region_code, deleted_at
				FROM package_archives
				WHERE package_id = ?
				""",
				(package_id,),
			).fetchone()
			if row is None:
				raise ArchiveConflict("archive_not_found", "The archive record was not found.")
			if deleted and row["deleted_at"] is not None:
				raise ArchiveConflict("archive_already_deleted", "The archive record is already deleted.")
			if not deleted and row["deleted_at"] is None:
				raise ArchiveConflict("archive_not_deleted", "The archive record is not deleted.")

			baseline = connection.execute(
				"SELECT package_id FROM release_baselines WHERE region_code = ?",
				(row["region_code"],),
			).fetchone()
			is_baseline = baseline is not None and baseline["package_id"] == package_id
			baseline_change: dict[str, object] = {
				"changed": False,
				"previous_package_id": baseline["package_id"] if baseline is not None else None,
				"package_id": baseline["package_id"] if baseline is not None else None,
			}

			if deleted and is_baseline:
				candidate_count = connection.execute(
					"""
					SELECT COUNT(*)
					FROM package_archives
					WHERE region_code = ? AND deleted_at IS NULL AND package_id != ?
					""",
					(row["region_code"], package_id),
				).fetchone()[0]
				if replacement_package_id is None and candidate_count:
					raise ArchiveConflict(
						"baseline_replacement_required",
						"Deleting the current release baseline requires a replacement archive.",
					)
				if replacement_package_id is not None:
					replacement = connection.execute(
						"""
						SELECT region_code, deleted_at
						FROM package_archives
						WHERE package_id = ?
						""",
						(replacement_package_id,),
					).fetchone()
					if (
						replacement is None
						or replacement["deleted_at"] is not None
						or replacement["region_code"] != row["region_code"]
						or replacement_package_id == package_id
					):
						raise ArchiveConflict(
							"invalid_baseline_replacement",
							"The replacement must be another active archive from the same region.",
						)
					connection.execute(
						"""
						UPDATE release_baselines
						SET package_id = ?, updated_at = ?, updated_by = ?, reason = ?
						WHERE region_code = ?
						""",
						(replacement_package_id, changed_at, actor, reason, row["region_code"]),
					)
					baseline_change["package_id"] = replacement_package_id
				else:
					connection.execute(
						"DELETE FROM release_baselines WHERE region_code = ?",
						(row["region_code"],),
					)
					baseline_change["package_id"] = None
				baseline_change["changed"] = True
			elif deleted and replacement_package_id is not None:
				raise ArchiveConflict(
					"baseline_replacement_not_allowed",
					"A replacement is only accepted when deleting the current release baseline.",
				)

			if deleted:
				connection.execute(
					"""
					UPDATE package_archives
					SET deleted_at = ?, deleted_by = ?, delete_reason = ?
					WHERE package_id = ?
					""",
					(changed_at, actor, reason, package_id),
				)
			else:
				connection.execute(
					"""
					UPDATE package_archives
					SET deleted_at = NULL, deleted_by = NULL, delete_reason = NULL
					WHERE package_id = ?
					""",
					(package_id,),
				)
			connection.execute(
				"""
				INSERT INTO archive_admin_audit (
					package_id, action, actor, reason, created_at
				) VALUES (?, ?, ?, ?, ?)
				""",
				(package_id, "delete" if deleted else "restore", actor, reason, changed_at),
			)
			connection.commit()
			return {
				"package_id": package_id,
				"region_code": row["region_code"],
				"action": "delete" if deleted else "restore",
				"actor": actor,
				"reason": reason,
				"created_at": changed_at,
				"baseline": baseline_change,
			}
		except Exception:
			if connection.in_transaction:
				connection.rollback()
			raise
		finally:
			connection.close()
	def list_archive_audit(
		self,
		*,
		limit: int = 100,
		offset: int = 0,
		action: str | None = None,
		region_code: str | None = None,
	) -> dict[str, object]:
		clauses: list[str] = []
		parameters: list[object] = []
		if action is not None:
			clauses.append("audit.action = ?")
			parameters.append(action)
		if region_code is not None:
			clauses.append("archives.region_code = ?")
			parameters.append(region_code)
		where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
		with self._open_connection() as connection:
			total = connection.execute(
				f"""
				SELECT COUNT(*)
				FROM archive_admin_audit AS audit
				JOIN package_archives AS archives ON archives.package_id = audit.package_id
				{where}
				""",
				parameters,
			).fetchone()[0]
			rows = connection.execute(
				f"""
				SELECT
					audit.id, audit.package_id, audit.action, audit.actor,
					audit.reason, audit.created_at, archives.region_code
				FROM archive_admin_audit AS audit
				JOIN package_archives AS archives ON archives.package_id = audit.package_id
				{where}
				ORDER BY audit.created_at DESC, audit.id DESC
				LIMIT ? OFFSET ?
				""",
				[*parameters, limit, offset],
			).fetchall()
		return {
			"items": [dict(row) for row in rows],
			"total": total,
			"limit": limit,
			"offset": offset,
		}
	def list_archives(
		self,
		*,
		limit: int = 50,
		offset: int = 0,
		region_code: str | None = None,
		package_version: str | None = None,
		package_status: str | None = None,
		validation_status: str | None = None,
		record_state: str = "active",
	) -> dict[str, object]:
		filters = {
			"region_code": region_code,
			"package_version": package_version,
			"package_status": package_status,
			"validation_status": validation_status,
		}
		clauses: list[str] = []
		parameters: list[object] = []
		if record_state == "active":
			clauses.append("deleted_at IS NULL")
		elif record_state == "deleted":
			clauses.append("deleted_at IS NOT NULL")
		elif record_state != "all":
			raise ValueError("Unsupported record_state")
		for column, value in filters.items():
			if value is not None:
				clauses.append(f"{column} = ?")
				parameters.append(value)
		where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

		with self._open_connection() as connection:
			connection.execute("BEGIN")
			try:
				total = connection.execute(
					f"SELECT COUNT(*) FROM package_archives{where}",
					parameters,
				).fetchone()[0]
				rows = connection.execute(
					f"""
					SELECT {', '.join(SUMMARY_COLUMNS)}
					FROM package_archives{where}
					ORDER BY received_at DESC, package_id DESC
					LIMIT ? OFFSET ?
					""",
					[*parameters, limit, offset],
				).fetchall()
				baseline_ids = {
					row["package_id"]
					for row in connection.execute("SELECT package_id FROM release_baselines")
				}
				connection.commit()
			except Exception:
				if connection.in_transaction:
					connection.rollback()
				raise
		items = [_row_summary(row) for row in rows]
		for item in items:
			item["is_release_baseline"] = item["package_id"] in baseline_ids
		return {
			"items": items,
			"total": total,
			"limit": limit,
			"offset": offset,
		}

	def get_dashboard_summary(self, region_codes: tuple[str, ...]) -> dict[str, object]:
		with self._open_connection() as connection:
			overview = connection.execute(
				"""
				SELECT
					SUM(CASE WHEN deleted_at IS NULL THEN 1 ELSE 0 END) AS active_count,
					SUM(CASE WHEN deleted_at IS NOT NULL THEN 1 ELSE 0 END) AS deleted_count,
					SUM(CASE
						WHEN deleted_at IS NULL AND validation_status IN ('warning', 'failed') THEN 1
						ELSE 0
					END) AS attention_count
				FROM package_archives
				"""
			).fetchone()
			baseline_count = connection.execute("SELECT COUNT(*) FROM release_baselines").fetchone()[0]
			region_rows = connection.execute(
				"""
				SELECT
					region_code,
					SUM(CASE WHEN deleted_at IS NULL THEN 1 ELSE 0 END) AS active_count,
					SUM(CASE WHEN deleted_at IS NOT NULL THEN 1 ELSE 0 END) AS deleted_count,
					SUM(CASE
						WHEN deleted_at IS NULL AND validation_status IN ('warning', 'failed') THEN 1
						ELSE 0
					END) AS attention_count
				FROM package_archives
				GROUP BY region_code
				"""
			).fetchall()
		region_stats = {row["region_code"]: dict(row) for row in region_rows}

		regions: list[dict[str, object]] = []
		for region_code in region_codes:
			stats = region_stats.get(region_code, {})
			latest = self.list_archives(limit=1, region_code=region_code)["items"]
			regions.append({
				"region_code": region_code,
				"active_count": int(stats.get("active_count") or 0),
				"deleted_count": int(stats.get("deleted_count") or 0),
				"attention_count": int(stats.get("attention_count") or 0),
				"baseline": self.get_latest_release_baseline(region_code),
				"latest_archive": latest[0] if latest else None,
			})
		recent = self.list_archives(limit=8)["items"]
		return {
			"generated_at": _utc_now(),
			"overview": {
				"active_count": int(overview["active_count"] or 0),
				"deleted_count": int(overview["deleted_count"] or 0),
				"attention_count": int(overview["attention_count"] or 0),
				"baseline_count": int(baseline_count),
			},
			"regions": regions,
			"recent_archives": recent,
		}
	def publish_rule_set(self, rule_set: Mapping[str, Any]) -> PublishRuleSetResult:
		normalized, payload_json, payload_sha256 = _canonical_payload(rule_set)
		rule_set_id = str(normalized["rule_set_id"])
		version = str(normalized["version"])
		published_at = str(normalized["published_at"])
		created_at = _utc_now()
		connection = self._connect()
		try:
			connection.execute("BEGIN IMMEDIATE")
			existing = connection.execute(
				"SELECT * FROM validation_rule_sets WHERE rule_set_id = ? AND version = ?",
				(rule_set_id, version),
			).fetchone()
			if existing is not None:
				if existing["payload_sha256"] != payload_sha256:
					raise ArchiveConflict(
						"rule_version_conflict",
						"The rule set version already belongs to different content.",
					)
				connection.commit()
				return PublishRuleSetResult(
					"replayed", rule_set_id, version, published_at, payload_sha256
				)
			connection.execute(
				"""
				INSERT INTO validation_rule_sets (
					rule_set_id, version, published_at, created_at, payload_sha256, payload_json
				) VALUES (?, ?, ?, ?, ?, ?)
				""",
				(rule_set_id, version, published_at, created_at, payload_sha256, payload_json),
			)
			connection.commit()
			return PublishRuleSetResult(
				"created", rule_set_id, version, published_at, payload_sha256
			)
		except Exception:
			if connection.in_transaction:
				connection.rollback()
			raise
		finally:
			connection.close()

	def get_rule_set(self, rule_set_id: str, version: str) -> dict[str, object] | None:
		with self._open_connection() as connection:
			row = connection.execute(
				"""
				SELECT payload_json FROM validation_rule_sets
				WHERE rule_set_id = ? AND version = ?
				""",
				(rule_set_id, version),
			).fetchone()
		if row is None:
			return None
		return json.loads(row["payload_json"])

	def list_rule_sets(self, *, limit: int = 50, offset: int = 0) -> dict[str, object]:
		with self._open_connection() as connection:
			connection.execute("BEGIN")
			try:
				total = connection.execute("SELECT COUNT(*) FROM validation_rule_sets").fetchone()[0]
				rows = connection.execute(
					"""
					SELECT payload_json, payload_sha256, created_at
					FROM validation_rule_sets
					ORDER BY published_at DESC, created_at DESC, rule_set_id DESC, version DESC
					LIMIT ? OFFSET ?
					""",
					(limit, offset),
				).fetchall()
				connection.commit()
			except Exception:
				if connection.in_transaction:
					connection.rollback()
				raise
		items: list[dict[str, object]] = []
		for row in rows:
			payload = json.loads(row["payload_json"])
			common = payload.get("common", {})
			regions = payload.get("regions", {})
			mapping_count = len(common.get("path_mappings", [])) if isinstance(common, dict) else 0
			whitelist_count = len(common.get("whitelist_paths", [])) if isinstance(common, dict) else 0
			content_check_count = len(common.get("content_checks", [])) if isinstance(common, dict) else 0
			if isinstance(regions, dict):
				for region_rules in regions.values():
					if not isinstance(region_rules, dict):
						continue
					mapping_count += len(region_rules.get("path_mappings", []))
					whitelist_count += len(region_rules.get("whitelist_paths", []))
					content_check_count += len(region_rules.get("content_checks", []))
			items.append({
				"rule_set_id": payload.get("rule_set_id", ""),
				"version": payload.get("version", ""),
				"published_at": payload.get("published_at", ""),
				"notes": payload.get("notes", ""),
				"payload_sha256": row["payload_sha256"],
				"created_at": row["created_at"],
				"mapping_count": mapping_count,
				"whitelist_count": whitelist_count,
				"content_check_count": content_check_count,
			})
		return {"items": items, "total": total, "limit": limit, "offset": offset}
	def get_latest_rule_set(self) -> dict[str, object] | None:
		with self._open_connection() as connection:
			row = connection.execute(
				"""
				SELECT payload_json FROM validation_rule_sets
				ORDER BY published_at DESC, created_at DESC, rule_set_id DESC, version DESC
				LIMIT 1
				"""
			).fetchone()
		if row is None:
			return None
		return json.loads(row["payload_json"])

	def health_check(self) -> bool:
		with self._open_connection() as connection:
			return connection.execute("SELECT 1").fetchone()[0] == 1


__all__ = [
	"ArchiveConflict",
	"ArchiveRepository",
	"CreateArchiveResult",
	"PublishRuleSetResult",
]
