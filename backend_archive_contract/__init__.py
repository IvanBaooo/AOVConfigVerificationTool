from __future__ import annotations

import copy
import importlib.util
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_implementation() -> ModuleType:
	implementation_path = Path(__file__).resolve().parent.parent / "backend_archive_contract.py"
	spec = importlib.util.spec_from_file_location("_aov_backend_archive_contract_impl", implementation_path)
	if spec is None or spec.loader is None:
		raise ImportError(f"Cannot load archive contract implementation: {implementation_path}")
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


_implementation = _load_implementation()

ARCHIVE_CONTRACT_VERSION = _implementation.ARCHIVE_CONTRACT_VERSION
ARCHIVE_RECORD_TYPE = _implementation.ARCHIVE_RECORD_TYPE
ArchiveContractError = _implementation.ArchiveContractError


def _validate_reported_count(package: Mapping[str, Any], key: str) -> None:
	value = package.get(key)
	if type(value) is not int or value < 0:
		raise ArchiveContractError(f"Expected non-negative integer: {key}")


def _normalize_package_counts(report: Mapping[str, Any]) -> dict[str, object]:
	normalized = copy.deepcopy(dict(report))
	package = normalized.get("package")
	files = normalized.get("files")
	if not isinstance(package, dict) or not isinstance(files, list):
		return normalized

	for key in ("file_count", "failed_count", "skipped_count"):
		_validate_reported_count(package, key)

	packaged_count = 0
	failed_count = 0
	for item in files:
		if not isinstance(item, Mapping):
			continue
		status = item.get("status")
		if status == "packaged":
			packaged_count += 1
		elif status in {"missing", "add_failed"}:
			failed_count += 1
	skipped_count = max(0, len(files) - packaged_count - failed_count)
	package["file_count"] = packaged_count
	package["failed_count"] = failed_count
	package["skipped_count"] = skipped_count
	return normalized


def build_archive_record(report: Mapping[str, Any]) -> dict[str, object]:
	if not isinstance(report, Mapping):
		raise ArchiveContractError("Report must be a mapping")
	return _implementation.build_archive_record(_normalize_package_counts(report))


def archive_create_headers(payload: Mapping[str, Any]) -> dict[str, str]:
	return _implementation.archive_create_headers(payload)


__all__ = [
	"ARCHIVE_CONTRACT_VERSION",
	"ARCHIVE_RECORD_TYPE",
	"ArchiveContractError",
	"archive_create_headers",
	"build_archive_record",
]
