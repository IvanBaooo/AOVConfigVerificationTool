from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError

from test_validation_rule_sets import sample_rule_set
from validation_rule_client import (
	ValidationRuleCache,
	ValidationRuleClient,
)
from validation_rule_sets import effective_rule_set


class FakeResponse:
	def __init__(self, body: dict[str, object]) -> None:
		self.body = body

	def __enter__(self):
		return self

	def __exit__(self, *_args):
		return False

	def read(self) -> bytes:
		return json.dumps(self.body, ensure_ascii=False).encode("utf-8")


class ValidationRuleClientTests(unittest.TestCase):
	def test_remote_rule_is_verified_cached_and_reloaded(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			cache = ValidationRuleCache(Path(temp_dir) / "rules.json")
			effective = effective_rule_set(sample_rule_set(), "TW")
			client = ValidationRuleClient(
				cache=cache,
				opener=lambda _request, **_kwargs: FakeResponse({"rule_set": effective}),
			)

			result = client.resolve(base_url="http://127.0.0.1:8780", region_code="TW")

			self.assertEqual("remote", result.source)
			self.assertEqual("2026.07.27.1", cache.load("TW")["version"])

	def test_offline_uses_cached_rule(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			cache = ValidationRuleCache(Path(temp_dir) / "rules.json")
			cache.save(effective_rule_set(sample_rule_set(), "TH"))
			client = ValidationRuleClient(
				cache=cache,
				opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline")),
			)

			result = client.resolve(base_url="http://127.0.0.1:8780", region_code="TH")

			self.assertEqual("local_cache", result.source)
			self.assertEqual("2026.07.27.1", result.rule_set["version"])
			self.assertIn("offline", result.message)

	def test_offline_without_cache_uses_built_in_rules(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			client = ValidationRuleClient(
				cache=ValidationRuleCache(Path(temp_dir) / "rules.json"),
				opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline")),
			)

			result = client.resolve(base_url="http://127.0.0.1:8780", region_code="VN")

			self.assertEqual("built_in", result.source)
			self.assertEqual("built-in", result.rule_set["rule_set_id"])
			self.assertIn("offline", result.message)

	def test_invalid_remote_hash_falls_back_to_cache(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			cache = ValidationRuleCache(Path(temp_dir) / "rules.json")
			cached = effective_rule_set(sample_rule_set(), "ID")
			cache.save(cached)
			tampered = dict(cached)
			tampered["notes"] = "changed without hash"
			client = ValidationRuleClient(
				cache=cache,
				opener=lambda _request, **_kwargs: FakeResponse({"rule_set": tampered}),
			)

			result = client.resolve(base_url="http://127.0.0.1:8780", region_code="ID")

			self.assertEqual("local_cache", result.source)
			self.assertIn("hash verification", result.message)


if __name__ == "__main__":
	unittest.main()
