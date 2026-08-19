from __future__ import annotations

import socket
import tempfile
import threading
import unittest
from pathlib import Path

from archive_backend.api import ArchiveApplication
from archive_backend.repository import ArchiveRepository
from archive_backend.schema_validation import ArchivePayloadValidator
from archive_backend.server import create_http_server


def read_socket_response(client: socket.socket) -> bytes:
	chunks: list[bytes] = []
	while True:
		chunk = client.recv(4096)
		if not chunk:
			return b"".join(chunks)
		chunks.append(chunk)


class ArchiveBackendHttpFramingTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		application = ArchiveApplication(
			repository=ArchiveRepository(Path(self.temp_dir.name) / "archives.sqlite3"),
			validator=ArchivePayloadValidator(),
			access_token="framing-token",
		)
		self.server = create_http_server(
			application,
			host="127.0.0.1",
			port=0,
			read_timeout_seconds=0.1,
		)
		self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
		self.thread.start()

	def tearDown(self) -> None:
		self.server.shutdown()
		self.server.server_close()
		self.thread.join(timeout=5)
		self.temp_dir.cleanup()

	def request(self, raw_request: bytes) -> bytes:
		client = socket.create_connection(("127.0.0.1", self.server.server_port), timeout=2)
		try:
			client.sendall(raw_request)
			return read_socket_response(client)
		finally:
			client.close()

	def test_missing_content_length_returns_411(self) -> None:
		response = self.request(
			b"POST /api/v1/package-archives HTTP/1.1\r\n"
			b"Host: 127.0.0.1\r\n"
			b"Authorization: Bearer framing-token\r\n\r\n"
		)
		self.assertIn(b"411", response)
		self.assertIn(b"length_required", response)

	def test_duplicate_content_length_is_rejected(self) -> None:
		response = self.request(
			b"POST /api/v1/package-archives HTTP/1.1\r\n"
			b"Host: 127.0.0.1\r\n"
			b"Authorization: Bearer framing-token\r\n"
			b"Content-Length: 0\r\nContent-Length: 0\r\n\r\n"
		)
		self.assertIn(b"400", response)
		self.assertIn(b"invalid_content_length", response)

	def test_authorized_incomplete_body_times_out_as_json(self) -> None:
		response = self.request(
			b"POST /api/v1/package-archives HTTP/1.1\r\n"
			b"Host: 127.0.0.1\r\n"
			b"Authorization: Bearer framing-token\r\n"
			b"Content-Length: 10\r\n\r\n{}"
		)
		self.assertIn(b"408", response)
		self.assertIn(b"request_timeout", response)

	def test_extremely_long_content_length_is_rejected(self) -> None:
		response = self.request(
			b"POST /api/v1/package-archives HTTP/1.1\r\n"
			b"Host: 127.0.0.1\r\n"
			b"Authorization: Bearer framing-token\r\n"
			+ b"Content-Length: "
			+ (b"9" * 5000)
			+ b"\r\n\r\n"
		)
		self.assertIn(b"413", response)
		self.assertIn(b"payload_too_large", response)


if __name__ == "__main__":
	unittest.main()
