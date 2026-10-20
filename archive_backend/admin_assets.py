from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AdminAssetResponse:
	status: int
	body: bytes
	content_type: str
	headers: dict[str, str] = field(default_factory=dict)


ASSET_DIRECTORY = Path(__file__).resolve().parent.parent / "archive_web"
ASSET_FILES = {
	"": ("index.html", "text/html; charset=utf-8"),
	"app.js": ("app.js", "text/javascript; charset=utf-8"),
	"rules.js": ("rules.js", "text/javascript; charset=utf-8"),
	"users.js": ("users.js", "text/javascript; charset=utf-8"),
	"rules.css": ("rules.css", "text/css; charset=utf-8"),
	"styles.css": ("styles.css", "text/css; charset=utf-8"),
}
APP_ROUTE_PREFIX = "/app"
LEGACY_ROUTE_PREFIX = "/admin"


def is_admin_route(path: str) -> bool:
	if path in {"/", APP_ROUTE_PREFIX, LEGACY_ROUTE_PREFIX}:
		return True
	for prefix in (APP_ROUTE_PREFIX, LEGACY_ROUTE_PREFIX):
		if path.startswith(prefix + "/") and path[len(prefix) + 1 :] in ASSET_FILES:
			return True
	return False


def load_admin_asset(path: str) -> AdminAssetResponse | None:
	if path == "/":
		return AdminAssetResponse(302, b"", "text/plain; charset=utf-8", {"Location": "/app/"})
	if path == APP_ROUTE_PREFIX:
		return AdminAssetResponse(302, b"", "text/plain; charset=utf-8", {"Location": "/app/"})
	if path == LEGACY_ROUTE_PREFIX or path.startswith(LEGACY_ROUTE_PREFIX + "/"):
		target = "/app/" + path[len(LEGACY_ROUTE_PREFIX) + 1 :]
		return AdminAssetResponse(302, b"", "text/plain; charset=utf-8", {"Location": target})
	if path.startswith(APP_ROUTE_PREFIX + "/"):
		filename, content_type = ASSET_FILES.get(path[len(APP_ROUTE_PREFIX) + 1 :], (None, None))
		if filename is None:
			return None
		try:
			body = (ASSET_DIRECTORY / filename).read_bytes()
		except OSError:
			return AdminAssetResponse(
				503,
				b"Admin interface is unavailable.",
				"text/plain; charset=utf-8",
			)
		return AdminAssetResponse(200, body, content_type)
	return None


__all__ = ["AdminAssetResponse", "is_admin_route", "load_admin_asset"]
