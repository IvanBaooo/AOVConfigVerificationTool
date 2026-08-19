from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from local_settings import LocalSettingsError, load_local_settings


class LocalSettingsReadFailureTests(unittest.TestCase):
	def test_exists_permission_error_is_wrapped_as_settings_error(self) -> None:
		with patch.object(Path, "exists", side_effect=PermissionError("denied")):
			with self.assertRaises(LocalSettingsError):
				load_local_settings(Path("settings.json"))


if __name__ == "__main__":
	unittest.main()
