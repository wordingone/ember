# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Frozen positives and reds for the #1947 G1/G2 content guards (spec v6, 9169818b).

Fixture-only: these prove guard behaviour, not production coverage (rule 13 real-sample leg is separate).
"""

from __future__ import annotations

import hashlib
import json
import sys
import types
import unicodedata
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import issue1947_protected_content_guard as g1  # noqa: E402
import issue1947_shortcut_guard as g2  # noqa: E402

GOLD = "The mitochondria is the powerhouse of the cell and makes ATP for all tissues"
HEXGOLD = "c0ffee" * 10 + "beef"  # a protected value that is itself 64-hex


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


FAKE_DETECTOR = (
    "import unicodedata\n"
    f"POLICY_SHA256 = {g1.POLICY_V2_SHA256!r}\n"
    "def normalize_n1(text):\n    return unicodedata.normalize('NFC', text)\n"
    "def normalize_n2(text):\n    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())\n"
)


def _detector(tmp_path, source=FAKE_DETECTOR):
    p = tmp_path / "policy_v2_detector.py"
    p.write_text(source)
    return p, _sha(p.read_bytes())


@pytest.fixture()
def normalizer(tmp_path):
    # Test stand-in for the reviewed detector source; the guard pins it by raw bytes like the real one.
    p, pin = _detector(tmp_path)
    return g1.load_normalizer(p, pin)


@pytest.fixture()
def index(normalizer):
    return g1.ProtectedIndex([{"text": GOLD}, {"text": "B"}, {"text": HEXGOLD}], normalizer)


def _refuses(prefix, fn, *a, **k):
    with pytest.raises((g1.ProtectedContentRefusal, g2.ShortcutRefusal)) as exc:
        fn(*a, **k)
    assert str(exc.value).startswith(prefix), str(exc.value)


# ---- raw-pin loader (G-F1, V5-G-F1-ED99) ----

def _pinned(tmp_path, body):
    p = tmp_path / "a.json"
    p.write_bytes(json.dumps(body).encode())
    return p, _sha(p.read_bytes())


def test_raw_pin_exact_load(tmp_path):
    p, pin = _pinned(tmp_path, {"schema_version": 1, "x": 1})
    assert g1.load_raw_pinned(p, pin, "ed99")["x"] == 1


def test_raw_pin_byte_flip_refuses(tmp_path):
    p, pin = _pinned(tmp_path, {"schema_version": 1, "x": 1})
    p.write_bytes(p.read_bytes().replace(b"1}", b"2}"))
    _refuses("PROTECTED_SET_UNAVAILABLE:ed99:pin_mismatch", g1.load_raw_pinned, p, pin, "ed99")


def test_raw_pin_wrong_schema_refuses(tmp_path):
    p, pin = _pinned(tmp_path, {"schema_version": 2})
    _refuses("PROTECTED_SET_UNAVAILABLE:ed99:schema", g1.load_raw_pinned, p, pin, "ed99")


def test_raw_pin_missing_file_refuses(tmp_path):
    _refuses("PROTECTED_SET_UNAVAILABLE:u:unreadable", g1.load_raw_pinned, tmp_path / "no", "0" * 64, "u")


def test_raw_pin_malformed_pin_refuses(tmp_path):
    p, pin = _pinned(tmp_path, {"schema_version": 1})
    _refuses("PIN_MALFORMED", g1.load_raw_pinned, p, pin[:63], "u")


def test_receipt_self_hash_negative(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"schema_version": 1, "self_sha256": "0" * 64}))
    _refuses("PROTECTED_SET_UNAVAILABLE:r:self_hash", g1.load_self_hashed, p, "r")


def test_normalizer_unavailable(tmp_path):
    _refuses("NORMALIZER_UNAVAILABLE", g1.load_normalizer, tmp_path / "absent.py", "0" * 64)


def test_normalizer_pin_mismatch(tmp_path):
    p, pin = _detector(tmp_path)
    p.write_text(FAKE_DETECTOR + "# edited\n")
    _refuses("NORMALIZER_PIN_MISMATCH", g1.load_normalizer, p, pin)


def test_normalizer_policy_mismatch(tmp_path):
    p, pin = _detector(tmp_path, FAKE_DETECTOR.replace(g1.POLICY_V2_SHA256, "0" * 64))
    _refuses("NORMALIZER_POLICY_MISMATCH", g1.load_normalizer, p, pin)


# ---- coverage ----

def _rec(k, **over):
    rec = {"member": "mmmu", "record_id": f"r{k:04d}", "role": "question", "field": "text",
           "text": f"protected record number {k:04d} body text", "media_sha256": f"{k:064x}"}
    rec.update(over)
    return rec


def _counted_index(normalizer, n, **over):
    return g1.ProtectedIndex([_rec(k, **over) for k in range(n)], normalizer)


def test_complete_claim_with_unresolved_member_refuses(normalizer):
    idx = _counted_index(normalizer, 899)
    _refuses("PROTECTED_UNIVERSE_INCOMPLETE:mmmu:records", g1.check_bundle, {}, index=idx,
             contracts={"coverage_expected": {"mmmu:records": 900}}, claim="COMPLETE")


def test_complete_claim_with_full_index_accepted(normalizer):
    idx = _counted_index(normalizer, 900)
    out = g1.check_bundle({}, index=idx, contracts={"coverage_expected": {"mmmu:records": 900}}, claim="COMPLETE")
    assert out["coverage"] == "COMPLETE"


def test_incomplete_staging_accepted_and_lists_member(normalizer):
    idx = _counted_index(normalizer, 899)
    out = g1.check_bundle({}, index=idx, contracts={"coverage_expected": {"mmmu:records": 900}}, claim="INCOMPLETE")
    assert out["coverage"] == "INCOMPLETE" and out["unresolved"] == ["mmmu:records:899!=900"]


def test_digest_equal_but_field_skipped_incomplete(normalizer):
    idx = _counted_index(normalizer, 900)
    assert g1.coverage_status(idx, {"coverage_expected": {"mmmu:records": 900, "mmmu:field:explanation:text": 412}})[0] == "INCOMPLETE"


def test_declared_coverage_field_is_not_trusted(normalizer):
    # G1-COVERAGE-BINDING red: an index receipt that DECLARES full coverage but holds 1 record.
    idx = _counted_index(normalizer, 1)
    idx.coverage_observed = {"mmmu:records": 900}  # a producer-declared field the guard must ignore
    _refuses("PROTECTED_UNIVERSE_INCOMPLETE:mmmu:records", g1.check_bundle, {}, index=idx,
             contracts={"coverage_expected": {"mmmu:records": 900}}, claim="COMPLETE")


def test_normalizer_executes_hashed_bytes_not_a_reread(tmp_path, monkeypatch):
    # G1-NORMALIZER-BYTES red: the file is swapped after it was read and hashed. The guard must run
    # the hashed bytes; a reload from the path would run the swapped source.
    p, pin = _detector(tmp_path)
    swapped = FAKE_DETECTOR.replace("casefold()", "upper()")
    real_read = Path.read_bytes

    def read_then_swap(self):
        data = real_read(self)
        if self == p:
            p.write_text(swapped)
        return data

    monkeypatch.setattr(Path, "read_bytes", read_then_swap)
    n = g1.load_normalizer(p, pin)
    assert n.n2("ABC") == "abc"


# ---- G1 matching ----

def _item(**over):
    item = {"item_id": "i0", "gold_item_sha256": "a" * 64, "prediction": "x", "score": 1.0}
    item.update(over)
    return item


def test_p1_clean_row(index):
    item = _item()
    g1.scan({"rows": [{"items": [item]}]}, index, validated_items={id(item)})


def test_p4_23_char_fragment_not_caught(index):
    g1.scan({"note": "see " + GOLD.casefold()[10:33] + " here"}, index)


@pytest.mark.parametrize("start", [0, 25, len(GOLD) - 24])
def test_24_char_window_caught_start_middle_end(index, start):
    _refuses("PROTECTED_CONTENT_EMBEDDED:bundle.note", g1.scan, {"note": "x " + GOLD[start:start + 24] + " y"}, index)


def test_exact_text(index):
    _refuses("PROTECTED_CONTENT_EXACT:bundle.rows[0].text", g1.scan, {"rows": [{"text": GOLD}]}, index)


def test_normalized_text(index):
    _refuses("PROTECTED_CONTENT_NORMALIZED:bundle.note", g1.scan, {"note": "  " + GOLD.upper()}, index)


def test_dict_key(index):
    _refuses("PROTECTED_CONTENT_EXACT:bundle", g1.scan, {GOLD: 1}, index)


def test_novel_key(index):
    _refuses("PROTECTED_CONTENT_EXACT:bundle.zq_note_7f", g1.scan, {"zq_note_7f": GOLD}, index)


def test_unbound_prediction_refuses(index):
    item = _item(prediction=GOLD)
    _refuses("PROTECTED_CONTENT_EXACT", g1.scan, {"items": [item]}, index, validated_items={id(item)})


def test_mismatched_bound_prediction_refuses(index):
    item = _item(prediction=GOLD)
    _refuses("PROTECTED_CONTENT_EXACT", g1.scan, {"items": [item]}, index,
             validated_items={id(item)}, producer_predictions={"i0": "0" * 64})


def test_p3_bound_prediction_equal_to_gold_accepted(index):
    item = _item(prediction="B")
    g1.scan({"items": [item]}, index, validated_items={id(item)},
            producer_predictions={"i0": _sha(b"B")})


# ---- G2 ----

def _row(preds, golds, scores=None):
    scores = scores or [1.0] * len(preds)
    return {"row_id": "R", "items": [
        {"item_id": f"i{k}", "gold_item_sha256": g, "prediction": p, "score": s}
        for k, (p, g, s) in enumerate(zip(preds, golds, scores))]}


def test_s1_constant_prediction_refuses():
    _refuses("CONSTANT_PREDICTION:R:10", g2.check_shortcuts,
             _row(["A"] * 10, ["a" * 64] * 5 + ["b" * 64] * 5), replay=None, model_row=False)


def test_p2_all_golds_identical_accepted():
    g2.check_shortcuts(_row(["A"] * 4, ["a" * 64] * 4), replay=None, model_row=False)


def test_p3_skewed_correct_is_flag_only():
    out = g2.check_shortcuts(_row(["A"] * 19 + ["B"], ["a" * 64] * 19 + ["b" * 64]), replay=None, model_row=False)
    assert out["flags"]["D1_near_constant_share"] == 0.95


def test_p5_model_row_without_replay_unproven():
    out = g2.check_shortcuts(_row(["A", "B"], ["a" * 64, "b" * 64]), replay=None, model_row=True)
    assert out["order_invariance"] == "ORDER_INVARIANCE_UNPROVEN"


def test_p4_paired_replay_keyed_passes():
    row = _row(["A", "B"], ["a" * 64, "b" * 64], [1.0, 0.0])
    out = g2.check_shortcuts(row, replay=(row["items"], list(reversed(row["items"]))), model_row=False)
    assert out["order_invariance"] == "ORDER_INVARIANCE_PROVEN_CAPTURED"


def test_order_dependent_prediction_refuses():
    row = _row(["A", "B"], ["a" * 64, "b" * 64])
    moved = [dict(row["items"][0], prediction="B"), row["items"][1]]
    _refuses("ORDER_DEPENDENT_PREDICTION:R:i0", g2.check_shortcuts, row, replay=(row["items"], moved), model_row=False)


def test_score_only_positional_mutant_refuses():
    row = _row(["A", "B"], ["a" * 64, "b" * 64], [1.0, 0.0])
    # predictions stay keyed, scores follow position
    permuted = [dict(row["items"][1], score=1.0), dict(row["items"][0], score=0.0)]
    _refuses("ORDER_DEPENDENT_PREDICTION:R:i", g2.check_shortcuts, row, replay=(row["items"], permuted), model_row=False)


def test_replay_itemset_mismatch():
    row = _row(["A", "B"], ["a" * 64, "b" * 64])
    _refuses("REPLAY_ITEMSET_MISMATCH:R", g2.check_shortcuts, row, replay=(row["items"], row["items"][:1]), model_row=False)


# ---- origin (G-F2 / V4-G-F2-ORIGIN) ----

def _origin_files(tmp_path, monkeypatch, approve: bool):
    contract = {"producer_contracts_sha256": g2.PRODUCER_CONTRACTS_SHA256}
    body = {"schema_version": 1, "preds": {"i0": "A"}}
    receipt = dict(body, self_sha256=_sha(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()))
    c, r = tmp_path / "c.json", tmp_path / "r.json"
    c.write_text(json.dumps(contract))
    r.write_text(json.dumps(receipt))
    monkeypatch.setattr(g2, "ALLOWED_ORIGIN_PATHS", frozenset({c.as_posix(), r.as_posix()}))
    if approve:
        monkeypatch.setattr(g2, "APPROVED_ROW_CONTRACTS", frozenset({_sha(c.read_bytes())}))
        monkeypatch.setattr(g2, "APPROVED_PRODUCER_RECEIPTS", frozenset({_sha(r.read_bytes())}))
    return {"row_contract_path": str(c), "producer_receipt_path": str(r)}, r


def _derive(contract, receipt):
    return {"i0": ("a" * 64, receipt["preds"]["i0"])}


def test_origin_approved_passes(tmp_path, monkeypatch):
    sidecar, _ = _origin_files(tmp_path, monkeypatch, approve=True)
    g2.verify_origin(_row(["A"], ["a" * 64]), sidecar, _derive)


def test_origin_fully_rehashed_forgery_refuses(tmp_path, monkeypatch):
    sidecar, _ = _origin_files(tmp_path, monkeypatch, approve=False)
    _refuses("ORIGIN_UNAPPROVED:row_contract", g2.verify_origin, _row(["A"], ["a" * 64]), sidecar, _derive)


def test_origin_approved_contract_forged_receipt_refuses(tmp_path, monkeypatch):
    sidecar, r = _origin_files(tmp_path, monkeypatch, approve=True)
    body = {"schema_version": 1, "preds": {"i0": "B"}}
    r.write_text(json.dumps(dict(body, self_sha256=_sha(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()))))
    _refuses("ORIGIN_UNAPPROVED:producer_receipt", g2.verify_origin, _row(["B"], ["a" * 64]), sidecar, _derive)


def test_origin_path_outside_allowlist(tmp_path, monkeypatch):
    sidecar, _ = _origin_files(tmp_path, monkeypatch, approve=True)
    monkeypatch.setattr(g2, "ALLOWED_ORIGIN_PATHS", frozenset())
    _refuses("ORIGIN_PATH_NOT_ALLOWED", g2.verify_origin, _row(["A"], ["a" * 64]), sidecar, _derive)


def test_origin_gold_swapped_refuses(tmp_path, monkeypatch):
    sidecar, _ = _origin_files(tmp_path, monkeypatch, approve=True)
    _refuses("ORIGIN_ITEM_MISMATCH:R:i0", g2.verify_origin, _row(["A"], ["b" * 64]), sidecar, _derive)


# ---- typed-hash exemption is not blanket (R-G1-i/j/k) ----

def test_protected_hex_under_novel_key_refuses(index):
    _refuses("PROTECTED_CONTENT_EXACT:bundle.zq", g1.scan, {"zq": HEXGOLD}, index)


def test_fake_hash_role_unvalidated_item_refuses(index):
    item = _item(gold_item_sha256=HEXGOLD)
    _refuses("PROTECTED_CONTENT_EXACT", g1.scan, {"items": [item]}, index)  # not admitted by validate_row


def test_nested_hash_role_refuses(index):
    item = _item(meta={"gold_item_sha256": HEXGOLD})
    _refuses("PROTECTED_CONTENT_EXACT", g1.scan, {"items": [item]}, index, validated_items={id(item)})


def test_p2_validated_typed_hash_accepted(index):
    item = _item(gold_item_sha256=HEXGOLD)
    g1.scan({"items": [item]}, index, validated_items={id(item)})


# ---- G2 replay/row binding and exact paths (Vera report df6d27bc) ----

def test_replay_pair_agreeing_but_not_the_reviewed_row_refuses():
    row = _row(["A", "B"], ["a" * 64, "b" * 64], [1.0, 0.0])
    other = _row(["B", "A"], ["a" * 64, "b" * 64], [0.0, 1.0])["items"]
    _refuses("REPLAY_NOT_THE_REVIEWED_ROW:R:i0", g2.check_shortcuts, row,
             replay=(other, list(reversed(other))), model_row=False)


def test_duplicate_item_ids_in_row_refuse():
    row = _row(["A", "B"], ["a" * 64, "b" * 64])
    row["items"][1]["item_id"] = "i0"
    _refuses("DUPLICATE_ITEM_ID:R:i0", g2.check_shortcuts, row, replay=None, model_row=False)


def test_duplicate_item_ids_in_replay_refuse():
    row = _row(["A", "B"], ["a" * 64, "b" * 64])
    dup = [row["items"][0], dict(row["items"][1], item_id="i0")]
    _refuses("DUPLICATE_ITEM_ID:R:i0", g2.check_shortcuts, row, replay=(row["items"], dup), model_row=False)


def test_duplicate_item_ids_in_origin_row_refuse(tmp_path, monkeypatch):
    sidecar, _ = _origin_files(tmp_path, monkeypatch, approve=True)
    row = _row(["A", "A"], ["a" * 64, "a" * 64])
    row["items"][1]["item_id"] = "i0"
    _refuses("DUPLICATE_ITEM_ID:R:i0", g2.verify_origin, row, sidecar, _derive)


def test_origin_sibling_file_in_same_directory_refuses(tmp_path, monkeypatch):
    # G2-EXACT-PATHS red: an approved-bytes copy beside the approved file is still not an allowed path.
    sidecar, _ = _origin_files(tmp_path, monkeypatch, approve=True)
    sib = tmp_path / "c_copy.json"
    sib.write_bytes(Path(sidecar["row_contract_path"]).read_bytes())
    _refuses("ORIGIN_PATH_NOT_ALLOWED:row_contract", g2.verify_origin, _row(["A"], ["a" * 64]),
             dict(sidecar, row_contract_path=str(sib)), _derive)


# ---- coverage counts bound identities with content, never caller tags (Vera report ce6fbbf6) ----

FULL = {"mmmu:records": 900, "mmmu:field:question:text": 900, "mmmu:media": 900}


def test_bound_full_universe_complete(normalizer):
    assert g1.coverage_status(_counted_index(normalizer, 900), {"coverage_expected": FULL}) == ("COMPLETE", [])


def test_tag_only_contentless_record_cannot_claim_900(normalizer):
    idx = g1.ProtectedIndex([{"coverage_keys": ["mmmu:records"] * 900}], normalizer)
    _refuses("PROTECTED_UNIVERSE_INCOMPLETE", g1.check_bundle, {}, index=idx, contracts={"coverage_expected": FULL}, claim="COMPLETE")


def test_duplicate_identity_counts_once(normalizer):
    idx = g1.ProtectedIndex([_rec(0)] * 900, normalizer)
    status, missing = g1.coverage_status(idx, {"coverage_expected": FULL})
    assert status == "INCOMPLETE" and "mmmu:records:1!=900" in missing


@pytest.mark.parametrize("over", [{"text": ""}, {"record_id": ""}, {"role": None}, {"field": ""}, {"member": ""}],
                         ids=["missing_content", "missing_id", "missing_role", "missing_field", "missing_member"])
def test_unbound_record_blocks_complete(normalizer, over):
    recs = [_rec(k) for k in range(900)]
    recs[7] = _rec(7, **over)
    status, missing = g1.coverage_status(g1.ProtectedIndex(recs, normalizer), {"coverage_expected": FULL})
    assert status == "INCOMPLETE" and "unbound_records:1" in missing


def test_missing_media_blocks_complete(normalizer):
    recs = [_rec(k) for k in range(900)]
    recs[3] = _rec(3, media_sha256=None)
    status, missing = g1.coverage_status(g1.ProtectedIndex(recs, normalizer), {"coverage_expected": FULL})
    assert status == "INCOMPLETE" and "mmmu:media:899!=900" in missing


def test_incomplete_staging_with_unbound_records_stays_lawful(normalizer):
    idx = g1.ProtectedIndex([{"coverage_keys": ["mmmu:records"] * 900}], normalizer)
    out = g1.check_bundle({}, index=idx, contracts={"coverage_expected": FULL}, claim="INCOMPLETE")
    assert out["coverage"] == "INCOMPLETE" and "unbound_records:1" in out["unresolved"]


def test_caller_tags_on_a_bound_record_never_add_counts(normalizer):
    # One fully bound record carrying 899 extra caller tags: tags must not lift the count to 900.
    idx = g1.ProtectedIndex([_rec(0, coverage_keys=["mmmu:records"] * 899)], normalizer)
    _refuses("PROTECTED_UNIVERSE_INCOMPLETE:mmmu:records:1!=900", g1.check_bundle, {}, index=idx,
             contracts={"coverage_expected": {"mmmu:records": 900}}, claim="COMPLETE")


def _media_index(normalizer):
    # mail 48390: one bound question whose protected image is known only by its media digest.
    rec = _rec(0, text="ordinary protected question text", media_sha256=_sha(b"protected-image-id"))
    return g1.ProtectedIndex([rec], normalizer)


ONE = {"coverage_expected": {"mmmu:records": 1, "mmmu:field:question:text": 1, "mmmu:media": 1}}


def test_counted_media_asset_refuses_under_complete(normalizer):
    idx = _media_index(normalizer)
    assert g1.coverage_status(idx, ONE) == ("COMPLETE", [])
    _refuses("PROTECTED_CONTENT_EXACT", g1.check_bundle, {"asset": "protected-image-id"}, index=idx, contracts=ONE, claim="COMPLETE")


def test_other_media_asset_accepted_under_complete(normalizer):
    g1.check_bundle({"asset": "an unrelated public image id"}, index=_media_index(normalizer), contracts=ONE, claim="COMPLETE")
