# Backend archive contract V1

## Purpose

The local packer builds an allowlisted archive payload from the generated
`report.json`. The payload contains package identity, release revisions,
validation results, readable warnings, region-filter statistics, and packaged
file metadata.

It intentionally excludes SVN credentials, raw SVN logs, raw SVN lines, local
file paths, and local dtxml/xml source paths.

## Proposed endpoint

```http
POST /api/v1/package-archives
Content-Type: application/json
Idempotency-Key: sgame_TW_Beta54_20260713153524
X-AOV-Contract-Version: 1.0
```

The request body must conform to:

```text
schemas/aov-package-archive-v1.schema.json
```

The local builder is:

```python
from backend_archive_contract_v1 import build_archive_record

payload = build_archive_record(report)
```

## Idempotency

The backend must place a unique constraint on `idempotency_key`.

- First request with a key: create the archive record and return `201`.
- Retry with the same key and same payload: return the existing record with `200`.
- Same key with materially different payload: return `409`.

This allows the local client to retry network failures without creating duplicate
archive records.

## Suggested responses

```text
201  archive record created
200  idempotent replay; existing record returned
400  malformed JSON
401  missing or invalid client credentials
403  client has no permission for this region
409  idempotency key conflicts with a different payload
422  payload does not match contract version 1.0
429  rate limited; retry with backoff
5xx  server failure; retry with backoff
```

## Payload groups

- `release`: region, version, previous external revision/time, current revisions.
- `package`: archive name, hashes, counts, and artifact filenames.
- `status`: package, validation, FTP, archive, and mail state snapshots.
- `region_filter`: original, included, and excluded ServerBytes counts.
- `validation.summary`: error, warning, confirm, and skipped counts.
- `validation.commit_record`: readable missing-change warnings and whitelist hits.
- `validation.checks`: per-rule results (type, name, status, counts, table attribution, capped items/warnings); skin precheck, when enabled, appears as an ordinary entry.
- `files`: allowlisted packaged-file metadata without raw SVN text or local paths.

## Sync order

1. Local package and validation complete.
2. FTP upload runs when enabled.
3. Local client builds the V1 archive payload.
4. Local client sends the payload with `Idempotency-Key`.
5. On `200/201`, local state becomes `archive_status=succeeded`.
6. On retryable failure, the payload remains locally queued with the same key.

FTP remote path and upload timestamps can be added as optional `delivery` fields
in a backward-compatible V1 extension once the FTP implementation is finalized.
