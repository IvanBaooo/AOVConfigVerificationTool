from __future__ import annotations

import ftplib
import hashlib
import json
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from backend_archive_contract_v1 import (
	ArchiveContractError,
	archive_create_headers,
	build_archive_record,
)


class PublicationError(RuntimeError):
	pass


class PublicationPreflightError(PublicationError):
	pass


class FtpUploadError(PublicationError):
	def __init__(self, message: str, *, cleanup_error: str | None = None) -> None:
		super().__init__(message)
		self.cleanup_error = cleanup_error


class PublicationCancelled(FtpUploadError):
	pass


class DuplicateRemoteFile(FtpUploadError):
	def __init__(self, filename: str, remote_size: int, local_size: int) -> None:
		super().__init__(f"FTP already contains {filename}.")
		self.filename = filename
		self.remote_size = remote_size
		self.local_size = local_size


class RemoteSizeMismatch(FtpUploadError):
	def __init__(self, filename: str, remote_size: int, local_size: int) -> None:
		super().__init__(
			f"FTP size mismatch for {filename}: remote={remote_size}, local={local_size}."
		)
		self.filename = filename
		self.remote_size = remote_size
		self.local_size = local_size


class BackendArchiveError(PublicationError):
	def __init__(self, message: str, *, status: int | None = None, code: str = "") -> None:
		super().__init__(message)
		self.status = status
		self.code = code


class RemoteFilePolicy(str, Enum):
	REQUIRE_ABSENT = "require_absent"
	USE_EXISTING = "use_existing"
	REPLACE = "replace"


@dataclass(frozen=True)
class FtpSettings:
	host: str
	port: int = 21
	username: str = ""
	password: str = ""
	remote_directory: str = "/"
	timeout_seconds: float = 30.0
	passive: bool = True

	def __post_init__(self) -> None:
		if not self.host.strip():
			raise ValueError("FTP host is required.")
		if not 1 <= self.port <= 65535:
			raise ValueError("FTP port must be 1-65535.")
		if not self.remote_directory.strip():
			raise ValueError("FTP remote directory is required.")
		if self.timeout_seconds <= 0:
			raise ValueError("FTP timeout must be positive.")


@dataclass(frozen=True)
class BackendSettings:
	base_url: str
	access_token: str = ""
	timeout_seconds: float = 30.0

	def __post_init__(self) -> None:
		parsed = urlsplit(self.base_url.strip())
		if parsed.scheme not in {"http", "https"} or not parsed.netloc:
			raise ValueError("Backend URL must be an absolute HTTP(S) URL.")

		if self.timeout_seconds <= 0:
			raise ValueError("Backend timeout must be positive.")


@dataclass(frozen=True)
class RemoteFileInfo:
	filename: str
	exists: bool
	remote_size: int | None
	local_size: int


@dataclass(frozen=True)
class FtpProgress:
	filename: str
	transferred_bytes: int
	total_bytes: int


@dataclass(frozen=True)
class FtpUploadResult:
	outcome: str
	filename: str
	remote_directory: str
	size: int


@dataclass(frozen=True)
class ArchiveSyncResult:
	outcome: str
	package_id: str


@dataclass(frozen=True)
class PublicationResult:
	ftp: FtpUploadResult
	archive: ArchiveSyncResult


class PublicationPartialFailure(PublicationError):
	def __init__(
		self,
		ftp_result: FtpUploadResult,
		backend_error: BackendArchiveError,
		*,
		queued: bool = False,
		queue_error: str = "",
	) -> None:
		super().__init__(f"FTP completed but backend archive failed: {backend_error}")
		self.ftp_result = ftp_result
		self.backend_error = backend_error
		self.queued = queued
		self.queue_error = queue_error


ProgressCallback = Callable[[FtpProgress], None]
StageCallback = Callable[[str], None]


class FtpClient(Protocol):
	def connect(self, host: str, port: int, timeout: float): ...
	def login(self, username: str, password: str): ...
	def set_pasv(self, passive: bool): ...
	def cwd(self, directory: str): ...
	def voidcmd(self, command: str): ...
	def size(self, filename: str): ...
	def storbinary(self, command: str, file_object, blocksize: int, callback): ...
	def delete(self, filename: str): ...
	def quit(self): ...
	def close(self): ...


def _hash_file(path: Path, algorithm: str) -> str:
	digest = hashlib.new(algorithm)
	with path.open("rb") as file_object:
		for chunk in iter(lambda: file_object.read(1024 * 1024), b""):
			digest.update(chunk)
	return digest.hexdigest()


def build_verified_archive_payload(
	report_path: str | Path,
	archive_path: str | Path | None = None,
	acknowledgments: list[dict[str, str]] | None = None,
) -> dict[str, object]:
	report_file = Path(report_path)
	try:
		report = json.loads(report_file.read_text(encoding="utf-8"))
	except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
		raise PublicationPreflightError(f"Cannot read package report: {error}") from error
	if acknowledgments is not None and isinstance(report, dict):
		validation = report.get("validation")
		if isinstance(validation, dict):
			validation["acknowledgments"] = list(acknowledgments)
	try:
		payload = build_archive_record(report)
	except ArchiveContractError as error:
		raise PublicationPreflightError(f"Package report is invalid: {error}") from error

	if archive_path is None:
		return payload
	archive_file = Path(archive_path)
	if not archive_file.is_file():
		raise PublicationPreflightError(f"Archive file does not exist: {archive_file}")
	package = report.get("package") if isinstance(report, dict) else None
	if not isinstance(package, dict):
		raise PublicationPreflightError("Package report is missing package metadata.")
	if package.get("name") != archive_file.name:
		raise PublicationPreflightError("Archive filename does not match the package report.")
	for algorithm in ("md5", "sha256"):
		expected = package.get(algorithm)
		if not isinstance(expected, str) or _hash_file(archive_file, algorithm) != expected.lower():
			raise PublicationPreflightError(
				f"Archive {algorithm.upper()} does not match the package report."
			)
	return payload


class FtpPublisher:
	def __init__(self, ftp_factory: Callable[[], FtpClient] = ftplib.FTP) -> None:
		self._ftp_factory = ftp_factory

	def check_connection(self, settings: FtpSettings) -> None:
		ftp = self._connect(settings)
		self._disconnect(ftp)
	def inspect(self, archive_path: str | Path, settings: FtpSettings) -> RemoteFileInfo:
		archive_file = self._archive_file(archive_path)
		ftp = self._connect(settings)
		try:
			remote_size = self._remote_size(ftp, archive_file.name)
			return RemoteFileInfo(
				filename=archive_file.name,
				exists=remote_size is not None,
				remote_size=remote_size,
				local_size=archive_file.stat().st_size,
			)
		except ftplib.all_errors as error:
			raise FtpUploadError(f"Cannot inspect FTP destination: {error}") from error
		finally:
			self._disconnect(ftp)

	def upload(
		self,
		archive_path: str | Path,
		settings: FtpSettings,
		*,
		policy: RemoteFilePolicy,
		progress: ProgressCallback | None = None,
		cancel_event: threading.Event | None = None,
		block_size: int = 64 * 1024,
	) -> FtpUploadResult:
		if block_size <= 0:
			raise ValueError("FTP block size must be positive.")
		archive_file = self._archive_file(archive_path)
		local_size = archive_file.stat().st_size
		ftp = self._connect(settings)
		try:
			remote_size = self._remote_size(ftp, archive_file.name)
			if remote_size is not None:
				if policy is RemoteFilePolicy.REQUIRE_ABSENT:
					raise DuplicateRemoteFile(archive_file.name, remote_size, local_size)
				if policy is RemoteFilePolicy.USE_EXISTING:
					if remote_size != local_size:
						raise RemoteSizeMismatch(archive_file.name, remote_size, local_size)
					return FtpUploadResult(
						"existing_confirmed",
						archive_file.name,
						settings.remote_directory,
						local_size,
					)
				self._delete(ftp, archive_file.name)
			elif policy is RemoteFilePolicy.USE_EXISTING:
				raise FtpUploadError("The confirmed existing FTP file is no longer present.")

			if cancel_event is not None and cancel_event.is_set():
				raise PublicationCancelled("FTP upload was cancelled before it started.")
			transferred = 0

			def on_chunk(chunk: bytes) -> None:
				nonlocal transferred
				if cancel_event is not None and cancel_event.is_set():
					raise PublicationCancelled("FTP upload was cancelled.")
				transferred += len(chunk)
				if progress is not None:
					progress(FtpProgress(archive_file.name, transferred, local_size))

			try:
				with archive_file.open("rb") as file_object:
					ftp.storbinary(
						f"STOR {archive_file.name}",
						file_object,
						block_size,
						on_chunk,
					)
				if cancel_event is not None and cancel_event.is_set():
					raise PublicationCancelled("FTP upload was cancelled.")
			except Exception as error:
				cleanup_error = self._cleanup_partial(ftp, archive_file.name)
				if isinstance(error, FtpUploadError):
					error.cleanup_error = cleanup_error
					raise
				raise FtpUploadError(
					f"FTP upload failed: {error}",
					cleanup_error=cleanup_error,
				) from error

			remote_size = self._remote_size(ftp, archive_file.name)
			if remote_size != local_size:
				cleanup_error = self._cleanup_partial(ftp, archive_file.name)
				error = RemoteSizeMismatch(archive_file.name, remote_size or 0, local_size)
				error.cleanup_error = cleanup_error
				raise error
			return FtpUploadResult(
				"uploaded",
				archive_file.name,
				settings.remote_directory,
				local_size,
			)
		except FtpUploadError:
			raise
		except ftplib.all_errors as error:
			raise FtpUploadError(f"FTP operation failed: {error}") from error
		finally:
			self._disconnect(ftp)

	@staticmethod
	def _archive_file(archive_path: str | Path) -> Path:
		archive_file = Path(archive_path)
		if not archive_file.is_file():
			raise FtpUploadError(f"Archive file does not exist: {archive_file}")
		if not archive_file.name.endswith(".tar.gz"):
			raise FtpUploadError("Only .tar.gz archives can be uploaded to FTP.")
		return archive_file

	def _connect(self, settings: FtpSettings) -> FtpClient:
		ftp = self._ftp_factory()
		try:
			ftp.connect(settings.host.strip(), settings.port, settings.timeout_seconds)
			ftp.login(settings.username, settings.password)
			ftp.set_pasv(settings.passive)
			ftp.cwd(settings.remote_directory)
			ftp.voidcmd("TYPE I")
			return ftp
		except ftplib.all_errors as error:
			self._disconnect(ftp)
			raise FtpUploadError(f"Cannot connect to FTP: {error}") from error

	@staticmethod
	def _remote_size(ftp: FtpClient, filename: str) -> int | None:
		try:
			size = ftp.size(filename)
		except ftplib.error_perm as error:
			if str(error).startswith("550"):
				return None
			raise
		return int(size) if size is not None else None

	@staticmethod
	def _delete(ftp: FtpClient, filename: str) -> None:
		try:
			ftp.delete(filename)
		except ftplib.all_errors as error:
			raise FtpUploadError(f"Cannot delete existing FTP file: {error}") from error

	@staticmethod
	def _cleanup_partial(ftp: FtpClient, filename: str) -> str | None:
		try:
			ftp.delete(filename)
			return None
		except ftplib.all_errors as error:
			message = str(error).lower()
			if message.startswith("550") and any(
				marker in message
				for marker in ("not found", "no such file", "cannot find")
			):
				return None
			return str(error)

	@staticmethod
	def _disconnect(ftp: FtpClient) -> None:
		try:
			ftp.close()
		except Exception:
			pass


class ArchiveBackendClient:
	def __init__(self, opener=urlopen) -> None:
		self._opener = opener

	def sync_report(
		self,
		report_path: str | Path,
		settings: BackendSettings,
		acknowledgments: list[dict[str, str]] | None = None,
	) -> ArchiveSyncResult:
		return self.sync_payload(
			build_verified_archive_payload(report_path, acknowledgments=acknowledgments), settings
		)

	def sync_payload(
		self,
		payload: dict[str, object],
		settings: BackendSettings,
	) -> ArchiveSyncResult:
		headers = archive_create_headers(payload)
		if settings.access_token:
			headers["Authorization"] = f"Bearer {settings.access_token}"
		request = Request(
			settings.base_url.rstrip("/") + "/api/v1/package-archives",
			data=json.dumps(
				payload,
				ensure_ascii=False,
				separators=(",", ":"),
			).encode("utf-8"),
			headers=headers,
			method="POST",
		)
		try:
			with self._opener(request, timeout=settings.timeout_seconds) as response:
				status = response.status
				response_data = json.loads(response.read().decode("utf-8"))
		except HTTPError as error:
			response_data = self._read_error(error)
			error_data = response_data.get("error", {}) if isinstance(response_data, dict) else {}
			code = str(error_data.get("code", "")) if isinstance(error_data, dict) else ""
			message = (
				str(error_data.get("message", ""))
				if isinstance(error_data, dict)
				else ""
			)
			raise BackendArchiveError(
				message or f"Backend archive request failed with HTTP {error.code}.",
				status=error.code,
				code=code,
			) from error
		except (OSError, URLError, UnicodeDecodeError, json.JSONDecodeError) as error:
			raise BackendArchiveError(f"Cannot reach archive backend: {error}") from error

		if status not in {200, 201} or not isinstance(response_data, dict):
			raise BackendArchiveError(
				f"Unexpected archive backend response: HTTP {status}.",
				status=status,
			)
		outcome = response_data.get("result")
		if outcome not in {"created", "replayed"}:
			raise BackendArchiveError("Archive backend returned an unknown result.", status=status)
		return ArchiveSyncResult(str(outcome), str(payload["package_id"]))

	@staticmethod
	def _read_error(error: HTTPError) -> object:
		try:
			return json.loads(error.read().decode("utf-8"))
		except (UnicodeDecodeError, json.JSONDecodeError):
			return {}


class BackendClient(Protocol):
	def sync_report(
		self,
		report_path: str | Path,
		settings: BackendSettings,
		acknowledgments: list[dict[str, str]] | None = None,
	) -> ArchiveSyncResult: ...


class SyncQueue(Protocol):
	def enqueue(
		self,
		payload: dict[str, object],
		backend_url: str,
		last_error: str,
	): ...

	def complete(self, idempotency_key: str) -> None: ...


class ManualPublicationService:
	def __init__(
		self,
		*,
		ftp_publisher: FtpPublisher | None = None,
		backend_client: BackendClient | None = None,
		sync_queue: SyncQueue | None = None,
	) -> None:
		self.ftp_publisher = ftp_publisher or FtpPublisher()
		self.backend_client = backend_client or ArchiveBackendClient()
		self.sync_queue = sync_queue

	def publish(
		self,
		*,
		archive_path: str | Path,
		report_path: str | Path,
		ftp_settings: FtpSettings,
		backend_settings: BackendSettings,
		policy: RemoteFilePolicy,
		acknowledgments: list[dict[str, str]] | None = None,
		progress: ProgressCallback | None = None,
		cancel_event: threading.Event | None = None,
		stage: StageCallback | None = None,
	) -> PublicationResult:
		if stage is not None:
			stage("preflight")
		payload = build_verified_archive_payload(report_path, archive_path, acknowledgments=acknowledgments)
		if stage is not None:
			stage("ftp_upload")
		ftp_result = self.ftp_publisher.upload(
			archive_path,
			ftp_settings,
			policy=policy,
			progress=progress,
			cancel_event=cancel_event,
		)
		if stage is not None:
			stage("backend_archive")
		try:
			archive_result = self.backend_client.sync_report(
				report_path, backend_settings, acknowledgments=acknowledgments
			)
		except BackendArchiveError as error:
			queued = False
			queue_error = ""
			if self.sync_queue is not None:
				try:
					self.sync_queue.enqueue(payload, backend_settings.base_url, str(error))
					queued = True
				except Exception as enqueue_error:
					queue_error = str(enqueue_error)
			raise PublicationPartialFailure(
				ftp_result,
				error,
				queued=queued,
				queue_error=queue_error,
			) from error
		if self.sync_queue is not None:
			try:
				self.sync_queue.complete(str(payload["idempotency_key"]))
			except Exception:
				pass
		if stage is not None:
			stage("complete")
		return PublicationResult(ftp_result, archive_result)


__all__ = [
	"ArchiveBackendClient",
	"ArchiveSyncResult",
	"BackendArchiveError",
	"BackendSettings",
	"DuplicateRemoteFile",
	"FtpProgress",
	"FtpPublisher",
	"FtpSettings",
	"FtpUploadError",
	"FtpUploadResult",
	"ManualPublicationService",
	"PublicationCancelled",
	"PublicationError",
	"PublicationPartialFailure",
	"PublicationPreflightError",
	"PublicationResult",
	"RemoteFileInfo",
	"RemoteFilePolicy",
	"RemoteSizeMismatch",
	"build_verified_archive_payload",
]
