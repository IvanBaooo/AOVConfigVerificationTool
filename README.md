# AOVAutoPacker

AOVAutoPacker is a Windows local packaging and configuration-analysis tool. It
selects files from SVN revisions, packages the matching regional ServerBytes
content, analyzes DTXML changes through business modules, and allows an
operator to confirm FTP upload and backend archival.

## Current workflow

1. Select `TW`, `TH`, `VN`, or `ID` and enter one or more SVN revisions.
2. Read changed paths from SVN and verify the local working copy.
3. Build a regional `.tar.gz` package from ServerBytes files.
4. Generate a ChangeSet and interpret supported activity and item content.
5. Review the local report manually.
6. Confirm FTP upload and backend archival.

FTP upload and backend synchronization never run automatically after packaging.

## Components

- `electron/`: current local desktop frontend.
- `electron_bridge.py`: Electron-to-Python command bridge.
- `packer_*.py`: packaging and report pipeline.
- `svn_*.py`: SVN log, revision, working-copy, and DTXML diff handling.
- `changeset_modules.py`: activity, item, reward, skin, and related analysis.
- `archive_backend/`: local archive API and admin frontend service.
- `archive_web/`: archive management web assets.
- `test_*.py`: Python regression tests.

## Requirements

- Windows
- Python 3.11 or newer
- SVN command-line client
- Node.js and pnpm

Install Electron dependencies:

```powershell
pnpm install
```

Install Python dependencies when backend development is needed:

```powershell
python -m pip install -r requirements-backend.txt -r requirements-test.txt
```

## Start

Double-click `start_current_packer.bat`, or run:

```powershell
.\start_current_packer.bat
```

The launcher checks the local archive backend, starts it on
`http://127.0.0.1:8780` when necessary, and then opens Electron.

## Local configuration

Copy the structure of `settings.example.json` into `settings.json` and configure
the local TdrTable paths, SVN target, backend URL, and regional FTP profiles.
The application also creates and updates `settings.json` from the settings page.

`settings.json` is intentionally ignored by Git because it may contain machine
paths, internal service addresses, usernames, and FTP passwords. SVN passwords
are runtime-only and are not persisted by this application.

Legacy defaults can be provided through environment variables:

- `AOV_TDR_SVN_ROOT_URL`
- `AOV_LOCAL_TDR_ROOT`
- `AOV_LOCAL_SERVERBYTES_ROOT`
- `AOV_SVN_EXE`
- `AOV_FTP_PASSWORD`
- `AOV_BACKEND_TOKEN`

## Tests

Run all Python tests:

```powershell
python -m unittest discover
```

Check Electron JavaScript syntax:

```powershell
pnpm run check
```

Generated packages, local settings, caches, SQLite databases, logs,
`node_modules`, and analysis snapshots are excluded from version control.
