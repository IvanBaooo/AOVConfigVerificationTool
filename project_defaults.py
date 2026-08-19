from __future__ import annotations

import os


TDR_SVN_ROOT_URL = os.environ.get("AOV_TDR_SVN_ROOT_URL", "").strip().rstrip("/")
SERVERBYTES_SVN_URL = f"{TDR_SVN_ROOT_URL}/ServerBytes" if TDR_SVN_ROOT_URL else ""

LOCAL_TDR_ROOT = os.environ.get("AOV_LOCAL_TDR_ROOT", "").strip()
LOCAL_SERVERBYTES_ROOT = os.environ.get("AOV_LOCAL_SERVERBYTES_ROOT", "").strip()
LOCAL_SVN_EXE = os.environ.get("AOV_SVN_EXE", "").strip()

DEFAULT_REGION_CODE = "TW"
DEFAULT_SCOPE_ROOTS = "/Taiwan"


def existing_path_or_empty(path: str) -> str:
	return path if os.path.exists(path) else ""
