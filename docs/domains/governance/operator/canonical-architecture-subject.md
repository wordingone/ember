# Canonical architecture subject

The selected CIA subject is manifests/ember-current-subject-v2.json. Its closed schema
contains only architecture_revision and checkpoint_manifest_sha256 under the existing
EMBER-02 authority binding. The v1 file and its predecessor/cursor/parameter fields remain
the historical sparse-v2 record.

The generator defaults to canonical v2 and accepts both schemas. Historical v1 rendering requires an explicit --subject-manifest manifests/ember-current-subject-v1.json. For v2, provide exactly one --selected-pointer,
--selected-manifest and --selected-pointer-sha256. It hashes the complete metadata files,
requires subject digest = selector digest = actual full manifest digest, and compares the
actual manifest architecture_revision. Missing files, duplicated JSON fields, missing or
repeated bindings, and a valid subject with the wrong architecture fail explicitly.
No config-only fallback or machine-local default is used.

The durable writer accepts v2 through its candidate-payload interface with explicit --candidate-schema ember-current-subject-v2. That mode reads bounded original bytes through the duplicate-rejecting decoder before any dictionary exists. V2 without that mode refuses. Historical v1 retains its original decoding and writer behavior. The library API accepts a dictionary; its caller must perform strict raw decoding before calling it. It verifies
the full metadata digest and architecture, verifies the pinned selector, preserves the
existing stale-parent and staged-reader checks, and uses the existing durable atomic
replace. It writes a separate v2 target; it cannot inherit or overwrite v1 history.
A caller-provided wrong architecture fails before staging. This metadata record does not
promote checkpoint bytes or establish model qualification.

Example identity-only check (paths must name actual complete selected metadata):

    python src/ember/governance/scripts/selected_subject_architecture.py --canonical-subject manifests/ember-current-subject-v2.json --selected-pointer <pointer.json> --selected-manifest <checkpoint-manifest.json> --selected-pointer-sha256 <full-pointer-SHA256>

The original current metadata contains local paths and remains private. Public reference copies in manifests/selected-cia-public-metadata-v1 remove exactly two local-path fields. The publication map records original hashes, sanitized-copy hashes and each removed field. Generation binds complete original local files and fails closed on mismatches; sanitized copies never substitute for that identity. The public synthetic
tests exercise functionality. A transformed public fixture has a different hash and cannot
prove the original selected digest. On Windows, every agent invocation uses the authorized
headless Python wrapper and contained hidden children during an owner-released window.

Live corpus revision was independently resolved from the public metadata API on
2026-10-09T19:54:00Z as 7d6d91a1823455a53cba77548ce0540ba2ad97e7. Resolution is separate
from availability, data admission and consumption. See native-operation-contract-v1.json.
