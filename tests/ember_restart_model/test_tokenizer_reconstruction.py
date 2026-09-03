# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed reconstruction tests for the serving tokenizer."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools" / "ember-restart-3b") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))
from repository_layout import resolve_repository_authority  # noqa: E402
RESTART_TOOLS = ROOT / "tools" / "ember-restart-3b"
if str(RESTART_TOOLS) not in sys.path:
    sys.path.insert(0, str(RESTART_TOOLS))

from tokenizer.reconstruct_frozen_tokenizer import (
    ReconstructionError,
    ensure_serving_tokenizer,
    main,
    reconstruct_frozen_tokenizer,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _render_tokenizer(
    vocab_pairs: list[tuple[str, int]], merges: list[list[str]]
) -> bytes:
    lines = [
        "{",
        '  "version": "1.0",',
        '  "model": {',
        '    "type": "BPE",',
        '    "vocab": {',
    ]
    for index, (token, token_id) in enumerate(vocab_pairs):
        comma = "," if index + 1 < len(vocab_pairs) else ""
        lines.append(
            f"      {json.dumps(token, ensure_ascii=False)}: {token_id}{comma}"
        )
    lines.extend(
        [
            "    },",
            '    "merges": [',
        ]
    )
    for index, (left, right) in enumerate(merges):
        comma = "," if index + 1 < len(merges) else ""
        lines.extend(
            [
                "      [",
                f"        {json.dumps(left, ensure_ascii=False)},",
                f"        {json.dumps(right, ensure_ascii=False)}",
                f"      ]{comma}",
            ]
        )
    lines.extend(["    ]", "  }", "}", ""])
    return "\n".join(lines).encode("utf-8")


def _fixture() -> tuple[bytes, bytes, list[list[int]]]:
    base = [chr(0x1000 + index) for index in range(245)]
    oracle_pairs = [(token, token_id) for token_id, token in enumerate(base)]
    oracle_pairs.extend(
        [
            (base[0] + base[1], 245),
            (base[0] + base[1] + base[2], 246),
        ]
    )
    oracle = _render_tokenizer(
        oracle_pairs,
        [
            [base[0], base[1]],
            [base[0] + base[1], base[2]],
        ],
    )
    redacted_pairs = [(token, token_id) for token_id, token in enumerate(base)]
    redacted_pairs.extend(
        [
            (base[6], 245),
            (base[0] + base[1] + base[2], 246),
        ]
    )
    redacted = _render_tokenizer(
        redacted_pairs,
        [
            [base[0], base[1]],
            [base[6], base[2]],
        ],
    )
    return redacted, oracle, [[6, 245]]


def _write_freeze(path: Path, oracle: bytes) -> None:
    path.write_text(
        json.dumps(
            {
                "ticket": "TOKENIZER-FREEZE-V0",
                "tokenizer_json_sha256": _sha256(oracle),
            }
        ),
        encoding="utf-8",
    )


def _canonical_paths(tmp_path: Path) -> tuple[Path, Path]:
    output = tmp_path / "models" / "cbase-serving" / "tokenizer.json"
    receipt = (
        tmp_path / "models" / "cbase-serving" / "tokenizer-reconstruction-receipt.json"
    )
    return output, receipt


def test_reconstructs_duplicate_preserving_vocab_and_merge_ambiguity(
    tmp_path: Path,
) -> None:
    redacted, oracle, duplicate_groups = _fixture()
    source = tmp_path / "tracked-redacted-tokenizer.json"
    freeze = tmp_path / "freeze.json"
    output, receipt_path = _canonical_paths(tmp_path)
    source.write_bytes(redacted)
    _write_freeze(freeze, oracle)

    receipt = reconstruct_frozen_tokenizer(
        source=source,
        freeze_receipt=freeze,
        output=output,
        receipt_output=receipt_path,
    )

    assert output.read_bytes() == oracle
    assert (
        _sha256(output.read_bytes())
        == json.loads(freeze.read_text(encoding="utf-8"))["tokenizer_json_sha256"]
    )
    assert receipt == json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "RECONSTRUCTED"
    assert receipt["base_size"] == 245
    assert receipt["vocab_entry_count"] == 247
    assert receipt["merge_count"] == 2
    assert receipt["duplicate_groups"] == duplicate_groups
    assert receipt["gap_ids"] == [6]
    assert receipt["inconsistency_ids"] == [245, 246]
    assert receipt["vocab_replacement_ids"] == [245]
    assert receipt["merge_replacement_ids"] == [246]
    assert receipt["oracle_combination_count"] == 2
    assert isinstance(receipt["combination_index"], int)
    assert receipt["write_performed"] is True
    assert receipt["dry_run"] is False


def test_dry_run_enumerates_without_writing(tmp_path: Path) -> None:
    redacted, oracle, _duplicate_groups = _fixture()
    source = tmp_path / "tracked-redacted-tokenizer.json"
    freeze = tmp_path / "freeze.json"
    output, receipt_path = _canonical_paths(tmp_path)
    source.write_bytes(redacted)
    _write_freeze(freeze, oracle)

    receipt = reconstruct_frozen_tokenizer(
        source=source,
        freeze_receipt=freeze,
        output=output,
        receipt_output=receipt_path,
        dry_run=True,
    )

    assert receipt["status"] == "RECONSTRUCTED"
    assert receipt["dry_run"] is True
    assert receipt["write_performed"] is False
    assert not output.exists()
    assert not receipt_path.exists()


def test_existing_mismatch_fails_closed_without_rewrite(tmp_path: Path) -> None:
    redacted, oracle, _duplicate_groups = _fixture()
    source = tmp_path / "tracked-redacted-tokenizer.json"
    freeze = tmp_path / "freeze.json"
    output, receipt_path = _canonical_paths(tmp_path)
    source.write_bytes(redacted)
    _write_freeze(freeze, oracle)
    output.parent.mkdir(parents=True)
    existing = b"mismatch"
    output.write_bytes(existing)

    with pytest.raises(ReconstructionError) as caught:
        ensure_serving_tokenizer(
            output=output,
            source=source,
            freeze_receipt=freeze,
            receipt_output=receipt_path,
        )

    assert output.read_bytes() == existing
    assert _sha256(existing) in str(caught.value)
    assert _sha256(oracle) in str(caught.value)
    assert not receipt_path.exists()


def test_absent_serving_tokenizer_is_created_and_reverified(tmp_path: Path) -> None:
    _redacted, oracle, _duplicate_groups = _fixture()
    source = tmp_path / "tracked-tokenizer.json"
    freeze = tmp_path / "freeze.json"
    output, receipt_path = _canonical_paths(tmp_path)
    source.write_bytes(oracle)
    _write_freeze(freeze, oracle)

    verified = ensure_serving_tokenizer(
        output=output,
        source=source,
        freeze_receipt=freeze,
        receipt_output=receipt_path,
    )

    assert verified == output
    assert output.read_bytes() == oracle
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "ALREADY_MATCHED"
    assert receipt["output_sha256"] == _sha256(oracle)


def test_serving_preflight_refuses_unpinned_freeze_receipt(
    tmp_path: Path,
) -> None:
    _redacted, oracle, _duplicate_groups = _fixture()
    source = tmp_path / "tracked-tokenizer.json"
    freeze = tmp_path / "freeze.json"
    output, receipt_path = _canonical_paths(tmp_path)
    source.write_bytes(oracle)
    _write_freeze(freeze, oracle)

    with pytest.raises(ReconstructionError, match="freeze receipt hash mismatch"):
        ensure_serving_tokenizer(
            output=output,
            source=source,
            freeze_receipt=freeze,
            receipt_output=receipt_path,
            expected_freeze_receipt_sha256="0" * 64,
        )

    assert not output.exists()
    assert not receipt_path.exists()


def test_idempotent_existing_oracle_does_not_claim_tokenizer_write(
    tmp_path: Path,
) -> None:
    _redacted, oracle, _duplicate_groups = _fixture()
    source = tmp_path / "tracked-tokenizer.json"
    freeze = tmp_path / "freeze.json"
    output, receipt_path = _canonical_paths(tmp_path)
    source.write_bytes(oracle)
    _write_freeze(freeze, oracle)
    output.parent.mkdir(parents=True)
    output.write_bytes(oracle)

    receipt = reconstruct_frozen_tokenizer(
        source=source,
        freeze_receipt=freeze,
        output=output,
        receipt_output=receipt_path,
    )

    assert receipt["status"] == "ALREADY_MATCHED"
    assert receipt["write_performed"] is False
    assert output.read_bytes() == oracle


def test_receipt_destination_cannot_alias_authority_or_output(
    tmp_path: Path,
) -> None:
    _redacted, oracle, _duplicate_groups = _fixture()
    source = tmp_path / "tracked-tokenizer.json"
    freeze = tmp_path / "freeze.json"
    output, _receipt_path = _canonical_paths(tmp_path)
    source.write_bytes(oracle)
    _write_freeze(freeze, oracle)
    output.parent.mkdir(parents=True)

    with pytest.raises(ReconstructionError, match="must be distinct"):
        reconstruct_frozen_tokenizer(
            source=source,
            freeze_receipt=freeze,
            output=output,
            receipt_output=output,
        )
    assert not output.exists()


@pytest.mark.parametrize(
    "output_builder",
    [
        lambda root: root / "tokenizer.json",
        lambda root: root / "models" / "other" / "tokenizer.json",
    ],
)
def test_output_must_be_under_models_cbase_serving(
    tmp_path: Path, output_builder
) -> None:
    _redacted, oracle, _duplicate_groups = _fixture()
    source = tmp_path / "tracked-tokenizer.json"
    freeze = tmp_path / "freeze.json"
    source.write_bytes(oracle)
    _write_freeze(freeze, oracle)
    output = output_builder(tmp_path)

    with pytest.raises(ReconstructionError, match="canonical serving directory"):
        reconstruct_frozen_tokenizer(
            source=source,
            freeze_receipt=freeze,
            output=output,
            receipt_output=output.parent / "receipt.json",
        )
    assert not output.exists()


def test_source_cannot_be_the_serving_output(tmp_path: Path) -> None:
    _redacted, oracle, _duplicate_groups = _fixture()
    output, receipt_path = _canonical_paths(tmp_path)
    freeze = tmp_path / "freeze.json"
    output.parent.mkdir(parents=True)
    output.write_bytes(oracle)
    _write_freeze(freeze, oracle)
    with pytest.raises(ReconstructionError, match="distinct"):
        reconstruct_frozen_tokenizer(
            source=output,
            freeze_receipt=freeze,
            output=output,
            receipt_output=receipt_path,
        )


def test_cli_prints_ids_and_hashes_only(tmp_path: Path, capsys) -> None:
    redacted, oracle, duplicate_groups = _fixture()
    source = tmp_path / "tracked-redacted-tokenizer.json"
    freeze = tmp_path / "freeze.json"
    output, receipt_path = _canonical_paths(tmp_path)
    source.write_bytes(redacted)
    _write_freeze(freeze, oracle)

    assert (
        main(
            [
                "--source",
                str(source),
                "--freeze-receipt",
                str(freeze),
                "--output",
                str(output),
                "--receipt-output",
                str(receipt_path),
                "--dry-run",
            ]
        )
        == 0
    )
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["duplicate_groups"] == duplicate_groups
    assert payload["gap_ids"] == [6]
    for token_id in range(247):
        token = chr(0x1000 + token_id)
        assert token not in stdout


def test_current_public_tokenizer_dry_run_is_oracle_bound() -> None:
    source = resolve_repository_authority(ROOT, "tokenizer").path
    freeze = ROOT / "receipts" / "tokenizer-freeze-20260611T154111Z.json"
    receipt = reconstruct_frozen_tokenizer(
        source=source,
        freeze_receipt=freeze,
        dry_run=True,
    )
    assert receipt["status"] == "ALREADY_MATCHED"
    assert receipt["base_size"] == 245
    assert receipt["vocab_entry_count"] == 32_000
    assert receipt["merge_count"] == 31_755
    assert receipt["duplicate_groups"] == []
    assert receipt["gap_ids"] == []
    assert receipt["output_sha256"] == receipt["oracle_sha256"]
