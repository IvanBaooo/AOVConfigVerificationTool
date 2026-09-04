# Manual archive MVP

The local packer does not publish automatically. A package can be archived only
after packaging finishes and the user reviews its Report.

## Workflow

1. Package locally and generate the `.tar.gz` and Report.
2. Open and review the Report from the Daily tab.
3. Click `确认归档`.
4. Rebuild the final V1 archive payload and verify the `.tar.gz` MD5/SHA256
   against the Report.
5. Inspect the configured FTP directory for the formal `.tar.gz` filename.
6. Upload the formal filename with local progress, or use a same-size existing
   file only after explicit confirmation.
7. Verify the remote FTP size.
8. Submit the Report-derived final payload to the archive backend.

## FTP duplicate handling

- No remote file: upload the formal `.tar.gz` filename.
- Same filename and same size: ask the user whether to use the existing file.
- Same filename and different size: ask the user whether to delete it and
  upload again.
- No existing file is overwritten without explicit confirmation.

An interrupted or failed upload attempts to delete the incomplete formal file.
If cleanup fails, the GUI warns that manual FTP cleanup is required.

## Partial failures

- FTP failure: do not call the backend and do not create a synchronization item.
- FTP success and backend failure: keep the FTP file and persist the immutable
  archive payload in publication_queue.sqlite3.
- The 待同步 N button retries only the backend request; it never uploads FTP
  again.
- Retry attempts retain the original idempotency key and record the latest error.
- A successful created or replayed response removes the pending queue item.
- Backend conflict or payload rejection remains pending for manual investigation.
- The queue stores no FTP password, SVN credential, or backend token.

## Local configuration

Persisted machine settings:

- Region-specific FTP profiles for TW, TH, VN, and ID
- Each FTP profile contains host, port, username, password, remote directory, and passive mode
- Backend base URL

The selected region automatically loads its FTP profile and starts a background
connection check. FTP profiles are stored in the local settings file, including
the shared FTP password in plain text.

Session-only secret:

- Backend bearer token when backend authentication is enabled

The backend token can also be supplied through AOV_BACKEND_TOKEN. It may be
empty while the loopback backend runs with --no-auth. FTP credentials and
backend tokens are never written to the package Report or synchronization queue.

## Current boundary

The immutable backend archive stores the final Report payload. FTP delivery
metadata remains separate and is not yet displayed by the web management UI.
