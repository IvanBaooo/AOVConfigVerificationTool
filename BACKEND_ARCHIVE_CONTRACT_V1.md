# Backend archive contract V1 - current

This document supersedes the earlier draft `BACKEND_ARCHIVE_CONTRACT.md`.

## Immutable create endpoint

```http
POST /api/v1/package-archives
Content-Type: application/json
Idempotency-Key: sgame_TW_Beta54_20260713153524
X-AOV-Contract-Version: 1.0
```

Canonical local builder:

```python
from backend_archive_contract import build_archive_record

payload = build_archive_record(report)
```

Canonical machine-readable schema:

```text
schemas/aov-package-archive-v1-strict.schema.json
```

The create payload contains immutable packaging facts only. `status` contains
`package_status` and `validation_status`. FTP, archive-sync, and mail states do
not belong to the idempotent create payload.

## Mutable state ownership

- FTP status and remote path: updated separately after upload.
- Archive-sync status: local delivery state, not part of the archived record.
- Mail status and reply tracking: backend-owned state.

Proposed FTP result endpoint:

```http
PUT /api/v1/package-archives/{package_id}/delivery/ftp
```

The FTP endpoint can be idempotent on `{package_id, upload_attempt_id}` without
changing the immutable package-create payload.

## Idempotency behavior

- First request: create and return `201`.
- Same key and byte-equivalent immutable payload: return existing record with `200`.
- Same key and different immutable payload: return `409` and do not overwrite.

The backend must enforce a unique constraint on `idempotency_key`.

## Retry policy

- Connect timeout: 5 seconds.
- Response timeout: 15 seconds.
- Retry connection failures, timeouts, `408`, `429`, `500`, `502`, `503`, `504`.
- Respect `Retry-After`, capped at 120 seconds.
- Otherwise use exponential delays of 2, 4, 8, 16, 32 seconds with jitter.
- Stop the immediate run after 6 attempts and keep the same payload queued locally.
- Later manual or scheduled retry must reuse the same `Idempotency-Key`.
- Do not retry `400`, `401`, `403`, `409`, or `422` automatically.

## Data boundary

The strict builder rejects malformed counts, invalid or duplicate revisions,
unsafe idempotency keys, invalid hashes, and artifact paths that are not plain
filenames.

The payload excludes:

- SVN username and password.
- Raw SVN logs and raw changed-path lines.
- Local file paths.
- Local dtxml/xml source paths.
- Unknown nested skin-validation fields.

Skin sale fields use an explicit allowlist so future nested values cannot bypass
the archive boundary.
