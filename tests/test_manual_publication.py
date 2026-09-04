from __future__ import annotations

import ftplib
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path

from manual_publication import (
	ArchiveBackendClient,
	BackendArchiveError,
	BackendSettings,
	DuplicateRemoteFile,
	FtpPublisher,
	FtpSettings,
	FtpUploadError,
	ManualPublicationService,
	PublicationPartialFailure,
	RemoteFilePolicy,
	RemoteSizeMismatch,
)
from publication_queue import PublicationQueue
from test_backend_archive_contract_v1 import final_sample_report


class FakeFtpState:
	def __init__(self) -> None:
		self.files: dict[str, bytes] = {}
		self.commands: list[tuple[object, ...]] = []
		self.fail_upload = False
		self.fail_delete = False
		self.fail_before_upload = False
		self.cancel_after_store: threading.Event | None = None


def fake_ftp_factory(state: FakeFtpState):
	class FakeFtp:
		def connect(self, host, port, timeout):
			state.commands.append(("connect", host, port, timeout))

		def login(self, username, password):
			state.commands.append(("login", username, password))

		def set_pasv(self, passive):
			state.commands.append(("pasv", passive))

		def cwd(self, directory):
			state.commands.append(("cwd", directory))

		def voidcmd(self, command):
			state.commands.append(("voidcmd", command))
			return "200 OK"

		def size(self, filename):
			if filename not in state.files:
				raise ftplib.error_perm("550 Not found")
			return len(state.files[filename])

		def storbinary(self, command, file_object, blocksize, callback):
			filename = command.removeprefix("STOR ")
			state.commands.append(("store", filename))
			if state.fail_before_upload:
				raise OSError("simulated failure before remote creation")
			content = bytearray()
			while True:
				chunk = file_object.read(blocksize)
				if not chunk:
					break
				content.extend(chunk)
				state.files[filename] = bytes(content)
				callback(chunk)
				if state.fail_upload:
					raise OSError("simulated upload failure")
			state.files[filename] = bytes(content)
			if state.cancel_after_store is not None:
				state.cancel_after_store.set()
			return "226 Transfer complete"

		def delete(self, filename):
			state.commands.append(("delete", filename))
			if state.fail_delete:
				raise ftplib.error_perm("550 Delete denied")
			if filename not in state.files:
				raise ftplib.error_perm("550 Not found")
			state.files.pop(filename)

		def quit(self):
			state.commands.append(("quit",))

		def close(self):
			state.commands.append(("close",))

	return FakeFtp


class FakeHttpResponse:
	def __init__(self, status: int, body: dict[str, object]) -> None:
		self.status = status
		self._body = json.dumps(body).encode("utf-8")

	def __enter__(self):
		return self

	def __exit__(self, *_args):
		return False

	def read(self) -> bytes:
		return self._body


class ManualPublicationTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.root = Path(self.temp_dir.name)
		self.archive_path = self.root / "sgame_TW_Beta54_20260713153524.tar.gz"
		self.archive_path.write_bytes(b"archive-content")
		self.report_path = self.root / "package.report.json"
		report = final_sample_report()
		report["package"]["name"] = self.archive_path.name
		report["package"]["md5"] = hashlib.md5(self.archive_path.read_bytes()).hexdigest()
		report["package"]["sha256"] = hashlib.sha256(self.archive_path.read_bytes()).hexdigest()
		self.report_path.write_text(
			json.dumps(report, ensure_ascii=False),
			encoding="utf-8",
		)
		self.ftp_settings = FtpSettings(
			host="ftp.example.test",
			port=21,
			username="publisher",
			password="secret",
			remote_directory="/release/TW",
		)

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def publisher(self, state: FakeFtpState) -> FtpPublisher:
		return FtpPublisher(ftp_factory=fake_ftp_factory(state))

	def test_upload_uses_formal_filename_and_reports_progress(self) -> None:
		state = FakeFtpState()
		progress = []
		result = self.publisher(state).upload(
			self.archive_path,
			self.ftp_settings,
			policy=RemoteFilePolicy.REQUIRE_ABSENT,
			progress=progress.append,
		)

		self.assertEqual(result.outcome, "uploaded")
		self.assertEqual(state.files[self.archive_path.name], self.archive_path.read_bytes())
		self.assertFalse(any(name.endswith(".part") for name in state.files))
		self.assertEqual(progress[-1].transferred_bytes, self.archive_path.stat().st_size)
		self.assertEqual(progress[-1].total_bytes, self.archive_path.stat().st_size)

	def test_disconnect_closes_without_waiting_for_ftp_quit(self) -> None:
		state = FakeFtpState()
		self.publisher(state).inspect(self.archive_path, self.ftp_settings)
		self.assertIn(("close",), state.commands)
		self.assertNotIn(("quit",), state.commands)
	def test_existing_same_size_can_be_confirmed_without_upload(self) -> None:
		state = FakeFtpState()
		state.files[self.archive_path.name] = b"x" * self.archive_path.stat().st_size
		result = self.publisher(state).upload(
			self.archive_path,
			self.ftp_settings,
			policy=RemoteFilePolicy.USE_EXISTING,
		)

		self.assertEqual(result.outcome, "existing_confirmed")
		self.assertFalse(any(command[0] == "store" for command in state.commands))

	def test_existing_file_requires_confirmation_and_matching_size(self) -> None:
		state = FakeFtpState()
		state.files[self.archive_path.name] = b"different-size"
		with self.assertRaises(DuplicateRemoteFile):
			self.publisher(state).upload(
				self.archive_path,
				self.ftp_settings,
				policy=RemoteFilePolicy.REQUIRE_ABSENT,
			)
		with self.assertRaises(RemoteSizeMismatch):
			self.publisher(state).upload(
				self.archive_path,
				self.ftp_settings,
				policy=RemoteFilePolicy.USE_EXISTING,
			)

	def test_failed_upload_removes_partial_formal_file(self) -> None:
		state = FakeFtpState()
		state.fail_upload = True
		with self.assertRaises(FtpUploadError) as captured:
			self.publisher(state).upload(
				self.archive_path,
				self.ftp_settings,
				policy=RemoteFilePolicy.REQUIRE_ABSENT,
			)
		self.assertNotIn(self.archive_path.name, state.files)
		self.assertIsNone(captured.exception.cleanup_error)

	def test_cancelled_upload_removes_partial_formal_file(self) -> None:
		state = FakeFtpState()
		cancel_event = threading.Event()

		def cancel_after_first_block(_progress) -> None:
			cancel_event.set()

		with self.assertRaises(FtpUploadError):
			self.publisher(state).upload(
				self.archive_path,
				self.ftp_settings,
				policy=RemoteFilePolicy.REQUIRE_ABSENT,
				progress=cancel_after_first_block,
				cancel_event=cancel_event,
				block_size=4,
			)
		self.assertNotIn(self.archive_path.name, state.files)

	def test_cancel_after_transfer_does_not_continue_to_backend(self) -> None:
		state = FakeFtpState()
		cancel_event = threading.Event()
		state.cancel_after_store = cancel_event

		with self.assertRaises(FtpUploadError):
			self.publisher(state).upload(
				self.archive_path,
				self.ftp_settings,
				policy=RemoteFilePolicy.REQUIRE_ABSENT,
				cancel_event=cancel_event,
			)
		self.assertNotIn(self.archive_path.name, state.files)

	def test_cleanup_treats_missing_remote_file_as_success(self) -> None:
		state = FakeFtpState()
		state.fail_before_upload = True
		with self.assertRaises(FtpUploadError) as captured:
			self.publisher(state).upload(
				self.archive_path,
				self.ftp_settings,
				policy=RemoteFilePolicy.REQUIRE_ABSENT,
			)
		self.assertIsNone(captured.exception.cleanup_error)

	def test_backend_client_posts_final_contract_with_required_headers(self) -> None:
		requests = []

		def opener(request, timeout):
			requests.append((request, timeout))
			return FakeHttpResponse(
				201,
				{"result": "created", "archive": {"package_id": "package-id"}},
			)

		client = ArchiveBackendClient(opener=opener)
		result = client.sync_report(
			self.report_path,
			BackendSettings("http://127.0.0.1:8780", "backend-token"),
		)

		request, timeout = requests[0]
		payload = json.loads(request.data.decode("utf-8"))
		self.assertEqual(result.outcome, "created")
		self.assertEqual(request.full_url, "http://127.0.0.1:8780/api/v1/package-archives")
		self.assertEqual(request.get_header("Authorization"), "Bearer backend-token")
		self.assertEqual(request.get_header("Idempotency-key"), payload["idempotency_key"])
		self.assertEqual(timeout, 30.0)

	def test_backend_client_omits_authorization_when_token_is_disabled(self) -> None:
		requests = []

		def opener(request, timeout):
			requests.append(request)
			return FakeHttpResponse(
				201,
				{"result": "created", "archive": {"package_id": "package-id"}},
			)

		ArchiveBackendClient(opener=opener).sync_report(
			self.report_path,
			BackendSettings("http://127.0.0.1:8780"),
		)

		self.assertIsNone(requests[0].get_header("Authorization"))

	def test_backend_error_preserves_ftp_success_and_queues_manual_retry(self) -> None:
		state = FakeFtpState()
		sync_queue = PublicationQueue(self.root / "publication-queue.sqlite3")

		class FailingBackend:
			def sync_report(self, *_args, **_kwargs):
				raise BackendArchiveError("backend unavailable")

		service = ManualPublicationService(
			ftp_publisher=self.publisher(state),
			backend_client=FailingBackend(),
			sync_queue=sync_queue,
		)
		with self.assertRaises(PublicationPartialFailure) as captured:
			service.publish(
				archive_path=self.archive_path,
				report_path=self.report_path,
				ftp_settings=self.ftp_settings,
				backend_settings=BackendSettings("http://127.0.0.1:8780"),
				policy=RemoteFilePolicy.REQUIRE_ABSENT,
			)

		self.assertEqual(captured.exception.ftp_result.outcome, "uploaded")
		self.assertTrue(captured.exception.queued)
		self.assertIn(self.archive_path.name, state.files)
		pending = sync_queue.list_pending()
		self.assertEqual(len(pending), 1)
		self.assertEqual(pending[0].package_id, captured.exception.ftp_result.filename.removesuffix(".tar.gz"))
		self.assertNotIn("access_token", pending[0].payload)


if __name__ == "__main__":
	unittest.main()
