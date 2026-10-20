from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from archive_backend.api import ArchiveApplication
from archive_backend.repository import ArchiveRepository
from archive_backend.schema_validation import ArchivePayloadValidator
from backend_archive_contract_v1 import build_archive_record
from test_backend_archive_contract_v1 import final_sample_report
from test_validation_rule_sets import sample_rule_set


class FakeGoogleVerifier:
	PROFILES = {
		"admin-cred": {"email": "admin@example.com", "display_name": "Admin"},
		"member-cred": {"email": "member@example.com", "display_name": "Member"},
	}

	def verify(self, credential: str) -> dict[str, str]:
		profile = self.PROFILES.get(credential)
		if profile is None:
			raise ValueError("invalid credential")
		return profile


class RoleEnforcementTests(unittest.TestCase):
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
		self.admin_cookie = self.login("admin-cred")
		self.application.handle(
			"POST",
			"/api/v1/admin/users",
			{"Cookie": self.admin_cookie, "Content-Type": "application/json"},
			json.dumps({"email": "member@example.com"}).encode("utf-8"),
		)
		self.member_cookie = self.login("member-cred")

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def login(self, credential: str) -> str:
		response = self.application.handle(
			"POST",
			"/api/v1/auth/google",
			{"Content-Type": "application/json"},
			json.dumps({"credential": credential}).encode("utf-8"),
		)
		return response.headers["Set-Cookie"].split(";", 1)[0]

	def create_archive(self, cookie: str) -> str:
		payload = build_archive_record(final_sample_report())
		response = self.application.handle(
			"POST",
			"/api/v1/package-archives",
			{
				"Cookie": cookie,
				"Content-Type": "application/json; charset=utf-8",
				"Idempotency-Key": payload["idempotency_key"],
				"X-AOV-Contract-Version": "1.0",
			},
			json.dumps(payload, ensure_ascii=False).encode("utf-8"),
		)
		assert response.status == 201, response.body
		return payload["package_id"]

	def test_member_cannot_reach_admin_routes(self) -> None:
		users = self.application.handle("GET", "/api/v1/admin/users", {"Cookie": self.member_cookie})
		self.assertEqual(403, users.status)
		self.assertEqual("forbidden", users.body["error"]["code"])

		audit = self.application.handle("GET", "/api/v1/admin/archive-audit", {"Cookie": self.member_cookie})
		self.assertEqual(403, audit.status)

		publish = self.application.handle(
			"POST",
			"/api/v1/validation-rule-sets",
			{"Cookie": self.member_cookie, "Content-Type": "application/json"},
			json.dumps(sample_rule_set(), ensure_ascii=False).encode("utf-8"),
		)
		self.assertEqual(403, publish.status)

		package_id = self.create_archive(self.member_cookie)
		manage = self.application.handle(
			"POST",
			f"/api/v1/admin/package-archives/{package_id}/soft-delete",
			{"Cookie": self.member_cookie, "Content-Type": "application/json"},
			json.dumps({"reason": "no permission"}).encode("utf-8"),
		)
		self.assertEqual(403, manage.status)

	def test_member_can_read_and_upload(self) -> None:
		self.create_archive(self.member_cookie)
		listed = self.application.handle("GET", "/api/v1/package-archives", {"Cookie": self.member_cookie})
		self.assertEqual(200, listed.status)
		self.assertEqual(1, listed.body["total"])

		dashboard = self.application.handle("GET", "/api/v1/dashboard-summary", {"Cookie": self.member_cookie})
		self.assertEqual(200, dashboard.status)

	def test_admin_actions_record_real_actor(self) -> None:
		package_id = self.create_archive(self.admin_cookie)
		deleted = self.application.handle(
			"POST",
			f"/api/v1/admin/package-archives/{package_id}/soft-delete",
			{"Cookie": self.admin_cookie, "Content-Type": "application/json"},
			json.dumps({"reason": "cleanup"}).encode("utf-8"),
		)
		self.assertEqual(200, deleted.status)
		self.assertEqual("admin@example.com", deleted.body["event"]["actor"])

	def test_admin_cannot_demote_or_disable_self(self) -> None:
		admin_user = self.repository.get_user_by_email("admin@example.com")
		demote = self.application.handle(
			"PATCH",
			f"/api/v1/admin/users/{admin_user['id']}",
			{"Cookie": self.admin_cookie, "Content-Type": "application/json"},
			json.dumps({"role": "member"}).encode("utf-8"),
		)
		self.assertEqual(400, demote.status)
		self.assertEqual("cannot_modify_self", demote.body["error"]["code"])

		remove = self.application.handle(
			"DELETE",
			f"/api/v1/admin/users/{admin_user['id']}",
			{"Cookie": self.admin_cookie},
		)
		self.assertEqual(400, remove.status)

	def test_disabling_member_revokes_sessions_and_tokens(self) -> None:
		created = self.application.handle(
			"POST",
			"/api/v1/tokens",
			{"Cookie": self.member_cookie, "Content-Type": "application/json"},
			json.dumps({"name": "member-ci"}).encode("utf-8"),
		)
		plaintext = created.body["token"]

		member_user = self.repository.get_user_by_email("member@example.com")
		disabled = self.application.handle(
			"DELETE",
			f"/api/v1/admin/users/{member_user['id']}",
			{"Cookie": self.admin_cookie},
		)
		self.assertEqual(200, disabled.status)

		session_check = self.application.handle("GET", "/api/v1/auth/me", {"Cookie": self.member_cookie})
		self.assertEqual(401, session_check.status)
		token_check = self.application.handle(
			"GET",
			"/api/v1/package-archives",
			{"Authorization": f"Bearer {plaintext}"},
		)
		self.assertEqual(401, token_check.status)


if __name__ == "__main__":
	unittest.main()
