# Install Ember on Windows

Issue: [#1578](https://github.com/wordingone/ember/issues/1578)

Ember supports a normal per-user Windows installation with stable Desktop and Start Menu shortcuts. The default root is `%LOCALAPPDATA%\Programs\Ember`; installation does not require elevation and does not write the registry, services, scheduled tasks, or shell profiles.

From a clean Ember checkout, run:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts\install-ember-desktop.ps1 -Action Install
```

The installer builds the exact checked-out commit through the canonical pinned Bun launcher, publishes the executable below `versions\<source-sha>`, records its SHA-256 in closed manifests, and creates `Ember.lnk` on the Desktop and in the current user's Start Menu. The shortcut always targets the stable installed launcher. That launcher reopens `current.json`, contains the executable path under the install root, and rehashes the binary before starting it.

Lifecycle commands:

```powershell
# Revalidate the installed version and recreate both shortcuts.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts\install-ember-desktop.ps1 -Action Repair

# Switch to the previously installed version after reopening version.json and rehashing it.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts\install-ember-desktop.ps1 -Action Rollback

# Remove only the owned shortcuts and the per-user installation root.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts\install-ember-desktop.ps1 -Action Uninstall
```

`install-receipt.json` records a path-free local verdict. Version directories are immutable: a different executable for the same source commit is refused. An interrupted publication cannot replace `current.json` before the version and shortcut metadata are ready.

The manifest/version/rollback contract is deliberately platform-neutral. PowerShell and `WScript.Shell` are the Windows adapter; future macOS bundles and Linux desktop entries must reuse the same admission concepts instead of introducing another update authority.

Claim boundary: per-user Windows deployment only. No model, training, GPU, checkpoint, capability, result, or milestone credit. `NO_NEW_PARALLEL_AUTHORITY`.
