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

## Directory layout

- `src/renderer/`: React desktop frontend with shadcn-inspired primitives and design tokens.
- `electron/`: Electron main process and secure preload bridge. The renderer is built into `electron/dist/`.
- `electron_bridge.py`: Electron-to-Python command bridge (kept at the project root; `electron/main.js` spawns it from there).
- `packer_*.py`: packaging and report pipeline.
- `svn_*.py`: SVN log, revision, working-copy, and DTXML diff handling.
- `changeset_modules.py`: activity, item, reward, skin, and related analysis.
- `archive_backend/`: local archive API and admin frontend service (`python -m archive_backend.server`).
- `archive_web/`: archive management web assets.
- `backend_archive_contract/`: archive record builder package; the implementation lives in `backend_archive_contract/base.py`.
- `backend_archive_contract_v1.py`: final V1 contract builder and send-boundary validation.
- `schemas/`: V1 archive JSON Schemas.
- `tests/`: Python regression tests plus shared fixtures (`archive_fixtures.py`).
- `tools/`: auxiliary scripts (`create_icon.py`, `generate_svn_dtxml_diff.py`).
- `docs/`: design and contract documentation.

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

Double-click `start_packer.bat`, or run:

```powershell
.\start_packer.bat
```

The launcher checks the local archive backend, starts it on
`http://127.0.0.1:8780` when necessary, and then opens Electron.

To start the pieces manually:

```powershell
python -m archive_backend.server --host 127.0.0.1 --port 8780 --no-auth
pnpm start
```

`pnpm start` builds the React renderer and launches the desktop app. The
renderer keeps the existing `window.aov` bridge contract, so Python packaging,
SVN, FTP, and archive behavior remain in the backend/core modules.

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

Run all Python tests from the project root (use the project virtualenv when
present, since it carries the test dependencies such as `jsonschema`):

```powershell
.venv/bin/python -m unittest discover -s tests -v
```

or with any Python that has the test requirements installed:

```powershell
python -m unittest discover -s tests -v
```

Check Electron JavaScript syntax and the renderer build:

```powershell
pnpm run check
```

Generated packages, local settings, caches, SQLite databases, logs,
`node_modules`, and analysis snapshots are excluded from version control.
