# Installed Authority Marker Migration Design

## Problem

An Ember desktop installation upgraded from the legacy authority layout can retain the installer-owned root `GOAL.md` while the current installer also writes `docs/domains/governance/authority/GOAL.md`. The runtime source-root resolver requires exactly one authority marker, so the admitted installed executable refuses before opening its Windows Terminal UI.

## Design

Keep the strict runtime resolver unchanged. During `Install-StableFiles`, migrate only the legacy marker that the installer itself owns:

- If root `GOAL.md` is absent, continue normally.
- If its raw bytes equal one of the closed historical UTF-8 BOM/no-BOM encodings, migrate it; decoded matching UTF-16/UTF-32 text is foreign.
- Reject a marker reached through any symlink, junction, or reparse component.
- Reject a canonical destination that is non-file or crosses a reparse component; reopen its exact raw bytes after atomic publication.
- If it contains any other bytes, refuse without deleting or replacing it.
- Continue creating the git-less `tools/ember-cli` marker directory and canonical `docs/domains/governance/authority/GOAL.md`.
- Complete all other stable-file writes before the marker transition. Publish the canonical marker atomically, remove the legacy marker last, and restore the prior canonical state if deletion fails.

This preserves the one-authority invariant, makes upgrades self-contained, and never treats foreign bytes as installer-owned.

## Verification

Extend the real desktop deployment self-test with two upgrade fixtures:

1. A legacy installed marker is removed and the admitted executable still launches with its exact exit code.
2. Foreign text, UTF-16 matching text, a junction-root marker, a canonical-directory destination, and a canonical-parent junction cause refusal without byte deletion or foreign writes.
3. A later stable-file failure or locked legacy deletion preserves a single byte-exact legacy authority marker.

After focused tests and repository guards pass, install the exact repaired commit, launch the verified desktop shortcut, and resume the real #1251 window and pointer acceptance.

## Claim Boundary

This repair establishes installed-launch admission only. It does not by itself prove #1251 visual, pointer, scroll, or closure acceptance.
