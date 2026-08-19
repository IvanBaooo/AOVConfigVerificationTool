from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


QUEUE_PATH_ENV = "AOV_PUBLICATION_QUEUE"
SETTINGS_PATH_ENV = "AOV_AUTOPACKER_SETTINGS"


class PublicationQueueError(RuntimeError):
	pass


@dataclass(frozen=True)
class PendingArchive:
	idempotency_key: str
	package_id: str
	backend_url: str
	payload: dict[str, object]
	attempts: int
	last_error: str
	created_at: str
	updated_at: str


def default_queue_path() -> Path:
	override = os.environ.get(QUEUE_PATH_ENV, "").strip()
	if override:
		return Path(override).expanduser()
	settings_override = os.environ.get(SETTINGS_PATH_ENV, "").strip()
	if settings_override:
		return Path(settings_override).expanduser().with_name("publication_queue.sqlite3")
	return Path(__file__).resolve().parent / "publication_queue.sqlite3"


def _utc_now() -> str:
	return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validated_payload(payload: Mapping[str, Any]) -> tuple[str, str, str]:
	idempotency_key = payload.get("idempotency_key")
	package_id = payload.get("package_id")
	if not isinstance(idempotency_key, str) or not idempotency_key:
		raise PublicationQueueError("Archive payload is missing idempotency_key.")
	if not isinstance(package_id, str) or not package_id:
		raise PublicationQueueError("Archive payload is missing package_id.")
	try:
		serialized = json.dumps(
			dict(payload),
			ensure_ascii=False,
			sort_keys=True,
			separators=(",", ":"),
			allow_nan=False,
		)
	except (TypeError, ValueError) as error:
		raise PublicationQueueError(f"Archive payload is not JSON serializable: {error}") from error
	return idempotency_key, package_id, serialized


def _validated_backend_url(backend_url: str) -> str:
	value = str(backend_url).strip().rstrip("/")
	parsed = urlsplit(value)
	if parsed.scheme not in {"http", "https"} or not parsed.netloc:
		raise PublicationQueueError("Backend URL must be an absolute HTTP(S) URL.")
	return value


class PublicationQueue:
	def __init__(self, database_path: str | Path | None = None) -> None:
		self.database_path = Path(database_path) if database_path is not None else default_queue_path()
		self._initialize()

	def _connect(self) -> sqlite3.Connection:
		connection = sqlite3.connect(self.database_path, timeout=10)
		connection.row_factory = sqlite3.Row
		connection.execute("PRAGMA busy_timeout = 10000")
		return connection

	@contextmanager
	def _open_connection(self):
		connection = self._connect()
		try:
			with connection:
				yield connection
		finally:
			connection.close()

	def _initialize(self) -> None:
		try:
			self.database_path.parent.mkdir(parents=True, exist_ok=True)
			with self._open_connection() as connection:
				connection.execute("PRAGMA journal_mode = WAL")
				connection.execute(
					"""
					CREATE TABLE IF NOT EXISTS pending_archives (
						idempotency_key TEXT PRIMARY KEY,
						package_id TEXT NOT NULL,
						backend_url TEXT NOT NULL,
						payload_json TEXT NOT NULL,
						attempts INTEGER NOT NULL CHECK (attempts >= 1),
						last_error TEXT NOT NULL,
						created_at TEXT NOT NULL,
						updated_at TEXT NOT NULL
					)
					"""
				)
				connection.execute(
					"CREATE INDEX IF NOT EXISTS idx_pending_archives_created "
					"ON pending_archives(created_at, idempotency_key)"
				)
		except sqlite3.Error as error:
			raise PublicationQueueError(f"Cannot initialize publication queue: {error}") from error

	def enqueue(
		self,
		payload: Mapping[str, Any],
		backend_url: str,
		last_error: str,
	) -> PendingArchive:
		idempotency_key, package_id, serialized = _validated_payload(payload)
		url = _validated_backend_url(backend_url)
		now = _utc_now()
		try:
			with self._open_connection() as connection:
				connection.execute(
					"""
					INSERT INTO pending_archives (
						idempotency_key, package_id, backend_url, payload_json,
						attempts, last_error, created_at, updated_at
					) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
					ON CONFLICT(idempotency_key) DO UPDATE SET
						package_id = excluded.package_id,
						backend_url = excluded.backend_url,
						payload_json = excluded.payload_json,
						attempts = pending_archives.attempts + 1,
						last_error = excluded.last_error,
						updated_at = excluded.updated_at
					""",
					(idempotency_key, package_id, url, serialized, str(last_error), now, now),
				)
		except sqlite3.Error as error:
			raise PublicationQueueError(f"Cannot enqueue archive synchronization: {error}") from error
		item = self.get(idempotency_key)
		if item is None:
			raise PublicationQueueError("Queued archive could not be read back.")
		return item

	def get(self, idempotency_key: str) -> PendingArchive | None:
		try:
			with self._open_connection() as connection:
				row = connection.execute(
					"SELECT * FROM pending_archives WHERE idempotency_key = ?",
					(idempotency_key,),
				).fetchone()
		except sqlite3.Error as error:
			raise PublicationQueueError(f"Cannot read publication queue: {error}") from error
		return self._from_row(row) if row is not None else None

	def list_pending(self) -> list[PendingArchive]:
		try:
			with self._open_connection() as connection:
				rows = connection.execute(
					"SELECT * FROM pending_archives ORDER BY created_at, idempotency_key"
				).fetchall()
		except sqlite3.Error as error:
			raise PublicationQueueError(f"Cannot list publication queue: {error}") from error
		return [self._from_row(row) for row in rows]

	def count(self) -> int:
		try:
			with self._open_connection() as connection:
				row = connection.execute("SELECT COUNT(*) AS count FROM pending_archives").fetchone()
		except sqlite3.Error as error:
			raise PublicationQueueError(f"Cannot count publication queue: {error}") from error
		return int(row["count"])

	def mark_failure(self, idempotency_key: str, last_error: str) -> None:
		try:
			with self._open_connection() as connection:
				result = connection.execute(
					"""
					UPDATE pending_archives
					SET attempts = attempts + 1, last_error = ?, updated_at = ?
					WHERE idempotency_key = ?
					""",
					(str(last_error), _utc_now(), idempotency_key),
				)
				if result.rowcount != 1:
					raise PublicationQueueError("Pending archive no longer exists.")
		except sqlite3.Error as error:
			raise PublicationQueueError(f"Cannot update publication queue: {error}") from error

	def complete(self, idempotency_key: str) -> None:
		try:
			with self._open_connection() as connection:
				connection.execute(
					"DELETE FROM pending_archives WHERE idempotency_key = ?",
					(idempotency_key,),
				)
		except sqlite3.Error as error:
			raise PublicationQueueError(f"Cannot complete queued archive: {error}") from error

	@staticmethod
	def _from_row(row: sqlite3.Row) -> PendingArchive:
		try:
			payload = json.loads(row["payload_json"])
		except (TypeError, json.JSONDecodeError) as error:
			raise PublicationQueueError("Queued archive payload is corrupted.") from error
		if not isinstance(payload, dict):
			raise PublicationQueueError("Queued archive payload must be an object.")
		return PendingArchive(
			idempotency_key=str(row["idempotency_key"]),
			package_id=str(row["package_id"]),
			backend_url=str(row["backend_url"]),
			payload=payload,
			attempts=int(row["attempts"]),
			last_error=str(row["last_error"]),
			created_at=str(row["created_at"]),
			updated_at=str(row["updated_at"]),
		)


__all__ = [
	"PendingArchive",
	"PublicationQueue",
	"PublicationQueueError",
	"default_queue_path",
]
