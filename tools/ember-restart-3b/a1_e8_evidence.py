# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""R1-E8 A1-vs-A3 liveness evidence producer.

Mints the closed `ember02-r1-e8-liveness-v1` packet
(`docs/spec/ember02-r1-e8-receipts-v1.md`) that `src/ember/governance/scripts/r1_e8_validator.py`
consumes as its first real downstream call. This module never trains, never
projects a charged budget, and never invents the R2 token forecast: DEV-008
assigns that projection to a separately frozen `ember02-r2-charged-budget-
contract-v1` external authority, which this module only reopens by exact raw
SHA-256. A missing contract is a permanent, distinguished evidence-missing
condition -- never a REFUSED verdict and never a fabricated projection.

Every field this module derives (contiguous per-step samples, tokens/second,
joules/token) is re-stated independently of `r1_e8_validator.py` rather than
imported from it -- the same "two independent transcriptions of one frozen
spec" discipline `r1_exit_battery.py` already documents for its own checks,
so a transcription defect in either surfaces as a refusal at first contact
instead of the producer validating itself.

The packet is a single flat directory (`packet_root`): every reopened or
minted file lives directly inside it, and every `{path, sha256}` reference
the liveness receipt carries is that file's bare name -- the validator's
`_reopen_ref` refuses any reference that is absolute, traverses, or escapes
the packet root, so the layout is not a convenience, it is the contract.

Raw per-step liveness telemetry reuses the frozen `train_step` envelope
(`{"ts":..., "kind":"train_step", "source":"ember-restart-3b", "payload":
{"run_id":..., "step":int, ...}}`) `r1_exit_battery.py` already scans for
loss/grad_norm, extended with three additional payload fields this producer
requires: `tokens` (int > 0), `wall_seconds` (decimal > 0, whole-boundary
step duration), and `proxy_joules` (decimal >= 0, from `energy_proxy_logger`
`sec5.3` accounting). `a1_execution.run_dense_a1` (issue #1464's first
residual) emits `tokens` and `wall_seconds` honestly, measured per step.
`proxy_joules` is derived by a distinct post-pass,
`a1_energy_apportionment.enrich_telemetry_with_energy` (issue #1464's second
residual, `docs/spec/ember02-r1-e8-receipts-v1.md`): it reopens the energy
sidecar's raw measured-window GPU samples and time-weight-integrates them
over each step's `[ts - wall_seconds, ts]` interval, adding `proxy_joules`
to the telemetry file in place only where a real sample record honestly
covers the interval -- never a placeholder. A step whose interval the
sidecar's samples do not cover (no sampler ran, sparse coverage, or the
interval reaches outside the sample record's own timestamp range) keeps no
`proxy_joules` field, so `derive_liveness_series` still correctly finds it
liveness-incomplete; this producer's own tests still construct the full
three-field envelope by hand for that reason, exactly as
`r1_exit_battery.py`'s own train_step selftest fixtures already do.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from pathlib import Path
from typing import Any
import uuid


LIVENESS_SCHEMA = "ember02-r1-e8-liveness-v1"
RUN_SCHEMA = "ember02-r1-e8-run-v1"
CONTRACT_SCHEMA = "ember02-r2-charged-budget-contract-v1"
LIVENESS_SERIES_SCHEMA = "ember02-r1-e8-liveness-series-v1"
THRESHOLDS_SCHEMA = "ember02-preregistration-thresholds-v1"
Q = Decimal("0.000000000001")

TIER1_FILENAME = "tier1-run.json"
A3_FILENAME = "a3-run.json"
A1_SERIES_FILENAME = "a1-live-series.json"
A3_SERIES_FILENAME = "a3-live-series.json"
CONTRACT_FILENAME = "charged-budget-contract.json"
LIVENESS_FILENAME = "a1-e8-liveness.json"

IDENTITY_FIELDS = {
    "comparison_id", "corpus_authority_sha256", "shard_sequence_sha256",
    "tokenizer_sha256", "seed", "cursor_start", "schedule_sha256", "genesis_sha256",
}
CONTRACT_FIELDS = {
    "schema_version", "status", "comparison_id", "a1_run_sha256",
    "a3_run_sha256", "projected_r2_tokens", "receipt_sha256",
}


class E8EvidenceProducerError(ValueError):
    """A structural or arithmetic defect in reopened evidence. Never raised
    for a merely-absent charged-budget contract -- see
    `E8EvidenceProducerMissing`."""


class E8EvidenceProducerMissing(E8EvidenceProducerError):
    """The externally authorized charged-budget contract is absent. DEV-008:
    this condition is permanent until a reviewed contract is published; the
    producer must never infer or select a projection formula to clear it."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _serial(value: Decimal) -> str:
    with localcontext() as ctx:
        ctx.prec = 50
        return format(value.quantize(Q, rounding=ROUND_HALF_EVEN), "f")


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise E8EvidenceProducerError(f"{label} must be a decimal string or integer")
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise E8EvidenceProducerError(f"{label} is not a valid decimal") from error
    if not result.is_finite():
        raise E8EvidenceProducerError(f"{label} is non-finite")
    return result


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        doc = json.loads(raw)
    except FileNotFoundError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise E8EvidenceProducerError(f"{label} is unreadable or invalid: {error}") from error
    if not isinstance(doc, dict):
        raise E8EvidenceProducerError(f"{label} top level must be an object")
    return doc, raw


def _self_digest_valid(doc: dict[str, Any]) -> bool:
    claimed = doc.get("receipt_sha256")
    unsigned = {key: value for key, value in doc.items() if key != "receipt_sha256"}
    return claimed == _sha256_bytes(_canonical(unsigned))


def _write_atomic_no_overwrite(target: Path, payload: bytes) -> None:
    """Create ONE new file, never replacing an existing one. Mirrors
    `durable_io.atomic_create_durable`'s Windows/POSIX durable-publish
    behaviour locally, so this module carries no cross-package import onto a
    sibling directory's private helper for a five-line primitive."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        if os.name == "nt":
            movefile_write_through = 0x00000008
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            if not kernel32.MoveFileExW(str(temporary), str(target), movefile_write_through):
                error = ctypes.get_last_error()
                if error in {80, 183}:
                    raise FileExistsError(target)
                raise ctypes.WinError(error)
        else:
            os.link(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _copy_verified(source: Path, target: Path) -> tuple[str, bytes]:
    """Copy an externally-produced evidence file into the packet root,
    byte-verified after the write. Refuses silently if `source` is absent
    (`FileNotFoundError` propagates) rather than minting a packet around a
    file that was never really there."""
    raw = source.read_bytes()
    _write_atomic_no_overwrite(target, raw)
    if target.read_bytes() != raw:
        raise E8EvidenceProducerError(f"{target} copy verification failed")
    return _sha256_bytes(raw), raw


def reopen_run_receipt(path: Path, *, arm: str) -> tuple[dict[str, Any], str]:
    """Reopen an already-minted `ember02-r1-e8-run-v1` receipt (arm A1's
    Tier-1 run from `a1_execution.finalize_tier1_run`, or the matched arm A3
    run from its own production route) and re-verify its self-digest and
    identity envelope. This function never constructs a run receipt -- it
    only refuses to carry one forward that is already malformed."""
    doc, raw = _load_json(path, f"{arm} run receipt")
    if not _self_digest_valid(doc):
        raise E8EvidenceProducerError(f"{arm} run receipt self-digest is invalid")
    if doc.get("schema_version") != RUN_SCHEMA or doc.get("arm_id") != arm or doc.get("status") != "TERMINAL":
        raise E8EvidenceProducerError(f"{arm} run receipt schema is invalid")
    identity = doc.get("identity")
    if not isinstance(identity, dict) or set(identity) != IDENTITY_FIELDS:
        raise E8EvidenceProducerError(f"{arm} run receipt identity is not closed")
    return doc, _sha256_bytes(raw)


def _iter_train_step_payloads(telemetry_path: Path, *, run_id: str):
    """Tolerant line-by-line reopen of the frozen train_step envelope,
    filtered to one run_id. Malformed or oversized lines are skipped rather
    than refusing the whole file -- mirrors `r1_exit_battery.py`'s own
    `_iter_jsonl_events` recovery discipline for the same file family."""
    with telemetry_path.open("rb") as handle:
        for raw_line in handle:
            if len(raw_line) > 4096:
                continue
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(event, dict) or event.get("kind") != "train_step" or event.get("source") != "ember-restart-3b":
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict) or payload.get("run_id") != run_id:
                continue
            yield payload


def derive_liveness_series(
    telemetry_path: Path, *, run_id: str, run_receipt_sha256: str
) -> dict[str, Any]:
    """Reopen raw per-step telemetry for `run_id` and mint a closed
    `ember02-r1-e8-liveness-series-v1` object bound to `run_receipt_sha256`.
    Refuses on any noncontiguous step, duplicate step, or nonpositive
    tokens/wall_seconds/negative proxy_joules -- the same numeric floor
    `r1_e8_validator._liveness_measurements` re-derives independently."""
    by_step: dict[int, dict[str, Any]] = {}
    for payload in _iter_train_step_payloads(telemetry_path, run_id=run_id):
        step = payload.get("step")
        if type(step) is not int or step <= 0:
            continue
        if not {"tokens", "wall_seconds", "proxy_joules"} <= set(payload):
            continue
        by_step[step] = payload
    if not by_step:
        raise E8EvidenceProducerError(f"no liveness-complete train_step rows for run_id={run_id!r} in {telemetry_path}")
    samples: list[dict[str, Any]] = []
    for expected_step in range(1, len(by_step) + 1):
        payload = by_step.get(expected_step)
        if payload is None:
            raise E8EvidenceProducerError(f"liveness telemetry step sequence is noncontiguous at step={expected_step}")
        tokens = _decimal(payload["tokens"], "liveness telemetry tokens")
        wall = _decimal(payload["wall_seconds"], "liveness telemetry wall_seconds")
        joules = _decimal(payload["proxy_joules"], "liveness telemetry proxy_joules")
        if tokens != tokens.to_integral_value() or tokens <= 0:
            raise E8EvidenceProducerError(f"liveness telemetry tokens must be a positive integer at step={expected_step}")
        if wall <= 0:
            raise E8EvidenceProducerError(f"liveness telemetry wall_seconds must be positive at step={expected_step}")
        if joules < 0:
            raise E8EvidenceProducerError(f"liveness telemetry proxy_joules must be non-negative at step={expected_step}")
        samples.append({
            "step": expected_step,
            "tokens": str(int(tokens)),
            "wall_seconds": _serial(wall),
            "proxy_joules": _serial(joules),
        })
    if len(by_step) != max(by_step):
        raise E8EvidenceProducerError("liveness telemetry step sequence carries a gap or a duplicate")
    return {
        "schema_version": LIVENESS_SERIES_SCHEMA,
        "run_receipt_sha256": run_receipt_sha256,
        "samples": samples,
    }


def _measurements(samples: list[dict[str, Any]]) -> tuple[Decimal, Decimal]:
    """tokens/second and joules/token over the WHOLE series -- summed
    numerator over summed denominator, never a per-row average. This is the
    exact arithmetic `r1_e8_validator._liveness_measurements` recomputes;
    any divergence here is a defect in this function, not a rounding choice
    the validator would tolerate."""
    tokens = Decimal(0)
    seconds = Decimal(0)
    joules = Decimal(0)
    for row in samples:
        tokens += Decimal(row["tokens"])
        seconds += Decimal(row["wall_seconds"])
        joules += Decimal(row["proxy_joules"])
    if seconds <= 0 or tokens <= 0:
        raise E8EvidenceProducerError("liveness series sums to nonpositive tokens or wall_seconds")
    return tokens / seconds, joules / tokens


def _load_thresholds(path: Path) -> tuple[dict[str, Decimal], str]:
    doc, raw = _load_json(path, "R1 threshold authority")
    if doc.get("schema_version") != THRESHOLDS_SCHEMA or doc.get("frozen") is not True:
        raise E8EvidenceProducerError("R1 threshold authority is not a recognized frozen document")
    values: dict[str, Decimal] = {}
    for entry in doc.get("entries", []):
        if isinstance(entry, dict) and entry.get("frozen_form") == "number" and isinstance(entry.get("id"), str):
            values[entry["id"]] = _decimal(entry.get("value"), f"threshold {entry.get('id')}")
    for required in ("T-06", "T-08"):
        if required not in values:
            raise E8EvidenceProducerError(f"R1 threshold authority is missing {required}")
    return values, _sha256_bytes(raw)


def _reopen_contract(
    path: Path, *, comparison_id: str, tier1_sha: str, a3_sha: str
) -> dict[str, Any]:
    if not path.is_file():
        raise E8EvidenceProducerMissing(
            "CHARGED_BUDGET_CONTRACT_MISSING: no reviewed ember02-r2-charged-budget-contract-v1 "
            "authority is present; this producer never infers a liveness formula"
        )
    doc, _raw = _load_json(path, "charged-budget contract")
    if not _self_digest_valid(doc):
        raise E8EvidenceProducerError("charged-budget contract self-digest is invalid")
    if set(doc) != CONTRACT_FIELDS or doc.get("schema_version") != CONTRACT_SCHEMA or doc.get("status") != "FROZEN":
        raise E8EvidenceProducerError("charged-budget contract schema is invalid")
    if doc.get("comparison_id") != comparison_id or doc.get("a1_run_sha256") != tier1_sha or doc.get("a3_run_sha256") != a3_sha:
        raise E8EvidenceProducerError("charged-budget contract is not bound to this comparison")
    projected = doc.get("projected_r2_tokens")
    if not isinstance(projected, dict) or set(projected) != {"a1", "a3"}:
        raise E8EvidenceProducerError("charged-budget contract projected_r2_tokens is invalid")
    a1_projected = _decimal(projected["a1"], "charged-budget contract projected a1 tokens")
    a3_projected = _decimal(projected["a3"], "charged-budget contract projected a3 tokens")
    if a1_projected < 0 or a3_projected <= 0:
        raise E8EvidenceProducerError("charged-budget contract projected token counts are invalid")
    return doc


def mint_liveness_receipt(
    packet_root: Path,
    *,
    tier1_run_source: Path,
    a3_run_source: Path,
    charged_budget_contract_source: Path,
    a1_telemetry_path: Path,
    a1_run_id: str,
    a3_telemetry_path: Path,
    a3_run_id: str,
    thresholds_path: Path,
) -> Path:
    """Reopen a Tier-1 A1 run, its matched A3 run, both runs' raw per-step
    telemetry, and an externally frozen charged-budget contract; mint the
    closed `ember02-r1-e8-liveness-v1` packet at
    `packet_root/a1-e8-liveness.json`. Every referenced sibling file is
    copied byte-verified into `packet_root` first, so every `{path,
    sha256}` reference the receipt carries is packet-relative and
    non-traversing, exactly as `r1_e8_validator._reopen_ref` requires.

    Raises `E8EvidenceProducerMissing` (never `E8EvidenceProducerError`) when
    the charged-budget contract is absent -- callers must route that
    exception to an EVIDENCE_MISSING report, not a hard refusal.
    """
    packet_root = Path(packet_root)
    charged_budget_contract_source = Path(charged_budget_contract_source)
    if not charged_budget_contract_source.is_file():
        raise E8EvidenceProducerMissing(
            "CHARGED_BUDGET_CONTRACT_MISSING: no reviewed ember02-r2-charged-budget-contract-v1 "
            "authority is present; this producer never infers a liveness formula"
        )
    thresholds, thresholds_sha256 = _load_thresholds(Path(thresholds_path))
    t08 = thresholds["T-08"]

    tier1_target = packet_root / TIER1_FILENAME
    a3_target = packet_root / A3_FILENAME
    tier1_sha, _ = _copy_verified(Path(tier1_run_source), tier1_target)
    a3_sha, _ = _copy_verified(Path(a3_run_source), a3_target)
    tier1_doc, tier1_sha_reopened = reopen_run_receipt(tier1_target, arm="A1")
    a3_doc, a3_sha_reopened = reopen_run_receipt(a3_target, arm="A3")
    if tier1_sha_reopened != tier1_sha or a3_sha_reopened != a3_sha:
        raise E8EvidenceProducerError("run receipt copy verification hash mismatch")
    if tier1_doc.get("tier") != "TIER1" or tier1_doc.get("optimizer", {}).get("cpu_offload") is not True:
        raise E8EvidenceProducerError("A1 run receipt is not a Tier-1 full-state CPU-offload run")
    if tier1_doc.get("source_commit") != a3_doc.get("source_commit") or tier1_doc.get("identity") != a3_doc.get("identity"):
        raise E8EvidenceProducerError("MATCHED_IDENTITY_MISMATCH: A1 and A3 runs do not share source or identity")

    a1_series = derive_liveness_series(Path(a1_telemetry_path), run_id=a1_run_id, run_receipt_sha256=tier1_sha)
    a3_series = derive_liveness_series(Path(a3_telemetry_path), run_id=a3_run_id, run_receipt_sha256=a3_sha)
    a1_series_bytes = _canonical(a1_series) + b"\n"
    a3_series_bytes = _canonical(a3_series) + b"\n"
    _write_atomic_no_overwrite(packet_root / A1_SERIES_FILENAME, a1_series_bytes)
    _write_atomic_no_overwrite(packet_root / A3_SERIES_FILENAME, a3_series_bytes)
    a1_series_sha = _sha256_bytes(a1_series_bytes)
    a3_series_sha = _sha256_bytes(a3_series_bytes)

    a1_tps, a1_jpt = _measurements(a1_series["samples"])
    a3_tps, a3_jpt = _measurements(a3_series["samples"])

    comparison_id = tier1_doc["identity"]["comparison_id"]
    contract_target = packet_root / CONTRACT_FILENAME
    contract_sha, _ = _copy_verified(charged_budget_contract_source, contract_target)
    contract = _reopen_contract(contract_target, comparison_id=comparison_id, tier1_sha=tier1_sha, a3_sha=a3_sha)
    projected = contract["projected_r2_tokens"]
    a1_projected = Decimal(str(projected["a1"]))
    a3_projected = Decimal(str(projected["a3"]))
    ratio = a1_projected / a3_projected

    measurements = {
        "a1_tokens_per_second": _serial(a1_tps),
        "a1_joules_per_token": _serial(a1_jpt),
        "a3_tokens_per_second": _serial(a3_tps),
        "a3_joules_per_token": _serial(a3_jpt),
        "equal_budget_ratio": _serial(ratio),
    }
    verdict = "TIER1_LIVE" if ratio >= t08 else "FALLBACK_REQUIRED"

    liveness = {
        "schema_version": LIVENESS_SCHEMA,
        "thresholds_sha256": thresholds_sha256,
        "charged_budget_contract": {"path": CONTRACT_FILENAME, "sha256": contract_sha},
        "tier1_run": {"path": TIER1_FILENAME, "sha256": tier1_sha},
        "a3_run": {"path": A3_FILENAME, "sha256": a3_sha},
        "a1_series": {"path": A1_SERIES_FILENAME, "sha256": a1_series_sha},
        "a3_series": {"path": A3_SERIES_FILENAME, "sha256": a3_series_sha},
        "measurements": measurements,
        "verdict": verdict,
    }
    liveness["receipt_sha256"] = _sha256_bytes(_canonical(liveness))
    output = packet_root / LIVENESS_FILENAME
    _write_atomic_no_overwrite(output, _canonical(liveness) + b"\n")
    return output
