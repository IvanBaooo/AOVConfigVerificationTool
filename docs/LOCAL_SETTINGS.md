# Local settings

Start the desktop app with the launcher (it also starts the local archive
backend when needed):

```powershell
.\start_packer.bat
```

or run the steps manually:

```powershell
python -m archive_backend.server --host 127.0.0.1 --port 8780 --no-auth
pnpm start
```

Local settings are stored in the project root:

```text
settings.json
```

Saved values include machine paths, SVN target and executable, SVN username,
authentication-cache preference, previous external baseline, package region and
version, validation switches, validation window, commit whitelist, backend URL,
and region-specific FTP profiles.

Validation rule switches are stored as `disabled_rule_ids` (list of rule IDs
disabled on the settings page) and `rule_name_overrides` (map of rule ID to a
custom display name). They overlay the backend/default rule set for local runs
only.

FTP profiles are keyed by `TW`, `TH`, `VN`, and `ID`. Each profile stores its
host, port, username, password, remote directory, and passive-mode setting:

```json
{
  "ftp_profiles": {
    "TW": {
      "host": "ftp.example.test",
      "port": "21",
      "username": "publisher",
      "password": "shared-password",
      "remote_directory": "/release/TW",
      "passive": true
    }
  }
}
```

The FTP password is stored as plain text in this local file. The current
revision, pasted SVN log or file list, SVN password, and backend token are not
saved.

For tests or an alternate machine-specific location, set
`AOV_AUTOPACKER_SETTINGS` to override the root settings file path.
