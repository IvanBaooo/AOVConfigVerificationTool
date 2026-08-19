# Backend archive contract - CURRENT

Use only the following V1 files for new integration work:

```text
Builder: backend_archive_contract_v1.py
Schema:  schemas/aov-package-archive-v1-final.schema.json
Tests:   test_backend_archive_contract_v1.py
```

The earlier `backend_archive_payload.py`, `backend_archive_contract.py`, and
non-final schema files are implementation history and must not be imported by
the web-backend integration.

## Verification

```powershell
python -m pip install -r requirements-test.txt
python -m unittest discover -v
```

The suite includes Draft 2020-12 validation of the complete final Schema with its
local strict-Schema reference.

## Create request

```http
POST /api/v1/package-archives
Content-Type: application/json
Idempotency-Key: <payload.idempotency_key>
X-AOV-Contract-Version: 1.0
```

```python
from backend_archive_contract_v1 import build_archive_record, archive_create_headers

payload = build_archive_record(report)
headers = archive_create_headers(payload)
```

The request is immutable. It contains package and validation facts, but not FTP,
archive-delivery, or mail states.

## State updates

- FTP result: `PUT /api/v1/package-archives/{package_id}/delivery/ftp`
- Mail and reply state: maintained by the backend.
- Local archive-delivery status: kept in the local retry queue.

## Server idempotency semantics

- Enforce a unique database constraint on `(schema_version, idempotency_key)`.
- The first valid request atomically stores the key and archive record, then returns `201`.
- The same key with the same parsed JSON value returns the existing record with `200` and
  `Idempotency-Replayed: true`; object key order is ignored and array order is significant.
- The same key with a different parsed JSON value returns `409 idempotency_conflict` and
  must not mutate the existing record.
- `package_id` is also unique. The same package ID under a different key returns
  `409 package_id_conflict`.
- Concurrent requests are resolved by the unique constraint in the same transaction; only
  one request creates the record and the others follow the replay/conflict rules above.

## Retry policy

- Connect timeout 5 seconds; response timeout 15 seconds.
- Retry connection failures, timeouts, `408`, `429`, `500`, `502`, `503`, `504`.
- Respect `Retry-After` up to 120 seconds.
- Otherwise retry after 2, 4, 8, 16, and 32 seconds with jitter.
- Stop after 6 attempts and persist the payload for a later retry.
- Never change the idempotency key when retrying the same payload.
- Do not automatically retry `400`, `401`, `403`, `409`, or `422`.

## Boundary guarantees

The final builder rejects:

- Credentials, raw SVN fields, and Windows/UNC local paths at any nesting depth.
- Invalid, negative, boolean, or duplicate numeric/revision values.
- Package counts that do not match file statuses.
- Unsafe package IDs and idempotency keys.
- Absolute artifact paths, Windows reserved names, wildcards, and trailing dots/spaces.
- Unknown keys inside skin sale-field maps and unknown region-directory keys.

JSON Schema validates the structural boundary. Recursive local-path rejection and
source-report count reconciliation are application-level invariants enforced by
`backend_archive_contract_v1.py`.
