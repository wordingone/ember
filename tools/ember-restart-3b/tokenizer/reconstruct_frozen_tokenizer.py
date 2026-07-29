# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reconstruct the frozen serving tokenizer without disclosing token strings."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_JSON_STRING = rb'"(?:\\.|[^"\\])*"'
_VOCAB_LINE = re.compile(rb"^      (" + _JSON_STRING + rb"): ([0-9]+)(,?)\r?\n?$")
_MERGE_BLOCK = re.compile(
    rb"(?m)^      \[\r?\n"
    rb"        (" + _JSON_STRING + rb"),\r?\n"
    rb"        (" + _JSON_STRING + rb")\r?\n"
    rb"      \](,?)\r?\n?"
)
_CANONICAL_BASE_SIZE = 245
_MAX_ORACLE_COMBINATIONS = 1_000_000


class ReconstructionError(RuntimeError):
    """A fail-closed reconstruction refusal with no token-string disclosure."""


class _ObjectPairs(dict):
    def __init__(self, pairs: list[tuple[str, object]]) -> None:
        super().__init__(pairs)
        self.pairs = pairs


@dataclass(frozen=True)
class _Edit:
    start: int
    end: int
    replacement: bytes


@dataclass(frozen=True)
class _Structure:
    vocab_pairs: tuple[tuple[str, int], ...]
    merges: tuple[tuple[str, str], ...]
    vocab_spans: Mapping[int, tuple[int, int]]
    merge_spans: tuple[tuple[tuple[int, int], tuple[int, int]], ...]
    base_size: int


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_string(value: str) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _read_bytes(path: Path, label: str) -> bytes:
    try:
        if path.is_symlink():
            raise ReconstructionError(f"{label} must not be a symlink")
        return path.read_bytes()
    except ReconstructionError:
        raise
    except OSError as exc:
        raise ReconstructionError(f"{label} is unavailable") from exc


def _load_freeze_receipt(path: Path) -> tuple[str, str]:
    raw = _read_bytes(path, "freeze receipt")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReconstructionError("freeze receipt is not strict UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ReconstructionError("freeze receipt must be a JSON object")
    oracle = payload.get("tokenizer_json_sha256")
    if not isinstance(oracle, str) or _SHA256.fullmatch(oracle) is None:
        raise ReconstructionError("freeze receipt tokenizer hash is invalid")
    return oracle, _sha256(raw)


def _decode_string(raw: bytes) -> str:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReconstructionError("tokenizer string encoding is invalid") from exc
    if not isinstance(value, str):
        raise ReconstructionError("tokenizer string token is invalid")
    return value


def _parse_structure(raw: bytes) -> _Structure:
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_ObjectPairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReconstructionError("tokenizer is not strict UTF-8 JSON") from exc
    if not isinstance(document, _ObjectPairs):
        raise ReconstructionError("tokenizer root must be an object")
    model = document.get("model")
    if not isinstance(model, _ObjectPairs):
        raise ReconstructionError("tokenizer model must be an object")
    vocab = model.get("vocab")
    merges = model.get("merges")
    if not isinstance(vocab, _ObjectPairs) or not isinstance(merges, list):
        raise ReconstructionError("tokenizer model lacks vocab or merges")
    vocab_pairs: list[tuple[str, int]] = []
    seen_ids: set[int] = set()
    for token, token_id in vocab.pairs:
        if (
            not isinstance(token, str)
            or not isinstance(token_id, int)
            or isinstance(token_id, bool)
            or token_id < 0
            or token_id in seen_ids
        ):
            raise ReconstructionError("tokenizer vocab IDs are invalid")
        seen_ids.add(token_id)
        vocab_pairs.append((token, token_id))
    if seen_ids != set(range(len(vocab_pairs))):
        raise ReconstructionError("tokenizer vocab IDs are not closed and contiguous")
    merge_pairs: list[tuple[str, str]] = []
    for merge in merges:
        if (
            not isinstance(merge, list)
            or len(merge) != 2
            or not all(isinstance(value, str) for value in merge)
        ):
            raise ReconstructionError("tokenizer merge rows are invalid")
        merge_pairs.append((merge[0], merge[1]))
    base_size = len(vocab_pairs) - len(merge_pairs)
    if base_size != _CANONICAL_BASE_SIZE:
        raise ReconstructionError("tokenizer base-size fingerprint is invalid")

    vocab_marker = raw.find(b'    "vocab": {')
    merges_marker = raw.find(b'    "merges": [')
    if vocab_marker < 0 or merges_marker <= vocab_marker:
        raise ReconstructionError("tokenizer byte layout is unsupported")
    vocab_spans: dict[int, tuple[int, int]] = {}
    vocab_by_id = {candidate_id: token for token, candidate_id in vocab_pairs}
    cursor = vocab_marker
    for line in raw[vocab_marker:merges_marker].splitlines(keepends=True):
        match = _VOCAB_LINE.match(line)
        if match is not None:
            token_id = int(match.group(2))
            if token_id in seen_ids:
                if token_id in vocab_spans:
                    raise ReconstructionError(
                        "tokenizer vocab byte spans are ambiguous"
                    )
                start = cursor + match.start(1)
                end = cursor + match.end(1)
                if _decode_string(raw[start:end]) != vocab_by_id[token_id]:
                    raise ReconstructionError("tokenizer vocab span binding failed")
                vocab_spans[token_id] = (start, end)
        cursor += len(line)
    if set(vocab_spans) != seen_ids:
        raise ReconstructionError("tokenizer vocab byte layout is incomplete")

    merge_spans: list[tuple[tuple[int, int], tuple[int, int]]] = []
    merge_region = raw[merges_marker:]
    for match in _MERGE_BLOCK.finditer(merge_region):
        left_span = (
            merges_marker + match.start(1),
            merges_marker + match.end(1),
        )
        right_span = (
            merges_marker + match.start(2),
            merges_marker + match.end(2),
        )
        merge_spans.append((left_span, right_span))
    if len(merge_spans) != len(merge_pairs):
        raise ReconstructionError("tokenizer merge byte layout is incomplete")
    for rank, ((left_span, right_span), operands) in enumerate(
        zip(merge_spans, merge_pairs)
    ):
        if (
            _decode_string(raw[slice(*left_span)]) != operands[0]
            or _decode_string(raw[slice(*right_span)]) != operands[1]
        ):
            raise ReconstructionError(
                f"tokenizer merge span binding failed at ID {base_size + rank}"
            )
    return _Structure(
        vocab_pairs=tuple(vocab_pairs),
        merges=tuple(merge_pairs),
        vocab_spans=vocab_spans,
        merge_spans=tuple(merge_spans),
        base_size=base_size,
    )


def _duplicate_groups(
    vocab_pairs: Sequence[tuple[str, int]],
) -> tuple[list[list[int]], list[int]]:
    ids_by_token: dict[str, list[int]] = {}
    for token, token_id in vocab_pairs:
        ids_by_token.setdefault(token, []).append(token_id)
    groups = sorted(
        (ids for ids in ids_by_token.values() if len(ids) > 1),
        key=lambda ids: tuple(ids),
    )
    # A normal JSON object parser retains the final duplicate-key occurrence.
    gap_ids = sorted(token_id for ids in groups for token_id in ids[:-1])
    return groups, gap_ids


def _apply_edits(raw: bytes, edits: Iterable[_Edit]) -> bytes:
    ordered = sorted(edits, key=lambda edit: (edit.start, edit.end))
    cursor = 0
    parts: list[bytes] = []
    for edit in ordered:
        if edit.start < cursor or edit.end < edit.start or edit.end > len(raw):
            raise ReconstructionError("reconstruction byte spans overlap")
        parts.append(raw[cursor : edit.start])
        parts.append(edit.replacement)
        cursor = edit.end
    parts.append(raw[cursor:])
    return b"".join(parts)


def _oracle_reconstruct(
    raw: bytes, structure: _Structure, oracle_sha256: str
) -> tuple[bytes, int, int, list[int], list[int], list[int]]:
    observed_by_id = {token_id: token for token, token_id in structure.vocab_pairs}
    ids_by_observed: dict[str, list[int]] = {}
    for token, token_id in structure.vocab_pairs:
        ids_by_observed.setdefault(token, []).append(token_id)

    reference_options: list[tuple[tuple[int, int], ...]] = []
    ambiguous_ranks: list[int] = []
    fixed_references: dict[int, tuple[int, int]] = {}
    for rank, operands in enumerate(structure.merges):
        output_id = structure.base_size + rank
        left_ids = [
            token_id
            for token_id in ids_by_observed.get(operands[0], [])
            if token_id < output_id
        ]
        right_ids = [
            token_id
            for token_id in ids_by_observed.get(operands[1], [])
            if token_id < output_id
        ]
        options = tuple(itertools.product(left_ids, right_ids))
        if not options:
            raise ReconstructionError(
                f"merge operands have no prior-ID binding at ID {output_id}"
            )
        if len(options) == 1:
            fixed_references[rank] = options[0]
        else:
            ambiguous_ranks.append(rank)
            reference_options.append(options)

    combination_count = 1
    for options in reference_options:
        combination_count *= len(options)
    if combination_count > _MAX_ORACLE_COMBINATIONS:
        raise ReconstructionError("oracle search exceeds the finite safety bound")
    selections = itertools.product(*reference_options)
    if not reference_options:
        selections = iter([()])
    for combination_index, selected in enumerate(selections):
        references = dict(fixed_references)
        references.update(zip(ambiguous_ranks, selected))
        true_by_id = {
            token_id: observed_by_id[token_id]
            for token_id in range(structure.base_size)
        }
        true_merges: list[tuple[str, str]] = []
        for rank in range(len(structure.merges)):
            left_id, right_id = references[rank]
            if left_id not in true_by_id or right_id not in true_by_id:
                raise ReconstructionError(
                    f"merge rank references unresolved prior IDs at ID "
                    f"{structure.base_size + rank}"
                )
            operands = (true_by_id[left_id], true_by_id[right_id])
            true_merges.append(operands)
            true_by_id[structure.base_size + rank] = operands[0] + operands[1]

        edits: list[_Edit] = []
        vocab_replacements: list[int] = []
        merge_replacements: list[int] = []
        inconsistency_ids: set[int] = set()
        for token_id, observed in observed_by_id.items():
            if observed == true_by_id[token_id]:
                continue
            span = structure.vocab_spans[token_id]
            edits.append(_Edit(span[0], span[1], _json_string(true_by_id[token_id])))
            vocab_replacements.append(token_id)
            inconsistency_ids.add(token_id)
        for rank, (observed, derived) in enumerate(zip(structure.merges, true_merges)):
            if observed == derived:
                continue
            left_span, right_span = structure.merge_spans[rank]
            edits.extend(
                [
                    _Edit(
                        left_span[0],
                        left_span[1],
                        _json_string(derived[0]),
                    ),
                    _Edit(
                        right_span[0],
                        right_span[1],
                        _json_string(derived[1]),
                    ),
                ]
            )
            token_id = structure.base_size + rank
            merge_replacements.append(token_id)
            inconsistency_ids.add(token_id)
        candidate = _apply_edits(raw, edits)
        if _sha256(candidate) != oracle_sha256:
            continue
        return (
            candidate,
            combination_count,
            combination_index,
            sorted(inconsistency_ids),
            sorted(vocab_replacements),
            sorted(merge_replacements),
        )
    raise ReconstructionError("oracle search found no matching reconstruction")


def _validate_output_location(output: Path) -> Path:
    resolved = output.resolve(strict=False)
    if (
        resolved.parent.name != "cbase-serving"
        or resolved.parent.parent.name != "models"
    ):
        raise ReconstructionError(
            "output must be under the canonical serving directory"
        )
    if output.exists() and output.is_symlink():
        raise ReconstructionError("serving tokenizer output must not be a symlink")
    return resolved


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def reconstruct_frozen_tokenizer(
    *,
    source: Path,
    freeze_receipt: Path,
    output: Path | None = None,
    receipt_output: Path | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    source = Path(source)
    oracle_sha256, freeze_receipt_sha256 = _load_freeze_receipt(Path(freeze_receipt))
    source_raw = _read_bytes(source, "tracked tokenizer source")
    source_sha256 = _sha256(source_raw)
    structure = _parse_structure(source_raw)
    duplicate_groups, gap_ids = _duplicate_groups(structure.vocab_pairs)
    if output is not None:
        output = _validate_output_location(Path(output))
        if source.resolve(strict=False) == output:
            raise ReconstructionError(
                "tracked source and serving output must be distinct"
            )
    if receipt_output is not None:
        receipt_output = Path(receipt_output).resolve(strict=False)
        if (
            receipt_output.parent.name != "cbase-serving"
            or receipt_output.parent.parent.name != "models"
        ):
            raise ReconstructionError(
                "receipt must be under the canonical serving directory"
            )
        forbidden_destinations = {
            source.resolve(strict=False),
            Path(freeze_receipt).resolve(strict=False),
        }
        if output is not None:
            forbidden_destinations.add(output)
        if receipt_output in forbidden_destinations:
            raise ReconstructionError(
                "receipt destination must be distinct from source, oracle, and output"
            )

    output_preexisting = bool(output is not None and output.exists())

    if source_sha256 == oracle_sha256:
        reconstructed = source_raw
        status = "ALREADY_MATCHED"
        combination_count = 1
        combination_index = 0
        inconsistency_ids: list[int] = []
        vocab_replacement_ids: list[int] = []
        merge_replacement_ids: list[int] = []
    else:
        (
            reconstructed,
            combination_count,
            combination_index,
            inconsistency_ids,
            vocab_replacement_ids,
            merge_replacement_ids,
        ) = _oracle_reconstruct(source_raw, structure, oracle_sha256)
        status = "RECONSTRUCTED"
    output_sha256 = _sha256(reconstructed)
    if output_sha256 != oracle_sha256:
        raise ReconstructionError("reconstructed tokenizer does not match oracle")

    receipt: dict[str, object] = {
        "schema_version": "ember-tokenizer-reconstruction-v1",
        "status": status,
        "source_sha256": source_sha256,
        "source_byte_count": len(source_raw),
        "freeze_receipt_sha256": freeze_receipt_sha256,
        "oracle_sha256": oracle_sha256,
        "output_sha256": output_sha256,
        "output_byte_count": len(reconstructed),
        "base_size": structure.base_size,
        "vocab_entry_count": len(structure.vocab_pairs),
        "merge_count": len(structure.merges),
        "duplicate_groups": duplicate_groups,
        "gap_ids": gap_ids,
        "inconsistency_ids": inconsistency_ids,
        "vocab_replacement_ids": vocab_replacement_ids,
        "merge_replacement_ids": merge_replacement_ids,
        "oracle_combination_count": combination_count,
        "combination_index": combination_index,
        "dry_run": bool(dry_run),
        "write_performed": not dry_run and not output_preexisting,
        "verifier_sha256": _sha256(Path(__file__).read_bytes()),
    }
    receipt_bytes = (
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if dry_run:
        return receipt
    if output is None or receipt_output is None:
        raise ReconstructionError(
            "non-dry reconstruction requires output and receipt destinations"
        )
    if output.exists():
        actual = _sha256(_read_bytes(output, "serving tokenizer output"))
        if actual != oracle_sha256:
            raise ReconstructionError(
                f"serving tokenizer hash mismatch actual={actual} expected={oracle_sha256}"
            )
    else:
        _atomic_write(output, reconstructed)
    if _sha256(_read_bytes(output, "serving tokenizer output")) != oracle_sha256:
        raise ReconstructionError("serving tokenizer changed after publication")
    _atomic_write(receipt_output, receipt_bytes)
    return receipt


def ensure_serving_tokenizer(
    *,
    output: Path,
    source: Path,
    freeze_receipt: Path,
    receipt_output: Path,
    expected_freeze_receipt_sha256: str | None = None,
) -> Path:
    output = _validate_output_location(Path(output))
    oracle_sha256, freeze_sha256 = _load_freeze_receipt(Path(freeze_receipt))
    if (
        expected_freeze_receipt_sha256 is not None
        and freeze_sha256 != expected_freeze_receipt_sha256
    ):
        raise ReconstructionError(
            f"freeze receipt hash mismatch actual={freeze_sha256} "
            f"expected={expected_freeze_receipt_sha256}"
        )
    if output.exists():
        actual = _sha256(_read_bytes(output, "serving tokenizer output"))
        if actual != oracle_sha256:
            raise ReconstructionError(
                f"serving tokenizer hash mismatch actual={actual} expected={oracle_sha256}"
            )
        return output
    reconstruct_frozen_tokenizer(
        source=Path(source),
        freeze_receipt=Path(freeze_receipt),
        output=output,
        receipt_output=Path(receipt_output),
    )
    actual = _sha256(_read_bytes(output, "serving tokenizer output"))
    if actual != oracle_sha256:
        raise ReconstructionError(
            f"serving tokenizer hash mismatch actual={actual} expected={oracle_sha256}"
        )
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--freeze-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--receipt-output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    receipt = reconstruct_frozen_tokenizer(
        source=args.source,
        freeze_receipt=args.freeze_receipt,
        output=args.output,
        receipt_output=args.receipt_output,
        dry_run=args.dry_run,
    )
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
