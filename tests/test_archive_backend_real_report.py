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


class ArchiveBackendRealReportTests(unittest.TestCase):
	def test_latest_tw_report_create_replay_list_and_detail(self) -> None:
		root = Path(__file__).parent.parent
		report_path = (
			root
			/ "output"
			/ "sgame_TW_Beta54_20260713153524"
			/ "sgame_TW_Beta54_20260713153524.report.json"
		)
		if not report_path.exists():
			self.skipTest("The real TW regression report is not present.")
		payload = build_archive_record(json.loads(report_path.read_text(encoding="utf-8")))

		with tempfile.TemporaryDirectory() as temp_dir:
			application = ArchiveApplication(
				repository=ArchiveRepository(Path(temp_dir) / "archives.sqlite3"),
				validator=ArchivePayloadValidator(),
				access_token="real-report-token",
			)
			server = create_http_server(application, host="127.0.0.1", port=0)
			thread = threading.Thread(target=server.serve_forever, daemon=True)
			thread.start()
			try:
				headers = {
					"Authorization": "Bearer real-report-token",
					"Content-Type": "application/json",
					"Idempotency-Key": payload["idempotency_key"],
					"X-AOV-Contract-Version": "1.0",
				}
				encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")

				def request(method: str, target: str, body: bytes | None = None):
					connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
					connection.request(method, target, body=body, headers=headers)
					response = connection.getresponse()
					response_body = json.loads(response.read().decode("utf-8"))
					status = response.status
					connection.close()
					return status, response_body

				created_status, _ = request("POST", "/api/v1/package-archives", encoded)
				replayed_status, replayed = request("POST", "/api/v1/package-archives", encoded)
				list_status, listing = request("GET", "/api/v1/package-archives?region_code=TW")
				detail_status, detail = request(
					"GET", f"/api/v1/package-archives/{payload['package_id']}"
				)

				self.assertEqual(created_status, 201)
				self.assertEqual(replayed_status, 200)
				self.assertEqual(replayed["result"], "replayed")
				self.assertEqual(list_status, 200)
				self.assertEqual(listing["items"][0]["file_count"], 20)
				self.assertEqual(detail_status, 200)
				self.assertEqual(detail["archive"]["validation"]["summary"]["warning_count"], 0)
			finally:
				server.shutdown()
				server.server_close()
				thread.join(timeout=5)


if __name__ == "__main__":
	unittest.main()
