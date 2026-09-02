# Windows Desktop Installation Design

Issue: [#1578](https://github.com/wordingone/ember/issues/1578)

## Outcome

Ember gains a normal per-user Windows installation. A stable Desktop or Start Menu shortcut launches a versioned, hash-admitted `Ember.exe` without consulting a Git checkout. The repository `tools/launchers/Ember.cmd` remains the developer launcher.

## Authority boundary

`scripts/install-ember-desktop.ps1` is the sole Windows deployment mutation entrypoint. It owns `Install`, `Repair`, `Rollback`, and `Uninstall`. Installed shortcuts target the immutable, hash-recorded `ember-lab.exe cockpit` command directly; there is no installed launcher script.

The installed artifacts live below `%LOCALAPPDATA%\Programs\Ember` unless `-InstallRoot` is explicitly supplied. Tests always supply an isolated root.

## Installed layout

```text
<install-root>/
  Ember.cmd
  versions/<commit>/ember-lab.exe
  current.json
  install-receipt.json
  versions/
    <40-lowercase-source-sha>/
      Ember.exe
      version.json
```

`current.json` is a closed schema containing `schema_version`, `source_commit`, `executable_sha256`, `executable_relative_path`, `installed_at_utc`, and `previous_source_commit`. Paths are forward-slash relative paths. The launcher rejects unknown or missing keys, absolute or escaping paths, invalid hashes, missing files, and byte mismatches before process creation.

Each immutable version directory also contains a closed `version.json` with the source commit, executable SHA-256, relative executable filename, and publication timestamp. Rollback derives authority from this per-version record; it never trusts a source SHA or directory name alone.

## Build and publication

The installer requires a clean source checkout and exact 40-character lowercase Git commit. It uses the existing pinned Bun/bootstrap and cockpit build logic. The build lands in a destination-volume staging name. Only a successful executable is moved into the immutable version directory. The executable is hashed after publication. The new manifest is written to a sibling temporary file and atomically renamed only after the version, launcher files, and shortcuts are ready. An interrupted install therefore leaves the previous manifest authoritative.

Reinstalling the same commit is idempotent: the existing executable must match the newly derived SHA or installation refuses. It is never silently overwritten with different bytes.

## Stable launch

The shortcut targets the immutable versioned `ember-lab.exe` with the fixed `cockpit` command and exact source/application/state arguments. Both runtime and application hashes are closed in the deployment manifests; the daemon exports terminal evidence.

## Shortcut contract

The installer uses `WScript.Shell` to create temporary `.lnk` files, reads them back, verifies target, arguments, working directory, description, and icon, then atomically replaces:

- the current user's Desktop `Ember.lnk`; and
- the current user's Start Menu `Programs\Ember.lnk`.

Both shortcuts target only stable installed files. The icon comes from the currently admitted Ember executable. The executable embeds the tracked `domains/lab/assets/ember.ico`; `build-cockpit.ts` binds that exact asset through Bun's Windows metadata arguments.

## Lifecycle

- `Install`: build, publish immutable version, install stable launchers and shortcuts, then switch `current.json`.
- `Repair`: validate current authority and recreate stable launchers/shortcuts without changing the version.
- `Rollback`: validate `previous_source_commit`, reopen that version's closed `version.json`, rehash its executable, switch current and previous, then repair shortcuts.
- `Uninstall`: remove the two owned shortcuts and installation root only. Repository files, model data, cockpit state, receipts outside the install root, and unrelated shortcuts are untouched.

Every successful or refused action writes a closed, path-free local receipt under the install root when that root exists. It records action, source/executable hashes, shortcut kinds, verdict, and error class, never host paths.

## Portability

Manifest validation, version selection, hash admission, rollback, and receipt shapes are platform-neutral concepts. Windows-specific PowerShell, `.lnk`, Desktop/Start Menu, and `WScript.Shell` code stays inside the Windows adapter. Future macOS bundles or Linux desktop entries must reuse the common contract instead of creating a second update authority.

## Tests

PowerShell probes run against isolated temporary directories and injectable Desktop/Start Menu roots. Tests first demonstrate that no deployment command exists. After implementation they cover closed-schema validation, path traversal, hash tampering, interrupted manifest publication, idempotent install, repair, rollback, scoped uninstall, stable launcher exit-code preservation, and real `.lnk` creation/readback on Windows.

Bun tests prove the tracked icon is included in canonical Windows build arguments. Repository CI runs the PowerShell deployment selftest on Windows. No test mutates the operator's real Desktop.

## Claim boundary

Windows per-user application deployment only. No model, training, GPU, checkpoint, capability, result, sufficient-pretraining, or milestone credit. `NO_NEW_PARALLEL_AUTHORITY`.
