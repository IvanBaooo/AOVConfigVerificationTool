from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from archive_backend.api import ArchiveApplication
from archive_backend.repository import ArchiveRepository
from archive_backend.schema_validation import ArchivePayloadValidator
from archive_backend.server import create_http_server
from backend_archive_contract_v1 import build_archive_record
from test_backend_archive_contract_v1 import final_sample_report


class ArchiveHttpServerTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		application = ArchiveApplication(
			repository=ArchiveRepository(Path(self.temp_dir.name) / "archives.sqlite3"),
			validator=ArchivePayloadValidator(),
			access_token="http-test-token",
		)
		self.server = create_http_server(application, host="127.0.0.1", port=0)
		self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
		self.thread.start()

	def tearDown(self) -> None:
		self.server.shutdown()
		self.server.server_close()
		self.thread.join(timeout=5)
		self.temp_dir.cleanup()

	def request(
		self,
		method: str,
		path: str,
		*,
		payload: dict[str, object] | None = None,
		headers: dict[str, str] | None = None,
	) -> tuple[int, dict[str, object], dict[str, str]]:
		connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
		body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
		connection.request(method, path, body=body, headers=headers or {})
		response = connection.getresponse()
		response_body = json.loads(response.read().decode("utf-8"))
		response_headers = dict(response.getheaders())
		connection.close()
		return response.status, response_body, response_headers

	def test_health_and_archive_round_trip_over_http(self) -> None:
		health_status, health, _ = self.request("GET", "/health")
		payload = build_archive_record(final_sample_report())
		headers = {
			"Authorization": "Bearer http-test-token",
			"Content-Type": "application/json",
			"Idempotency-Key": payload["idempotency_key"],
			"X-AOV-Contract-Version": "1.0",
		}
		create_status, created, create_headers = self.request(
			"POST", "/api/v1/package-archives", payload=payload, headers=headers
		)
		detail_status, detail, _ = self.request(
			"GET",
			f"/api/v1/package-archives/{payload['package_id']}",
			headers={"Authorization": "Bearer http-test-token"},
		)

		self.assertEqual(health_status, 200)
		self.assertEqual(health["status"], "ok")
		self.assertEqual(create_status, 201)
		self.assertEqual(created["result"], "created")
		self.assertEqual(create_headers["X-Content-Type-Options"], "nosniff")
		self.assertEqual(detail_status, 200)
		self.assertEqual(detail["archive"], payload)

	def test_oversized_request_is_rejected_before_json_parsing(self) -> None:
		self.server.shutdown()
		self.server.server_close()
		self.thread.join(timeout=5)

		application = ArchiveApplication(
			repository=ArchiveRepository(Path(self.temp_dir.name) / "small.sqlite3"),
			validator=ArchivePayloadValidator(),
			access_token="http-test-token",
		)
		self.server = create_http_server(
			application,
			host="127.0.0.1",
			port=0,
			max_body_bytes=32,
		)
		self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
		self.thread.start()

		status, body, _ = self.request(
			"POST",
			"/api/v1/package-archives",
			payload={"value": "x" * 100},
			headers={
				"Authorization": "Bearer http-test-token",
				"Content-Type": "application/json",
			},
		)
		self.assertEqual(status, 413)
		self.assertEqual(body["error"]["code"], "payload_too_large")


if __name__ == "__main__":
	unittest.main()
