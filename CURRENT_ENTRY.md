# Current entry

The current local frontend is Electron. Run it with:

```powershell
run_electron_packer.bat
```

Or double-click:

```text
start_current_packer.bat
```

Install the Electron runtime once with:

```powershell
pnpm install
```

The existing Tkinter frontend remains available as a fallback and still uses
the same Python core:

```powershell
start_tkinter_packer.bat
```

Build the legacy Tkinter executable with:

```powershell
pyinstaller AOVAutoPackerCurrent.spec
```

The application stores machine settings in
`%LOCALAPPDATA%\AOVAutoPacker\settings.json`. That settings file never contains
the SVN password, current revision, or pasted SVN content.

Pending backend synchronizations are stored locally in
publication_queue.sqlite3 next to settings.json. The queue contains only the
immutable archive payload, backend URL, attempt count, and latest error. Use
AOV_PUBLICATION_QUEUE to override its location for testing.

The Use SVN auth cache option is managed by the SVN client itself. Depending
on the local SVN configuration, that separate SVN cache may store credentials;
it is not part of the AOVAutoPacker settings file.

SVN warning display names and commit whitelist formats are documented in
`SVN_WARNING_MAPPING.md`. The local report keeps both active warnings and
whitelisted changes for audit; path mappings supplied by backend rules take
priority over built-in mappings.
Validation rule delivery, regional overrides, caching, offline fallback, and
report metadata are documented in `VALIDATION_RULES_MVP.md`. The current local
backend contains the initial `aov-main` rule set at version `2026.07.27.1`.
The web admin at `http://127.0.0.1:8780/admin/` now includes a rule management
workspace with immutable history, structured common/regional editing, local
validation, change summaries, and manual publish confirmation. Rule reads are
public; publishing is restricted to the backend machine while no-auth mode is
active.
