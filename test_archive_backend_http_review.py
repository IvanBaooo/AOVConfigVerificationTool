from __future__ import annotations

import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from archive_backend.api import ArchiveApplication
from archive_backend.repository import ArchiveRepository
from archive_backend.schema_validation import ArchivePayloadValidator
from archive_backend.server import _handler_class, create_http_server


def read_socket_response(client: socket.socket) -> bytes:
	chunks: list[bytes] = []
	while True:
		chunk = client.recv(4096)
		if not chunk:
			return b"".join(chunks)
		chunks.append(chunk)


class ArchiveBackendHttpReviewTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.application = ArchiveApplication(
			repository=ArchiveRepository(Path(self.temp_dir.name) / "archives.sqlite3"),
			validator=ArchivePayloadValidator(),
			access_token="review-token",
		)
		self.servers: list[tuple[object, threading.Thread]] = []

	def tearDown(self) -> None:
		for server, thread in self.servers:
			server.shutdown()
			server.server_close()
			thread.join(timeout=5)
		self.temp_dir.cleanup()

	def start_server(self, **options):
		server = create_http_server(
			self.application,
			host="127.0.0.1",
			port=0,
			**options,
		)
		thread = threading.Thread(target=server.serve_forever, daemon=True)
		thread.start()
		self.servers.append((server, thread))
		return server

	def raw_request(self, server, request: bytes) -> bytes:
		client = socket.create_connection(("127.0.0.1", server.server_port), timeout=2)
		try:
			client.sendall(request)
			return read_socket_response(client)
		finally:
			client.close()

	def test_get_request_body_is_rejected_and_connection_closed(self) -> None:
		server = self.start_server()
		response = self.raw_request(
			server,
			b"GET /health HTTP/1.1\r\n"
			b"Host: 127.0.0.1\r\nContent-Length: 4\r\n\r\njunk",
		)
		self.assertIn(b"400", response)
		self.assertIn(b"request_body_not_allowed", response)
		self.assertIn(b"Connection: close", response)

	def test_total_request_deadline_stops_slow_body(self) -> None:
		server = self.start_server(read_timeout_seconds=0.2)
		client = socket.create_connection(("127.0.0.1", server.server_port), timeout=2)
		stop = threading.Event()
		client.sendall(
			b"POST /api/v1/package-archives HTTP/1.1\r\n"
			b"Host: 127.0.0.1\r\n"
			b"Authorization: Bearer review-token\r\n"
			b"Content-Length: 100\r\n\r\n"
		)

		def drip_body() -> None:
			while not stop.wait(0.05):
				try:
					client.sendall(b"x")
				except OSError:
					return

		sender = threading.Thread(target=drip_body, daemon=True)
		sender.start()
		started = time.monotonic()
		try:
			response = read_socket_response(client)
		finally:
			stop.set()
			sender.join(timeout=2)
			client.close()
		elapsed = time.monotonic() - started
		self.assertIn(b"408", response)
		self.assertIn(b"request_timeout", response)
		self.assertLess(elapsed, 0.8)

	def test_malformed_target_returns_stable_400(self) -> None:
		application_response = self.application.handle(
			"GET",
			"http://[",
			{"Authorization": "Bearer review-token"},
		)
		self.assertEqual(application_response.status, 400)
		self.assertEqual(application_response.body["error"]["code"], "invalid_target")

		server = self.start_server()
		http_response = self.raw_request(
			server,
			b"GET http://[ HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
		)
		self.assertIn(b"400", http_response)
		self.assertIn(b"invalid_target", http_response)

	def test_log_message_escapes_control_characters(self) -> None:
		handler_type = _handler_class(self.application, 1024, 1.0)
		handler = handler_type.__new__(handler_type)
		handler.client_address = ("127.0.0.1", 12345)
		with self.assertLogs("aov.archive_backend", level="INFO") as captured:
			handler.log_message("%s", "\x1b[31m forged\r\nline")
		log_text = "\n".join(captured.output)
		self.assertNotIn("\x1b", log_text)
		self.assertNotIn("forged\r\nline", log_text)
		self.assertIn("\\x1b", log_text)

	def test_worker_limit_must_be_positive(self) -> None:
		with self.assertRaises(ValueError):
			create_http_server(self.application, host="127.0.0.1", port=0, max_workers=0)


if __name__ == "__main__":
	unittest.main()
