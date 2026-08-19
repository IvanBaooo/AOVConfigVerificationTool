from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from publication_queue import PublicationQueue, PublicationQueueError


class PublicationQueueTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.queue = PublicationQueue(Path(self.temp_dir.name) / "queue.sqlite3")
		self.payload = {
			"idempotency_key": "archive-key",
			"package_id": "sgame_TW_Beta54_20260713153524",
			"schema_version": "1.0",
		}

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def test_enqueue_persists_only_archive_payload_and_backend_url(self) -> None:
		item = self.queue.enqueue(
			self.payload,
			"http://127.0.0.1:8780/",
			"backend unavailable",
		)

		self.assertEqual(item.package_id, self.payload["package_id"])
		self.assertEqual(item.backend_url, "http://127.0.0.1:8780")
		self.assertEqual(item.payload, self.payload)
		self.assertEqual(item.attempts, 1)
		self.assertNotIn("token", item.payload)
		self.assertNotIn("password", item.payload)

	def test_same_idempotency_key_updates_one_pending_item(self) -> None:
		self.queue.enqueue(self.payload, "http://127.0.0.1:8780", "first")
		item = self.queue.enqueue(self.payload, "http://127.0.0.1:8780", "second")

		self.assertEqual(self.queue.count(), 1)
		self.assertEqual(item.attempts, 2)
		self.assertEqual(item.last_error, "second")

	def test_failed_retry_increments_attempt_and_success_removes_item(self) -> None:
		self.queue.enqueue(self.payload, "http://127.0.0.1:8780", "first")

		self.queue.mark_failure("archive-key", "second")
		item = self.queue.get("archive-key")
		self.assertIsNotNone(item)
		self.assertEqual(item.attempts, 2)
		self.assertEqual(item.last_error, "second")

		self.queue.complete("archive-key")
		self.assertEqual(self.queue.list_pending(), [])

	def test_invalid_payload_or_backend_url_is_rejected(self) -> None:
		with self.assertRaises(PublicationQueueError):
			self.queue.enqueue({}, "http://127.0.0.1:8780", "error")
		with self.assertRaises(PublicationQueueError):
			self.queue.enqueue(self.payload, "not-a-url", "error")


if __name__ == "__main__":
	unittest.main()
