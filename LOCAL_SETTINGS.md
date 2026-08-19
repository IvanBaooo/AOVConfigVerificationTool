# Local settings

The current settings-enabled entry is:

```powershell
python AOVAutoPackerCurrent.py
```

It can also be started by double-clicking `start_current_packer.bat`.

Local settings are stored beside the source entry or packaged executable:

```text
AOVAutoPacker\settings.json
```

Saved values include machine paths, SVN target and executable, SVN username,
authentication-cache preference, previous external baseline, package region and
version, validation switches, validation window, commit whitelist, backend URL,
and region-specific FTP profiles.

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

Build the configured executable with:

```powershell
pyinstaller AOVAutoPackerCurrent.spec
```
