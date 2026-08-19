from __future__ import annotations

import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from AOVAutoPackerCurrent import AOVAutoPackerCurrentApp
from manual_publication import ArchiveSyncResult, BackendSettings


class PublicationQueueGuiTests(unittest.TestCase):
	def create_app(self, root_path: Path):
		environment = {
			"AOV_AUTOPACKER_SETTINGS": str(root_path / "settings.json"),
			"AOV_PUBLICATION_QUEUE": str(root_path / "publication-queue.sqlite3"),
		}
		patcher = patch.dict(os.environ, environment)
		patcher.start()
		self.addCleanup(patcher.stop)
		root = tk.Tk()
		root.withdraw()
		self.addCleanup(lambda: root.destroy() if root.winfo_exists() else None)
		return AOVAutoPackerCurrentApp(root)

	@staticmethod
	def payload() -> dict[str, object]:
		return {
			"idempotency_key": "queued-archive-key",
			"package_id": "sgame_TW_Beta54_20260713153524",
			"schema_version": "1.0",
		}

	def test_pending_count_is_visible_in_manual_archive_panel(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			app = self.create_app(Path(temp_dir))
			app._publication_queue.enqueue(
				self.payload(),
				"http://127.0.0.1:8780",
				"backend unavailable",
			)

			app._refresh_sync_queue_button()

			self.assertEqual(app.btn_retry_sync.cget("text"), "待同步 1")
			self.assertEqual(str(app.btn_retry_sync.cget("state")), "normal")

	def test_retry_worker_only_syncs_backend_and_removes_successful_item(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			app = self.create_app(Path(temp_dir))
			item = app._publication_queue.enqueue(
				self.payload(),
				"http://127.0.0.1:8780",
				"backend unavailable",
			)

			with patch("manual_publication_gui.ArchiveBackendClient") as client_class:
				client_class.return_value.sync_payload.return_value = ArchiveSyncResult(
					"replayed",
					item.package_id,
				)
				app._retry_sync_worker(item, BackendSettings(item.backend_url))

			event, args = app._publication_events.get_nowait()
			self.assertEqual(event, "retry_complete")
			self.assertEqual(args[0], item)
			self.assertEqual(app._publication_queue.count(), 0)
			client_class.return_value.sync_payload.assert_called_once()


if __name__ == "__main__":
	unittest.main()
