from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import math
import os
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .admin_assets import AdminAssetResponse, is_admin_route, load_admin_asset
from .api import ApiResponse, ArchiveApplication
from .repository import ArchiveRepository
from .schema_validation import ArchivePayloadValidator


DEFAULT_MAX_BODY_BYTES = 10 * 1024 * 1024
DEFAULT_READ_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_WORKERS = 32
LOG_CONTROL_CHAR_TABLE = {
	codepoint: f"\\x{codepoint:02x}"
	for codepoint in [*range(32), *range(127, 160)]
}
LOGGER = logging.getLogger("aov.archive_backend")


def _is_loopback_address(value: str) -> bool:
	try:
		return ipaddress.ip_address(value.split("%", 1)[0]).is_loopback
	except ValueError:
		return value.lower() == "localhost"


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
	daemon_threads = True

	def __init__(self, server_address, request_handler_class, *, max_workers: int) -> None:
		self._worker_slots = threading.BoundedSemaphore(max_workers)
		super().__init__(server_address, request_handler_class)

	def process_request(self, request, client_address) -> None:
		self._worker_slots.acquire()
		try:
			super().process_request(request, client_address)
		except BaseException:
			self._worker_slots.release()
			raise

	def process_request_thread(self, request, client_address) -> None:
		try:
			super().process_request_thread(request, client_address)
		finally:
			self._worker_slots.release()


def default_database_path() -> Path:
	configured = os.environ.get("AOV_BACKEND_DB")
	if configured:
		return Path(configured).expanduser()
	base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
	return base / "AOVAutoPackerBackend" / "archives.sqlite3"


def _handler_class(
	application: ArchiveApplication,
	max_body_bytes: int,
	read_timeout_seconds: float,
):
	class ArchiveRequestHandler(BaseHTTPRequestHandler):
		protocol_version = "HTTP/1.1"

		def setup(self) -> None:
			super().setup()
			self._request_generation = 0
			self._request_deadline = 0.0
			self._request_deadline_expired = False
			self._reading_headers = False

		def handle_one_request(self) -> None:
			self._request_generation += 1
			generation = self._request_generation
			self._request_deadline = time.monotonic() + read_timeout_seconds
			self._request_deadline_expired = False
			self._reading_headers = True
			self.connection.settimeout(read_timeout_seconds)
			deadline_timer = threading.Timer(
				read_timeout_seconds,
				self._expire_request,
				args=(generation,),
			)
			deadline_timer.daemon = True
			deadline_timer.start()
			try:
				self.raw_requestline = self.rfile.readline(65537)
				if len(self.raw_requestline) > 65536:
					self.requestline = ""
					self.request_version = ""
					self.command = ""
					self.send_error(HTTPStatus.REQUEST_URI_TOO_LONG)
					return
				if not self.raw_requestline:
					self.close_connection = True
					return
				if not self.parse_request():
					return
				self._reading_headers = False
				if self._request_timed_out():
					self.close_connection = True
					return

				method_name = "do_" + self.command
				if not hasattr(self, method_name):
					self.send_error(
						HTTPStatus.NOT_IMPLEMENTED,
						"Unsupported method (%r)" % self.command,
					)
					return
				getattr(self, method_name)()
				self.wfile.flush()
			except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
				self.close_connection = True
			except TimeoutError as error:
				self.log_error("Request timed out: %r", error)
				self.close_connection = True
			finally:
				self._reading_headers = False
				deadline_timer.cancel()

		def _expire_request(self, generation: int) -> None:
			if generation != self._request_generation:
				return
			self._request_deadline_expired = True
			self.close_connection = True
			if self._reading_headers:
				try:
					self.connection.shutdown(socket.SHUT_RD)
				except OSError:
					pass

		def _request_timed_out(self) -> bool:
			return self._request_deadline_expired or time.monotonic() >= self._request_deadline

		def do_GET(self) -> None:
			self._dispatch()

		def do_POST(self) -> None:
			self._dispatch(read_body=True)

		def do_PUT(self) -> None:
			self._dispatch(read_body=True)

		def do_PATCH(self) -> None:
			self._dispatch(read_body=True)

		def do_DELETE(self) -> None:
			self._dispatch()

		def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
			self.close_connection = True
			super().send_error(code, message, explain)

		def _dispatch(self, *, read_body: bool = False) -> None:
			request_headers = {key: value for key, value in self.headers.items()}
			path = ""
			body = b""
			response: ApiResponse | None = None
			admin_request = False
			public_api_request = False
			try:

				try:
					path = urlsplit(self.path).path
					admin_request = self.command == "GET" and is_admin_route(path)
					public_api_request = self.command == "GET" and (
						path == "/api/v1/validation-rules/latest"
						or path == "/api/v1/validation-rule-sets"
						or path.startswith("/api/v1/validation-rule-sets/")
					)
				except ValueError:
					self.close_connection = True
					response = self._error_response(
						400,
						"invalid_target",
						"The request target is invalid.",
					)

				if (
					response is None
					and self.command == "POST"
					and path == "/api/v1/validation-rule-sets"
					and not _is_loopback_address(str(self.client_address[0]))
				):
					self.close_connection = True
					response = self._error_response(
						403,
						"rule_publish_local_only",
						"Validation rule publishing is restricted to the local machine.",
					)
				if (
					response is None
					and path.startswith("/api/v1/admin/")
					and not _is_loopback_address(str(self.client_address[0]))
				):
					self.close_connection = True
					response = self._error_response(
						403,
						"admin_local_only",
						"Archive management is restricted to the local machine.",
					)
				if response is None and path != "/health" and not admin_request and not public_api_request:
					authorization_checker = getattr(application, "is_authorized", None)
					if callable(authorization_checker) and not authorization_checker(request_headers):
						self.close_connection = True
						response = application.handle(
							self.command,
							self.path,
							request_headers,
							body,
						)

				if response is None:
					body, response = self._prepare_request_body(allow_body=read_body)

				if response is None and admin_request:
					asset_response = load_admin_asset(path)
					if asset_response is not None:
						self._write_admin_response(asset_response)
						return

				if response is None:
					response = application.handle(
						self.command,
						self.path,
						request_headers,
						body,
					)

				if self._request_timed_out():
					self.close_connection = True
					response = self._timeout_response()
			except (socket.timeout, TimeoutError):
				self.close_connection = True
				response = self._timeout_response()
			except Exception:
				if self._request_timed_out():
					self.close_connection = True
					response = self._timeout_response()
				else:
					LOGGER.exception("Unhandled archive backend request error")
					self.close_connection = True
					if path == "/health":
						response = self._error_response(
							503,
							"service_unavailable",
							"The archive backend is unavailable.",
						)
					else:
						response = self._error_response(
							500,
							"internal_error",
							"The archive backend could not process the request.",
						)

			assert response is not None
			self._write_response(response)

		def _prepare_request_body(self, *, allow_body: bool) -> tuple[bytes, ApiResponse | None]:
			if self.headers.get_all("Transfer-Encoding"):
				self.close_connection = True
				return b"", self._error_response(
					400,
					"unsupported_transfer_encoding",
					"Transfer-Encoding is not supported.",
				)

			content_lengths = self.headers.get_all("Content-Length", [])
			if not content_lengths:
				if allow_body:
					self.close_connection = True
					return b"", self._error_response(
						411,
						"length_required",
						"Content-Length is required.",
					)
				return b"", None
			if len(content_lengths) != 1:
				self.close_connection = True
				return b"", self._error_response(
					400,
					"invalid_content_length",
					"Exactly one Content-Length header is required.",
				)

			raw_length = content_lengths[0].strip()
			if not raw_length or not raw_length.isascii() or not raw_length.isdigit():
				self.close_connection = True
				return b"", self._error_response(
					400,
					"invalid_content_length",
					"Content-Length must be a non-negative decimal integer.",
				)

			normalized_length = raw_length.lstrip("0") or "0"
			if not allow_body:
				if normalized_length != "0":
					self.close_connection = True
					return b"", self._error_response(
						400,
						"request_body_not_allowed",
						"This method does not accept a request body.",
					)
				return b"", None

			maximum_length = str(max_body_bytes)
			if (
				len(normalized_length) > len(maximum_length)
				or len(normalized_length) == len(maximum_length)
				and normalized_length > maximum_length
			):
				self.close_connection = True
				return b"", self._error_response(
					413,
					"payload_too_large",
					f"Request body exceeds {max_body_bytes} bytes.",
				)

			length = int(normalized_length)
			chunks: list[bytes] = []
			remaining = length
			while remaining:
				if self._request_timed_out():
					raise TimeoutError
				self.connection.settimeout(max(0.001, self._request_deadline - time.monotonic()))
				chunk = self.rfile.read1(min(remaining, 64 * 1024))
				if not chunk:
					break
				chunks.append(chunk)
				remaining -= len(chunk)
			body = b"".join(chunks)
			if self._request_timed_out():
				raise TimeoutError
			if len(body) != length:
				self.close_connection = True
				return b"", self._error_response(
					400,
					"incomplete_body",
					"The request body ended before Content-Length bytes were received.",
				)
			return body, None

		@staticmethod
		def _error_response(status: int, code: str, message: str) -> ApiResponse:
			return ApiResponse(
				status,
				{"error": {"code": code, "message": message}},
			)

		def _timeout_response(self) -> ApiResponse:
			return self._error_response(
				408,
				"request_timeout",
				"The request exceeded the configured time limit.",
			)

		def _write_admin_response(self, response: AdminAssetResponse) -> None:
			try:
				self.send_response(response.status)
				self.send_header("Content-Type", response.content_type)
				self.send_header("Content-Length", str(len(response.body)))
				self.send_header("Cache-Control", "no-store")
				self.send_header("X-Content-Type-Options", "nosniff")
				self.send_header("Referrer-Policy", "no-referrer")
				self.send_header(
					"Content-Security-Policy",
					"default-src 'self'; script-src 'self'; style-src 'self'; "
					"connect-src 'self'; img-src 'self' data:; object-src 'none'; "
					"base-uri 'none'; frame-ancestors 'none'",
				)
				for key, value in response.headers.items():
					self.send_header(key, value)
				self.end_headers()
				if response.body:
					self.wfile.write(response.body)
					self.wfile.flush()
			except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
				self.close_connection = True
		def _write_response(self, response: ApiResponse) -> None:
			encoded = json.dumps(
				response.body,
				ensure_ascii=False,
				separators=(",", ":"),
			).encode("utf-8")
			try:
				self.send_response(response.status)
				self.send_header("Content-Type", "application/json; charset=utf-8")
				self.send_header("Content-Length", str(len(encoded)))
				self.send_header("Cache-Control", "no-store")
				self.send_header("X-Content-Type-Options", "nosniff")
				if self.close_connection:
					self.send_header("Connection", "close")
				for key, value in response.headers.items():
					self.send_header(key, value)
				self.end_headers()
				self.wfile.write(encoded)
				self.wfile.flush()
			except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
				self.close_connection = True

		def log_message(self, format: str, *args: object) -> None:
			message = (format % args).translate(getattr(self, "_control_char_table", LOG_CONTROL_CHAR_TABLE))
			LOGGER.info("%s - %s", self.address_string(), message)

	return ArchiveRequestHandler


def create_http_server(
	application: ArchiveApplication,
	*,
	host: str = "127.0.0.1",
	port: int = 8780,
	max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
	read_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS,
	max_workers: int = DEFAULT_MAX_WORKERS,
) -> ThreadingHTTPServer:
	if max_body_bytes <= 0:
		raise ValueError("max_body_bytes must be positive.")
	if not math.isfinite(read_timeout_seconds) or read_timeout_seconds <= 0:
		raise ValueError("read_timeout_seconds must be finite and positive.")
	if max_workers <= 0:
		raise ValueError("max_workers must be positive.")
	return BoundedThreadingHTTPServer(
		(host, port),
		_handler_class(application, max_body_bytes, read_timeout_seconds),
		max_workers=max_workers,
	)


def _parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="AOV package archive backend")
	parser.add_argument("--host", default="127.0.0.1")
	parser.add_argument("--port", type=int, default=8780)
	parser.add_argument("--db", type=Path, default=default_database_path())
	parser.add_argument("--max-body-mb", type=int, default=10)
	parser.add_argument("--read-timeout-seconds", type=float, default=DEFAULT_READ_TIMEOUT_SECONDS)
	parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
	parser.add_argument(
		"--no-auth",
		action="store_true",
		help="Disable bearer authentication for loopback-only local development.",
	)
	return parser


def main() -> int:
	args = _parser().parse_args()
	access_token: str | None = os.environ.get("AOV_BACKEND_TOKEN", "")
	if args.no_auth:
		if args.host not in {"127.0.0.1", "localhost", "::1"}:
			raise SystemExit("--no-auth is only allowed with a loopback host.")
		access_token = None
	elif not access_token:
		raise SystemExit("AOV_BACKEND_TOKEN is required unless --no-auth is used.")
	logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
	application = ArchiveApplication(
		repository=ArchiveRepository(args.db),
		validator=ArchivePayloadValidator(),
		access_token=access_token,
	)
	server = create_http_server(
		application,
		host=args.host,
		port=args.port,
		max_body_bytes=args.max_body_mb * 1024 * 1024,
		read_timeout_seconds=args.read_timeout_seconds,
		max_workers=args.max_workers,
	)
	print(f"AOV archive backend listening on http://{args.host}:{server.server_port}")
	print(f"Database: {Path(args.db).expanduser().resolve()}")
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		pass
	finally:
		server.server_close()
	return 0


if __name__ == "__main__":
	raise SystemExit(main())


__all__ = ["_is_loopback_address", "create_http_server", "default_database_path", "main"]