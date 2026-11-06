# ember-lab resume: one-action training with a certificate wall

## Today
`execute_cia_hour_once_v3.py` (302 lines) calls `ember-lab dispatch --manifest <v5>` on a packet built by
`prepare_template_hour_dispatch.py` (692 lines). Both live outside the repo, and the operator hand-authors the data ledger, cap, parent and env. The daemon token (`consume_dispatch`) proves the run came from ember-lab, but not that ember-lab chose its inputs.

## Shape
1. `ember-lab resume --root <ember> --state <dir>`:
   - parent = the selected-continuation-head pointer;
   - config = a committed, sha-pinned lineage config;
   - data = every intake with a PASS C1/C2 receipt, composed in dataset_id lexical order onto the trained ledger (the rebase logic from `build_h38_ledger_v1.py`), minus the lineage-disclosure exclusions file;
   - C1/C2 is re-run on the composed extension (the existing Python gate, receipted);
   - cap = admitted extension tokens, rounded down to whole updates.
2. Certificate: the existing certified-launch certificate schema, extended with `ledger_sha256`, `c1c2_receipt_sha256`, `parent_manifest_sha256` and `code_tree_sha`. It is issued as a row in ember-lab's SQLite db, never as a second authority type.
3. Wall A: the dispatch RPC handler refuses any manifest whose program is the trainer entrypoint (`cia_step_runner.py`) unless it cites a certificate sha present in the issuance table, with bindings equal to the manifest's. The trainer has no other entry, and the refusal happens before any GPU allocation.
4. Orchestration: the two scripts move into the repo verbatim, with goal headers only, and `resume` calls them from the repo path. A Rust port is follow-up, off the critical path.

## Claim boundary
Same-user forgery on one machine is not prevented by A alone (anyone with write access could edit the db). The wall is the issuance ledger plus wall C (CI fails a PR that removes or bypasses the check) plus wall B (the pointer advances only for a certified child).

## Also in this PR
`data_census::object_extents` uses checked offset arithmetic and refuses a row whose span starts below its first span.
