# EMBER-02 admission verifiers

These five scripts are the executable trust root for `ember-owned-rung-v1` checkpoint
claims. `src/ember/governance/scripts/ember_restart/contract.py` resolves them through
`../trusted-verifiers-v1.json`, pins them by sha256, and runs each one with
`sys.executable -I` and `cwd` set to the rung manifest's directory.

Two properties are load-bearing and must survive every edit:

1. **Self-contained.** No import from `scripts/`, no third-party package. A verifier
   that imported the code it audits would not be independent, and `-I` isolation
   would not resolve the import anyway.
2. **Re-derived, never restated.** Each verifier is handed evidence bytes, never the
   receipt it is checking. Every field it prints is recomputed from those bytes;
   `contract.py` then compares its output field-by-field against the receipt. A
   verifier that echoed a receipt value would make that comparison vacuous.

Paths inside an evidence manifest are relative to the rung manifest root, which is
the process working directory — resolve them as plain relative paths.

Verifiers fail closed: when evidence needed to decide a criterion is missing or
malformed, exit non-zero rather than printing a verdict.
