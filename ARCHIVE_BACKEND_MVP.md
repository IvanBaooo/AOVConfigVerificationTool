# AOV archive backend MVP

This service receives immutable package archive records from the local packer.
It does not dispatch package jobs and does not upload files to FTP.

## Scope

- Validate the final V1 JSON Schema and application-level contract invariants.
- Store archive records in SQLite.
- Enforce idempotency and package ID uniqueness transactionally.
- Provide authenticated list and detail APIs for the web management UI.
- Serve the archive management MVP from the same backend process.
- Keep `/health` public for local monitoring.

## Install

```powershell
cd C:\Users\admin\Documents\AOVConfigVerification\AOVAutoPacker
python -m pip install -r requirements-backend.txt
```

## Run

For the current loopback-only MVP, start without authentication:

    python -m archive_backend.server --host 127.0.0.1 --port 8780 --no-auth

The --no-auth option is rejected for non-loopback hosts. To restore bearer
authentication, omit that option and set a long random token:

    $env:AOV_BACKEND_TOKEN = "replace-with-a-long-random-token"
    python -m archive_backend.server --host 127.0.0.1 --port 8780

The default database path is:

```text
%LOCALAPPDATA%\AOVAutoPackerBackend\archives.sqlite3
```

Override it with `AOV_BACKEND_DB` or `--db`. The batch entry is
`run_archive_backend.bat`.

The default host is loopback-only. Do not bind to a LAN/public interface until
TLS and the deployment firewall have been configured.

## Web management MVP

After the backend starts, open:

    http://127.0.0.1:8780/admin/

In the current --no-auth mode, the page opens directly without asking for a
Token. When bearer authentication is restored, the page asks for the same Token
configured in AOV_BACKEND_TOKEN and keeps it only in sessionStorage.

The current page supports:

- Archive list, region/version/status filters, and pagination.
- Package, validation, warning, revision, and file-list detail views.
- Backend health status and explicit token reconnection.

This is a read-only archive view. Packaging and the final "确认归档" action still
run manually on the local packing machine.

## API

### Health

```http
GET /health
```

No authentication is required.

### Create archive

```http
POST /api/v1/package-archives
Authorization: Bearer <token>
Content-Type: application/json
Idempotency-Key: <payload.idempotency_key>
X-AOV-Contract-Version: 1.0
```

- `201`: archive created.
- `200`: same idempotency key and same parsed JSON replayed.
- `409 idempotency_conflict`: same key with different JSON.
- `409 package_id_conflict`: same package ID under another key.
- `422 invalid_payload`: Schema or final contract invariant failed.

The default maximum request body is 10 MiB. Each request has a 15-second total deadline and the server runs at most 32 request workers by default; override these with `--read-timeout-seconds` and `--max-workers`.

### List archives

```http
GET /api/v1/package-archives?region_code=TW&validation_status=warning&limit=50&offset=0
Authorization: Bearer <token>
```

Supported filters:

- `region_code`
- `package_version`
- `package_status`
- `validation_status`
- `limit` from 1 to 200
- `offset` from 0 to 1,000,000

### Archive detail

```http
GET /api/v1/package-archives/{package_id}
Authorization: Bearer <token>
```

The response contains the complete immutable archive payload. FTP, mail, and
delivery states remain outside this record and will be added as separate APIs.

### Latest release baseline

```http
GET /api/v1/release-baselines/latest?region_code=TW
Authorization: Bearer <token>
```

The baseline is derived from the newest confirmed archive for the requested
region. It returns the exact released revision set, its original revision spec,
the maximum checked revision, backend archive time, package ID, and package
version. The local packer loads it on startup and region changes. A missing or
unavailable baseline never clears manual baseline input and does not block
packaging.

## Verification

```powershell
python -m pip install -r requirements-test.txt
python -m unittest discover -p "test_archive_backend_*.py" -v

```

The next implementation stage is the local synchronization queue and a more
complete web workflow state model. Packaging remains independent from network
availability.
