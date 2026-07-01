# Dual-Repo `/baseline` Promotion Plan V0

Status: NOT EXECUTED.

## Local Repo Mapping Observed 2026-06-29

- `<private-ember-local-checkout>`
  - `origin`: `https://github.com/private remote.git`
  - `public`: `https://github.com/public remote.git`
  - branch/status observed: `ember-cli-src-recovery-20260627`, dirty with many modified/untracked receipts and work surfaces.

- `<public-ember-local-mirror>`
  - `origin`: `https://github.com/private remote.git`
  - `public`: `https://github.com/public remote.git`
  - branch/status observed: `public-clean-root-20260628`, untracked `reconstruct-after-delete.sh`.

No `baseline/` directory was observed in either checkout.

## Promotion Order

1. Finish staging packet under `state/ember-baseline/`.
2. Refresh all external anchors and lock exact source pins.
3. Run staging verifiers:
   - verdict parser help/sample;
   - line-ending verifier;
   - manifest generator;
   - schema validation.
4. Create `baseline/` in a clean public-safe checkout and copy only public-safe files.
5. Add or update `.gitattributes` with `baseline/** text eol=lf` plus any justified Windows exceptions.
6. Run verifiers from inside the public checkout and write receipts under `baseline/receipts/`.
7. Repeat in the private checkout, adding private-only supplements only if the parity report names them.
8. Compare manifests.
9. Commit or open PRs for both repos.
10. Record remote refs or PR URLs in `baseline/reports/report-v0.md`.

## Do Not Promote Yet

Current staging status is draft. Promotion now would create a visible `/baseline` directory, but it would not be undisputable because external metric rows and thresholds are not locked.