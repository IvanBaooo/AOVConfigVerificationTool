from __future__ import annotations

import io
import json
import unittest
from urllib.error import HTTPError, URLError

from release_baseline_client import ReleaseBaselineClient, ReleaseBaselineClientError


class FakeResponse:
	def __init__(self, payload: object) -> None:
		self.body = json.dumps(payload).encode("utf-8")

	def __enter__(self):
		return self

	def __exit__(self, *_args):
		return False

	def read(self) -> bytes:
		return self.body


class ReleaseBaselineClientTests(unittest.TestCase):
	def payload(self) -> dict[str, object]:
		return {
			"baseline": {
				"region_code": "TW",
				"package_id": "sgame_TW_Beta54_20260714120000",
				"release_time": "2026-07-14T04:01:00Z",
				"package_created_at": "2026-07-14T12:00:00+08:00",
				"released_revision_spec": "r1700001,r1700003",
				"released_revisions": [1700001, 1700003],
				"last_checked_revision": 1700003,
				"package_version": "Beta54",
			}
		}

	def test_health_check_reports_connection_and_auth_mode(self) -> None:
		client = ReleaseBaselineClient(opener=lambda *_args, **_kwargs: FakeResponse({
			"status": "ok",
			"service": "aov-archive-backend",
			"auth_required": False,
		}))

		health = client.check_health(base_url="http://127.0.0.1:8780/")

		self.assertEqual(health.status, "ok")
		self.assertEqual(health.service, "aov-archive-backend")
		self.assertFalse(health.auth_required)

	def test_fetches_valid_baseline_and_sends_optional_token(self) -> None:
		captured = {}
		def opener(request, timeout):
			captured["request"] = request
			captured["timeout"] = timeout
			return FakeResponse(self.payload())

		baseline = ReleaseBaselineClient(opener=opener).fetch(
			base_url="http://127.0.0.1:8780/",
			region_code="tw",
			access_token="secret",
		)

		self.assertEqual(baseline.released_revision_spec, "r1700001,r1700003")
		self.assertEqual(baseline.last_checked_revision, 1700003)
		self.assertIn("region_code=TW", captured["request"].full_url)
		self.assertEqual(captured["request"].get_header("Authorization"), "Bearer secret")

	def test_rejects_inconsistent_or_empty_revision_baseline(self) -> None:
		payload = self.payload()
		payload["baseline"]["last_checked_revision"] = 1700001
		client = ReleaseBaselineClient(opener=lambda *_args, **_kwargs: FakeResponse(payload))
		with self.assertRaisesRegex(ReleaseBaselineClientError, "inconsistent"):
			client.fetch(base_url="http://localhost:8780", region_code="TW")

	def test_http_and_connection_failures_are_readable(self) -> None:
		error_body = io.BytesIO(json.dumps({"error": {"message": "No baseline yet."}}).encode("utf-8"))
		http_error = HTTPError("http://localhost", 404, "not found", {}, error_body)
		with self.assertRaisesRegex(ReleaseBaselineClientError, "No baseline yet"):
			ReleaseBaselineClient(opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(http_error)).fetch(
				base_url="http://localhost:8780", region_code="TW"
			)
		with self.assertRaisesRegex(ReleaseBaselineClientError, "Cannot connect"):
			ReleaseBaselineClient(
				opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline"))
			).fetch(base_url="http://localhost:8780", region_code="TW")


if __name__ == "__main__":
	unittest.main()