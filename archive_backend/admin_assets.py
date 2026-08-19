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
ASSET_ROUTES = {
	"/admin/": ("index.html", "text/html; charset=utf-8"),
	"/admin/app.js": ("app.js", "text/javascript; charset=utf-8"),
	"/admin/rules.js": ("rules.js", "text/javascript; charset=utf-8"),
	"/admin/rules.css": ("rules.css", "text/css; charset=utf-8"),
	"/admin/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


def is_admin_route(path: str) -> bool:
	return path in {"/", "/admin", *ASSET_ROUTES}


def load_admin_asset(path: str) -> AdminAssetResponse | None:
	if path in {"/", "/admin"}:
		return AdminAssetResponse(302, b"", "text/plain; charset=utf-8", {"Location": "/admin/"})
	route = ASSET_ROUTES.get(path)
	if route is None:
		return None
	filename, content_type = route
	try:
		body = (ASSET_DIRECTORY / filename).read_bytes()
	except OSError:
		return AdminAssetResponse(
			503,
			b"Admin interface is unavailable.",
			"text/plain; charset=utf-8",
		)
	return AdminAssetResponse(200, body, content_type)


__all__ = ["AdminAssetResponse", "is_admin_route", "load_admin_asset"]
