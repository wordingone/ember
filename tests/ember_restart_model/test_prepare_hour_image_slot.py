# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "src/ember/infrastructure/tools/ember-restart-3b/prepare_hour.py"


def load():
    spec = importlib.util.spec_from_file_location("prepare_hour_under_test", PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def ident(slot):
    return {"resume_derivation": {"image_slot": {"image_text": slot}}}


def test_text_only_refuses_any_manifest(tmp_path):
    f = tmp_path / "m.jsonl"
    f.write_text("{}\n")
    with pytest.raises(ValueError, match="text-only"):
        load().check_image_slot(ident(None), f)


def test_text_only_accepts_no_manifest():
    load().check_image_slot(ident(None), None)


def test_bound_slot_needs_the_same_manifest(tmp_path):
    m = load()
    f = tmp_path / "m.jsonl"
    f.write_bytes(b"{}\n")
    sha = hashlib.sha256(b"{}\n").hexdigest()
    m.check_image_slot(ident({"manifest_sha256": sha}), f)
    with pytest.raises(ValueError, match="differs"):
        m.check_image_slot(ident({"manifest_sha256": "0" * 64}), f)
    with pytest.raises(ValueError, match="differs"):
        m.check_image_slot(ident({"manifest_sha256": sha}), None)
