# Selected catalog projection: reviewed retention and refusal diagnostics

Refs #1581. This package preserves the exact source and fixtures reviewed by
Kai on October 9, 2026, together with the executed evidence. It enables selected
membership and target evidence for the Ember training-data consumer. Projection,
data admission, and consumer loading have separate acceptance requirements.

## Implementation

`selected_projection_preselected_leo74705_v2.cs` preselects membership IDs in the
existing hash pass. Pass 1 constructs full `Member` objects only for those IDs.
ID-only duplicate checks and global leakage indexes still cover every row.
The two metadata passes, 512 MiB private/process/job limits, 900-second ceiling,
BelowNormal priority, and one compute thread are preserved.

Diagnostic snapshots retain index cardinalities and the triggering PrivateUsage
observation before a cap refusal. A refusal with no successful memory sample
records a null peak and zero samples. `run_selected_projection_preselected_leo74705.ps1`
preserves the exception chain and these diagnostics without accepting a result.

`byte-identity-manifest.json` maps all 23 reviewed artifacts and six additional
review/run artifacts to their SHA-256 and expected Git blob IDs. The local
`.gitattributes` disables text normalization for this byte-pinned package.
Baseline and rejected sources are fixture inputs, not the current implementation.

## Executed evidence

- Kai's independent review receipt is `evidence/kai-successor90fea10d-review.json`.
  It covers the frozen source and synthetic evidence, not production feasibility.
- `synthetic-preselection-green-v2/preselection-validation.json` records both
  JSON array orders at 11 and 8,203 all-row IDs with eight selected Members.
  Each summary and both selected JSONL outputs match the distinct baseline:
  twelve byte-equal comparisons. Thirteen children have eight exits 0 and five
  expected exits 1; every child records cleanup and no timeout.
- Cap red/green, private-memory observer, duplicate-outside-selection, and
  zero-sample refusal fixtures are preserved. The old equality result routed
  both runs to the candidate and is invalid evidence; the corrected fixture
  explicitly binds distinct baseline and candidate bytes.
- The single released production run **refused** with `System.OutOfMemoryException`
  in pass 2 at `Dictionary.Resize`. PID 49512 ran from
  `2026-10-09T16:14:49.5149964Z` to `2026-10-09T16:15:03.9522946Z`, exit 1,
  with verified cleanup and zero remaining Job Object processes.
- `evidence/run-refusal.json` records a maximum successful PrivateUsage sample
  of 458,637,312 bytes across 90,015 samples. The failing allocation's size and
  instantaneous memory use are unrecorded. These samples do not prove that the
  536,870,912-byte OS limit was exceeded.
- Refusal diagnostics show 130,578 retained Members and 293,852 global IDs.
  Pass 2 fails at row 1,525,716 with 17,519 object-index entries. These are
  diagnostic cardinalities, not accepted projection or admitted-token counts.

No accepted projection, membership/target consumer packet, admission, or consumer
load resulted. The production attempt is consumed; no automatic retry is allowed.
The preserved handoff and launch scripts describe their historical states and
machine-specific paths. They are not fresh execution permission.

## Synthetic reproduction

On Windows with PowerShell 7, copy the top-level `.cs` and `.ps1` fixture files
into a new empty C: scratch directory. Do not copy the existing generated receipt
directories into that execution directory. Use the repository's finite process
guard and the required hidden Python wrapper; Python requires the current GPU
window marker to be absent. No production data is needed for this fixture:

```powershell
powershell.exe -NoLogo -NoProfile -NonInteractive -File C:/Users/Admin/.codex/headless-python.ps1 -- -B <repo>/src/ember/governance/scripts/owned_process.py --timeout-seconds 900 -- pwsh.exe -NoLogo -NoProfile -NonInteractive -File <fresh-C-scratch>/validate-preselection-v2.ps1 -CandidateSourcePath <fresh-C-scratch>/selected_projection_preselected_leo74705_v2.cs -CandidateRunnerPath <fresh-C-scratch>/run_selected_projection_preselected_leo74705.ps1
```

The cap snapshot fixture accepts `-SourcePath` and a new `-ReceiptPath`.
The private-memory observer also requires `-ExpectedSha256` equal to
`90fea10d7a01057d86655a19f7b59d9b560c7aadb92848ca78ff1aad2ddce1de`.
Prediction-schema and production-binding scripts retain historical machine inputs;
they need their own current scope and pins before execution.

Production memory feasibility remains unresolved. A subsequent repair or run
requires a new bounded scope and its review/resource release. This PR does not
close #1581 or provide data-admission credit.
