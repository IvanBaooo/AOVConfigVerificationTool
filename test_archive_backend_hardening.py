from __future__ import annotations

import http.client
import json
import socket
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from archive_backend.api import ArchiveApplication
from archive_backend.repository import ArchiveRepository
from archive_backend.schema_validation import ArchivePayloadValidator
from archive_backend.server import create_http_server
from backend_archive_contract_v1 import build_archive_record
from test_backend_archive_contract_v1 import final_sample_report


def read_socket_response(client: socket.socket) -> bytes:
	chunks: list[bytes] = []
	while True:
		chunk = client.recv(4096)
		if not chunk:
			return b"".join(chunks)
		chunks.append(chunk)

class ArchiveBackendHardeningTests(unittest.TestCase):
	def application(self, database_path: Path) -> ArchiveApplication:
		return ArchiveApplication(
			repository=ArchiveRepository(database_path),
			validator=ArchivePayloadValidator(),
			access_token="hardening-token",
		)

	def test_huge_offset_returns_invalid_query(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			application = self.application(Path(temp_dir) / "archives.sqlite3")
			response = application.handle(
				"GET",
				f"/api/v1/package-archives?offset={2**80}",
				{"Authorization": "Bearer hardening-token"},
			)
		self.assertEqual(response.status, 400)
		self.assertEqual(response.body["error"]["code"], "invalid_query")

	def test_list_count_and_items_share_one_snapshot(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			database_path = Path(temp_dir) / "archives.sqlite3"
			repository = ArchiveRepository(database_path)
			first = build_archive_record(final_sample_report())
			repository.create_archive(first)

			count_executed = threading.Event()
			allow_page_query = threading.Event()
			original_connect = repository._connect

			class PausingConnection:
				def __init__(self, connection):
					self.connection = connection

				def execute(self, sql, parameters=()):
					cursor = self.connection.execute(sql, parameters)
					if "SELECT COUNT(*)" in sql:
						count_executed.set()
						allow_page_query.wait(timeout=5)
					return cursor

				def __getattr__(self, name):
					return getattr(self.connection, name)

			repository._connect = lambda: PausingConnection(original_connect())
			with ThreadPoolExecutor(max_workers=1) as executor:
				future = executor.submit(repository.list_archives)
				self.assertTrue(count_executed.wait(timeout=5))
				second = json.loads(json.dumps(first))
				second["package_id"] = "sgame_TH_Beta54_20260713170000"
				second["idempotency_key"] = second["package_id"]
				second["release"]["region_code"] = "TH"
				second["release"]["region_dir"] = "Thailand"
				ArchiveRepository(database_path).create_archive(second)
				allow_page_query.set()
				result = future.result(timeout=5)

			self.assertEqual(result["total"], 1)
			self.assertEqual(len(result["items"]), 1)

	def test_internal_error_returns_json_503_for_health(self) -> None:
		class FailingApplication:
			def handle(self, *args, **kwargs):
				raise RuntimeError("sensitive database detail")

		server = create_http_server(FailingApplication(), host="127.0.0.1", port=0)
		thread = threading.Thread(target=server.serve_forever, daemon=True)
		thread.start()
		try:
			connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
			connection.request("GET", "/health")
			response = connection.getresponse()
			body = json.loads(response.read().decode("utf-8"))
			connection.close()
			self.assertEqual(response.status, 503)
			self.assertEqual(body["error"]["code"], "service_unavailable")
			self.assertNotIn("sensitive", json.dumps(body))
		finally:
			server.shutdown()
			server.server_close()
			thread.join(timeout=5)

	def test_unauthorized_request_is_rejected_without_reading_body(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			server = create_http_server(
				self.application(Path(temp_dir) / "archives.sqlite3"),
				host="127.0.0.1",
				port=0,
				read_timeout_seconds=0.2,
			)
			thread = threading.Thread(target=server.serve_forever, daemon=True)
			thread.start()
			try:
				client = socket.create_connection(("127.0.0.1", server.server_port), timeout=2)
				started = time.monotonic()
				client.sendall(
					b"POST /api/v1/package-archives HTTP/1.1\r\n"
					b"Host: 127.0.0.1\r\nContent-Length: 999\r\n\r\n"
				)
				response = client.recv(4096)
				elapsed = time.monotonic() - started
				client.close()
				self.assertIn(b"401", response)
				self.assertLess(elapsed, 0.2)
			finally:
				server.shutdown()
				server.server_close()
				thread.join(timeout=5)

	def test_transfer_encoding_is_rejected(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			server = create_http_server(
				self.application(Path(temp_dir) / "archives.sqlite3"),
				host="127.0.0.1",
				port=0,
			)
			thread = threading.Thread(target=server.serve_forever, daemon=True)
			thread.start()
			try:
				client = socket.create_connection(("127.0.0.1", server.server_port), timeout=2)
				client.sendall(
					b"POST /api/v1/package-archives HTTP/1.1\r\n"
					b"Host: 127.0.0.1\r\n"
					b"Authorization: Bearer hardening-token\r\n"
					b"Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n"
				)
				response = read_socket_response(client)
				client.close()
				self.assertIn(b"400", response)
				self.assertIn(b"unsupported_transfer_encoding", response)
			finally:
				server.shutdown()
				server.server_close()
				thread.join(timeout=5)


if __name__ == "__main__":
	unittest.main()
