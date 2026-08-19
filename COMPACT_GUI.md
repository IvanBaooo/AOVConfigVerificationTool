# AOVAutoPacker Compact GUI

`AOVAutoPackerLocalCompact.py` is the compact local entry.

## Daily tab

Daily packing only exposes the two fields used most often:

- `Region`: `TW`, `TH`, `VN`, `ID`
- `Current revision`: examples `r1699919,r1699997` or `r10001-r10005`

The `Pack` button still runs the same V10 backend flow:

1. Fetch SVN log from the configured ServerBytes anchor.
2. Build the file list from the current revision input.
3. Filter files by the selected ServerBytes region.
4. Pack local files.
5. Apply naming, whitelist, commit check, and optional skin validation.

## Config tab

The config tab keeps fields that should later come from the web backend:

- ServerBytes local root
- TdrTable local root
- SVN target and SVN executable
- SVN auth cache, username, password
- Last external revision and time
- Scope roots
- Package version override
- Region filter switch
- Skin precheck window
- Manual SVN log / file list paste area
- Commit whitelist

When backend config sync is added, these values can be loaded into the same variables before packing. The Daily tab does not need to change.
