#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bind the RUNNING tokenizer identity into the identity manifest, fail-closed.

cond3 increment (tokenizer_data_lineage category, tokenizer sub-field): the identity
manifest's ``tokenizer.sha256`` must be the identity of the tokenizer the model actually
tokenizes with -- NOT the sha of a raw ``tokenizer.json`` file. Those differ, and the
difference is load-bearing:

- The frozen tokenizer's on-disk bytes are DELIBERATELY NOT COMMITTED to the repo
  (custody: the recovered shard-generation tokenizer, raw-file sha
  2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97, is pinned by the
  step-776 freeze receipt but its bytes live in custody, not git). So "repair the
  artifact and hash it on disk" (artifact-repair) is forced out -- it would commit
  custody-held bytes. The binding is in-memory-decoder-attach instead.
- The production encode path (``scripts/token_shards_v0._production_tokenizer`` with
  ``match_added_tokens=False``, the ENCODE_SEMANTICS the shards were generated under, and
  what ``scripts/a1_predicate_scan.load_stripped_tokenizer`` is a verbatim reuse of)
  loads that sha-pinned file and STRIPS the ``added_tokens`` table IN MEMORY before
  building the tokenizer, so ids 0..7 are unreachable from text. The sha of the raw file
  is therefore NOT the identity of the object that runs; the identity of the runtime
  object is the sha of the in-memory, post-strip tokenizer.

This module binds against the REAL, canonical production loader
``token_shards_v0._production_tokenizer(match_added_tokens=False)`` -- the one the shards
were produced with, importable without tripping the execution-denied sub-3B cbase trainer
(``a1_predicate_scan`` and ``ember_cbase_avir_data`` both transitively import that denied
trainer and cannot be imported here; ``token_shards_v0`` is the canonical source they
derive from and imports clean). It records TWO real quantities:

- ``running_identity_sha256`` -- sha256 of the post-strip attached tokenizer's canonical
  serialization (``Tokenizer.to_str()``). THIS is what ``tokenizer.sha256`` binds to.
- ``provenance_sha256`` -- the receipt-pinned raw-file sha of the uncommitted frozen
  artifact, re-verified from the bytes the loader is pointed at (the loader's own
  sha-drift guard, ``_production_tokenizer``'s ``ValueError("tokenizer.json ... sha
  drift")`` -- the analog of ``a1``'s ``A1_SCAN_TOKENIZER_SHA_DRIFT``).

``verify_tokenizer_identity_binding`` re-derives BOTH via the same real loader and fails
closed -- naming the exact field -- on either a running-identity mismatch OR a provenance
drift, or an absent/empty ``tokenizer.id``.

Note on ``a1_predicate_scan.load_stripped_tokenizer``: it ADDITIONALLY drops orphaned
merge rules (a scan-only workaround for a recovered artifact that fails standard BPE
deserialization), which produces a DIFFERENT tokenizer than production. That scan
approximation is not the running identity; the production ``_production_tokenizer`` object
is. The independently-computed orphan-merge count is still disclosed in the receipt
(``orphan_merges_present``) for transparency, but the bound identity is the production
object, not the scan's dropped-merge variant.

DEFERRED (out of this smallest-increment scope): the ``OWNED_ADMITTED`` artifact-bundle
resolution (proving the provenance sha also appears as a content-addressed bundle entry)
threads the full ``ember-artifact-bundle-v1`` bundle through validate_manifest's admission
gate and is a separate, non-additive path; the manifest's closed ``tokenizer`` object is
``{id, sha256}`` and cannot carry a second sha field without a schema change, so the
provenance sha is carried in the evidence RECEIPT (verified here), never invented into the
manifest.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Mapping

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]  # ember/scripts
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# The canonical, importable production tokenizer loader (added_tokens stripped in memory,
# sha-drift guarded). a1_predicate_scan.load_stripped_tokenizer is a verbatim reuse of
# this; a1 itself cannot be imported (transitively pulls the execution-denied cbase
# trainer), so we bind against the canonical source directly.
import token_shards_v0  # noqa: E402

TOKENIZER_ENCODE_SEMANTICS = "added-token-matching-disabled-v1"


class TokenizerIdentityMismatch(ValueError):
    """A manifest's claimed tokenizer identity diverges from measured evidence."""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count_orphan_merges(tokenizer_json_path: Path) -> int:
    """Independently count merge rules whose join is absent from the model vocab.

    Disclosure only (a1's scan-workaround territory); the production loader does NOT drop
    these -- it requires a clean artifact. A production tokenizer.json has zero. Recorded
    so the receipt carries the same transparency field a1's loader returns."""
    import json

    data = json.loads(Path(tokenizer_json_path).read_text(encoding="utf-8"))
    model = data.get("model", {}) if isinstance(data, Mapping) else {}
    merges = model.get("merges")
    if not isinstance(merges, list):
        return 0
    vocab = model.get("vocab", {})

    def _joined(merge: Any) -> str:
        parts = merge.split(" ") if isinstance(merge, str) else list(merge)
        return "".join(parts)

    return sum(1 for merge in merges if _joined(merge) not in vocab)


def _load_running_tokenizer(tokenizer_json_path: Path, provenance_sha256: str):
    """Drive the REAL production loader against the artifact, sha-drift guarded.

    Builds the minimal ``tokfreeze`` receipt the production loader expects
    (``tokenizer_repo_path`` + ``tokenizer_json_sha256``) so its own sha guard fires on
    any drift between the receipt-pinned provenance sha and the bytes on disk. Returns the
    post-strip runtime tokenizer object."""
    path = Path(tokenizer_json_path)
    corpus_dir = str(path.parent)
    tokfreeze = {
        "tokenizer_repo_path": path.name,
        "tokenizer_json_sha256": provenance_sha256,
    }
    return token_shards_v0._production_tokenizer(
        corpus_dir, tokfreeze, match_added_tokens=False
    )


def measure_tokenizer_identity(
    tokenizer_json_path: Path, *, provenance_sha256: str | None = None
) -> dict[str, Any]:
    """Measure the running tokenizer identity from a real artifact via the production loader.

    ``provenance_sha256`` is the receipt-pinned raw-file sha of the frozen artifact. If
    None it is computed from the bytes the loader is pointed at (first measurement). The
    production loader is then driven against that sha (its drift guard fires on mismatch),
    the post-strip runtime tokenizer is serialized, and its sha256 is the running identity.
    Nothing is invented: both shas trace to bytes/loader output.
    """
    path = Path(tokenizer_json_path)
    try:
        real_provenance = _file_sha256(path)
    except OSError as error:
        raise TokenizerIdentityMismatch(
            f"tokenizer artifact at {path} could not be read from disk to "
            f"content-address it ({error})"
        ) from error
    provenance = provenance_sha256 or real_provenance
    if provenance != real_provenance:
        raise TokenizerIdentityMismatch(
            f"tokenizer provenance_sha256={provenance!r} does not match the artifact "
            f"bytes on disk ({real_provenance!r})"
        )
    try:
        running_tokenizer = _load_running_tokenizer(path, provenance)
    except TokenizerIdentityMismatch:
        raise
    except Exception as error:  # ValueError sha-drift, strip-probe failure, deser errors
        raise TokenizerIdentityMismatch(
            f"the production tokenizer loader failed to build a running tokenizer from "
            f"{path} ({type(error).__name__}: {error}); the artifact does not load as the "
            "sha-pinned running tokenizer"
        ) from error
    running_identity = hashlib.sha256(
        running_tokenizer.to_str().encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "ember-tokenizer-identity-receipt-v1",
        "result": "MEASURED",
        "encode_semantics": TOKENIZER_ENCODE_SEMANTICS,
        "provenance_sha256": provenance,
        "running_identity_sha256": running_identity,
        "orphan_merges_present": _count_orphan_merges(path),
    }


def bind_tokenizer_identity(
    manifest: Mapping[str, Any], receipt: Mapping[str, Any], *, tokenizer_id: str
) -> dict[str, Any]:
    """Project a MEASURED running-identity receipt into the manifest's tokenizer section.

    ``tokenizer.sha256`` binds to the receipt's ``running_identity_sha256`` (the post-strip
    runtime object), NOT the raw-file provenance sha. ``tokenizer.id`` is the caller's
    stated non-empty identity. The provenance sha stays in the receipt (the manifest's
    closed ``{id, sha256}`` object has no field for it; carried as evidence, verified by
    ``verify_``)."""
    if receipt.get("result") != "MEASURED":
        raise TokenizerIdentityMismatch(
            "receipt is not measured evidence; refusing to bind an unmeasured tokenizer "
            "identity"
        )
    if not isinstance(tokenizer_id, str) or not tokenizer_id.strip():
        raise TokenizerIdentityMismatch(
            f"tokenizer.id must be a non-empty string; got {tokenizer_id!r}"
        )
    running_identity = receipt.get("running_identity_sha256")
    if not isinstance(running_identity, str) or len(running_identity) != 64:
        raise TokenizerIdentityMismatch(
            f"receipt running_identity_sha256 is not a 64-hex digest: {running_identity!r}"
        )
    bound = dict(manifest)
    bound["tokenizer"] = {
        **dict(manifest.get("tokenizer", {})),
        "id": tokenizer_id,
        "sha256": running_identity,
    }
    return bound


def verify_tokenizer_identity_binding(
    manifest: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    tokenizer_json_path: Path,
) -> None:
    """Fail closed the instant the manifest's tokenizer identity diverges from evidence.

    Re-derives BOTH shas via the same real production loader (never the manifest against
    itself):

    1. Provenance: the raw artifact is re-hashed and driven through the loader's sha-drift
       guard against ``receipt.provenance_sha256``. A drifted/absent artifact fails here
       (the manifest-side analog of ``a1``'s ``A1_SCAN_TOKENIZER_SHA_DRIFT``).
    2. Running identity: the post-strip runtime tokenizer is re-serialized and re-hashed;
       ``receipt.running_identity_sha256`` and ``manifest.tokenizer.sha256`` must both
       equal it. A manifest bound to the raw-file sha, or to any object other than the
       running tokenizer, fails here.
    3. ``tokenizer.id`` must be present and non-empty.

    Raises ``TokenizerIdentityMismatch`` naming the exact field. Silent when every bound
    value matches the freshly measured evidence.
    """
    tokenizer = manifest.get("tokenizer")
    if not isinstance(tokenizer, Mapping):
        raise TokenizerIdentityMismatch("manifest has no tokenizer section to verify")

    claimed_id = tokenizer.get("id")
    if not isinstance(claimed_id, str) or not claimed_id.strip():
        raise TokenizerIdentityMismatch(
            f"tokenizer.id must be a present, non-empty string; got {claimed_id!r}"
        )

    claimed_provenance = receipt.get("provenance_sha256")
    path = Path(tokenizer_json_path)
    try:
        real_provenance = _file_sha256(path)
    except OSError as error:
        raise TokenizerIdentityMismatch(
            f"tokenizer artifact at {path} could not be read to re-derive its hash; "
            f"receipt claims provenance_sha256={claimed_provenance!r} but no such bytes "
            f"exist to verify against ({error})"
        ) from error
    if real_provenance != claimed_provenance:
        raise TokenizerIdentityMismatch(
            f"receipt claims tokenizer provenance_sha256={claimed_provenance!r} but the "
            f"artifact bytes on disk hash to {real_provenance!r} (sha drift)"
        )

    try:
        running_tokenizer = _load_running_tokenizer(path, claimed_provenance)
    except Exception as error:
        raise TokenizerIdentityMismatch(
            f"re-running the production tokenizer loader against {path} failed; the "
            f"receipt's running identity does not independently re-derive "
            f"({type(error).__name__}: {error})"
        ) from error
    real_running = hashlib.sha256(
        running_tokenizer.to_str().encode("utf-8")
    ).hexdigest()

    if receipt.get("running_identity_sha256") != real_running:
        raise TokenizerIdentityMismatch(
            f"receipt claims running_identity_sha256="
            f"{receipt.get('running_identity_sha256')!r} but the post-strip runtime "
            f"tokenizer re-serializes to tokenizer.sha256={real_running!r}"
        )
    if tokenizer.get("sha256") != real_running:
        raise TokenizerIdentityMismatch(
            f"manifest claims tokenizer.sha256={tokenizer.get('sha256')!r} but the "
            f"post-strip runtime tokenizer re-serializes to tokenizer.sha256="
            f"{real_running!r} (a raw-file sha or any non-runtime object fails here)"
        )
