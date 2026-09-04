from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from archive_backend.repository import ArchiveRepository
from backend_archive_contract_v1 import build_archive_record
from test_backend_archive_contract_v1 import final_sample_report


class ArchiveRepositoryNumericSemanticsTests(unittest.TestCase):
	def test_integral_float_replays_integer_payload(self) -> None:
		payload = build_archive_record(final_sample_report())
		numeric_variant = copy.deepcopy(payload)
		numeric_variant["package"]["file_count"] = 1.0

		with tempfile.TemporaryDirectory() as temp_dir:
			repository = ArchiveRepository(Path(temp_dir) / "archives.sqlite3")
			created = repository.create_archive(payload)
			replayed = repository.create_archive(numeric_variant)

		self.assertEqual(created.result, "created")
		self.assertEqual(replayed.result, "replayed")


if __name__ == "__main__":
	unittest.main()
