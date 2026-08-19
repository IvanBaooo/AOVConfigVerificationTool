from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from backend_archive_contract_v1 import (
	ArchiveContractError,
	archive_create_headers,
)


class ArchivePayloadError(ValueError):
	def __init__(self, message: str, details: list[dict[str, str]] | None = None) -> None:
		super().__init__(message)
		self.details = details or []


def _error_path(path: Any) -> str:
	result = "$"
	for part in path:
		if isinstance(part, int):
			result += f"[{part}]"
		else:
			result += f".{part}"
	return result


def _validate_file_counts(payload: Mapping[str, Any]) -> None:
	counts = {"file_count": 0, "failed_count": 0, "skipped_count": 0}
	for index, file_info in enumerate(payload["files"]):
		status = file_info["status"]
		if status == "packaged":
			counts["file_count"] += 1
		elif status in {"missing", "add_failed"}:
			counts["failed_count"] += 1
		elif status == "deleted_skipped":
			counts["skipped_count"] += 1
		else:
			raise ArchivePayloadError(
				f"Unsupported file status: {status}",
				[{"path": f"$.files[{index}].status", "message": "Unsupported file status."}],
			)

	package = payload["package"]
	for field, derived in counts.items():
		reported = package[field]
		if reported != derived:
			raise ArchivePayloadError(
				f"Package count mismatch: package.{field}={reported}, files-derived={derived}",
				[{"path": f"$.package.{field}", "message": f"Expected {derived}."}],
			)


class ArchivePayloadValidator:
	def __init__(self, schema_directory: str | Path | None = None) -> None:
		if schema_directory is None:
			schema_directory = Path(__file__).resolve().parent.parent / "schemas"
		schema_directory = Path(schema_directory)
		final_schema = json.loads(
			(schema_directory / "aov-package-archive-v1-final.schema.json").read_text(
				encoding="utf-8"
			)
		)
		strict_schema = json.loads(
			(schema_directory / "aov-package-archive-v1-strict.schema.json").read_text(
				encoding="utf-8"
			)
		)

		Draft202012Validator.check_schema(strict_schema)
		Draft202012Validator.check_schema(final_schema)
		registry = Registry().with_resource(
			strict_schema["$id"],
			Resource.from_contents(strict_schema),
		)
		self._validator = Draft202012Validator(
			final_schema,
			registry=registry,
			format_checker=Draft202012Validator.FORMAT_CHECKER,
		)

	def validate(self, payload: object) -> Mapping[str, Any]:
		if not isinstance(payload, Mapping):
			raise ArchivePayloadError(
				"The request body must be a JSON object.",
				[{"path": "$", "message": "Expected an object."}],
			)

		errors = sorted(
			self._validator.iter_errors(payload),
			key=lambda error: (list(error.absolute_path), error.message),
		)
		if errors:
			details = [
				{"path": _error_path(error.absolute_path), "message": error.message}
				for error in errors[:20]
			]
			raise ArchivePayloadError("The archive payload does not match contract V1.", details)

		_validate_file_counts(payload)

		try:
			archive_create_headers(payload)
		except ArchiveContractError as error:
			raise ArchivePayloadError(str(error)) from error
		return payload


__all__ = ["ArchivePayloadError", "ArchivePayloadValidator"]

