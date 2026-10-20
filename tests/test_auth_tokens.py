from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from archive_backend.api import ArchiveApplication
from archive_backend.repository import ArchiveRepository
from archive_backend.schema_validation import ArchivePayloadValidator


class FakeGoogleVerifier:
	def verify(self, credential: str) -> dict[str, str]:
		if credential != "admin-cred":
			raise ValueError("invalid credential")
		return {"email": "admin@example.com", "display_name": "Admin"}


class ApiTokenTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.repository = ArchiveRepository(Path(self.temp_dir.name) / "archives.sqlite3")
		self.application = ArchiveApplication(
			repository=self.repository,
			validator=ArchivePayloadValidator(),
			access_token=None,
			auth_mode="google",
			google_verifier=FakeGoogleVerifier(),
		)
		login = self.application.handle(
			"POST",
			"/api/v1/auth/google",
			{"Content-Type": "application/json"},
			json.dumps({"credential": "admin-cred"}).encode("utf-8"),
		)
		self.cookie = login.headers["Set-Cookie"].split(";", 1)[0]

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def create_token(self, name: str = "build-machine"):
		return self.application.handle(
			"POST",
			"/api/v1/tokens",
			{"Cookie": self.cookie, "Content-Type": "application/json"},
			json.dumps({"name": name}).encode("utf-8"),
		)

	def test_create_list_and_use_token(self) -> None:
		created = self.create_token()
		self.assertEqual(201, created.status)
		plaintext = created.body["token"]
		self.assertTrue(plaintext.startswith("aov_pk_"))

		listed = self.application.handle("GET", "/api/v1/tokens", {"Cookie": self.cookie})
		self.assertEqual(200, listed.status)
		self.assertEqual(1, len(listed.body["items"]))
		item = listed.body["items"][0]
		self.assertEqual("build-machine", item["name"])
		self.assertNotIn("token", item)
		self.assertNotIn("token_hash", item)

		with_token = self.application.handle(
			"GET",
			"/api/v1/package-archives",
			{"Authorization": f"Bearer {plaintext}"},
		)
		self.assertEqual(200, with_token.status)

		reloaded = self.repository.list_api_tokens(item["user_id"])
		self.assertIsNotNone(reloaded[0]["last_used_at"])

	def test_revoked_token_is_rejected(self) -> None:
		created = self.create_token()
		plaintext = created.body["token"]
		token_id = created.body["item"]["id"]

		revoked = self.application.handle(
			"POST",
			f"/api/v1/tokens/{token_id}/revoke",
			{"Cookie": self.cookie},
		)
		self.assertEqual(200, revoked.status)

		with_token = self.application.handle(
			"GET",
			"/api/v1/package-archives",
			{"Authorization": f"Bearer {plaintext}"},
		)
		self.assertEqual(401, with_token.status)

	def test_unknown_or_foreign_token_is_rejected(self) -> None:
		with_token = self.application.handle(
			"GET",
			"/api/v1/package-archives",
			{"Authorization": "Bearer aov_pk_deadbeef"},
		)
		self.assertEqual(401, with_token.status)

	def test_tokens_endpoint_requires_signed_in_account(self) -> None:
		legacy = ArchiveApplication(
			repository=self.repository,
			validator=ArchivePayloadValidator(),
			access_token="legacy-test-token",
		)
		response = legacy.handle(
			"GET",
			"/api/v1/tokens",
			{"Authorization": "Bearer legacy-test-token"},
		)
		self.assertEqual(400, response.status)
		self.assertEqual("tokens_unsupported", response.body["error"]["code"])


if __name__ == "__main__":
	unittest.main()
