from __future__ import annotations

# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import datetime
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

import torch


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mtp_parameter_manifest import (  # noqa: E402
    MtpParameterManifestError,
    attach_parameter_manifest,
    build_parameter_manifest,
    manifest_sha256,
    validate_parameter_manifest,
    write_parameter_manifest,
)


class TinyMtp(torch.nn.Module):
    def __init__(self, *, extra_base: bool = False, orphan: bool = False):
        super().__init__()
        self.base = torch.nn.Linear(2, 2, bias=False)
        self.mtp_heads = torch.nn.ModuleList(
            [torch.nn.Linear(2, 2, bias=False) for _ in range(2)]
        )
        if extra_base:
            self.extra = torch.nn.Parameter(torch.zeros(1))
        if orphan:
            self.rogue = torch.nn.Parameter(torch.zeros(1))


def _config(base=4, aux=8, realized=12):
    return {
        "model": {
            "parameter_accounting": {
                "base_excluding_mtp": base,
                "mtp_aux": aux,
                "realized": realized,
            }
        }
    }


class Issue688LiveManifestTests(unittest.TestCase):
    def test_independent_heads_emit_closed_manifest_and_hash(self):
        model = TinyMtp()
        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        manifest = build_parameter_manifest(model, optimizer, _config())
        self.assertEqual(manifest["parameter_accounting"], {
            "base_excluding_mtp": 4,
            "mtp_aux": 8,
            "realized": 12,
        })
        self.assertEqual(manifest["manifest_sha256"], manifest_sha256(manifest))
        self.assertEqual(len(manifest["parameters"]), 3)
        self.assertEqual({p["owner"] for p in manifest["parameters"]}, {"base", "mtp_head_0", "mtp_head_1"})
        validate_parameter_manifest(manifest, _config())

    def test_shared_storage_across_heads_refuses(self):
        model = TinyMtp()
        model.mtp_heads[1].weight = torch.nn.Parameter(model.mtp_heads[0].weight.detach())
        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        with self.assertRaisesRegex(MtpParameterManifestError, "cross-owner"):
            build_parameter_manifest(model, optimizer, _config())

    def test_compensating_trunk_inflation_refuses_declared_split(self):
        model = TinyMtp(extra_base=True)
        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        with self.assertRaisesRegex(MtpParameterManifestError, "base_excluding_mtp"):
            build_parameter_manifest(model, optimizer, _config())

    def test_orphan_parameter_owner_refuses(self):
        model = TinyMtp(orphan=True)
        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        with self.assertRaisesRegex(MtpParameterManifestError, "owner"):
            build_parameter_manifest(model, optimizer, _config())

    def test_parameter_missing_from_optimizer_group_refuses(self):
        model = TinyMtp()
        optimizer = torch.optim.SGD(model.base.parameters(), lr=0.1)
        with self.assertRaisesRegex(MtpParameterManifestError, "optimizer"):
            build_parameter_manifest(model, optimizer, _config())

    def test_manifest_tamper_and_unknown_field_refuse(self):
        model = TinyMtp()
        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        manifest = build_parameter_manifest(model, optimizer, _config())
        tampered = copy.deepcopy(manifest)
        tampered["parameters"][0]["numel"] += 1
        with self.assertRaisesRegex(MtpParameterManifestError, "(?:hash|sha256)"):
            validate_parameter_manifest(tampered, _config())
        unknown = copy.deepcopy(manifest)
        unknown["unexpected"] = True
        with self.assertRaisesRegex(MtpParameterManifestError, "unknown"):
            validate_parameter_manifest(unknown, _config())
        wrong_owner = copy.deepcopy(manifest)
        wrong_owner["parameters"][1]["owner"] = "base"
        wrong_owner["manifest_sha256"] = manifest_sha256(wrong_owner)
        with self.assertRaisesRegex(MtpParameterManifestError, "owner"):
            validate_parameter_manifest(wrong_owner, _config())

    def test_manifest_write_and_pricing_binding_are_content_addressed(self):
        model = TinyMtp()
        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "parameter-manifest.json"
            manifest = write_parameter_manifest(path, model, optimizer, _config())
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded, manifest)
            receipt = attach_parameter_manifest(
                {"ticket": "EMBER-702-ATTRIBUTION", "pricing": {"status": "MEASURED"}},
                model,
                optimizer,
                _config(),
                path,
            )
            self.assertEqual(receipt["parameter_manifest"]["sha256"], manifest["manifest_sha256"])
            self.assertEqual(receipt["parameter_accounting"]["realized"], 12)


    def test_config_check_requires_live_manifest_binding(self):
        import v0_config_check

        model = TinyMtp()
        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        manifest = build_parameter_manifest(model, optimizer, _config())
        original = v0_config_check._parameter_accounting_violations
        v0_config_check._parameter_accounting_violations = lambda cfg: []
        try:
            self.assertEqual(
                v0_config_check.parameter_accounting(_config(), live_manifest=manifest),
                (4, 8, 12),
            )
            forged = copy.deepcopy(manifest)
            forged["parameter_accounting"]["realized"] = 13
            with self.assertRaises(ValueError):
                v0_config_check.parameter_accounting(_config(), live_manifest=forged)
        finally:
            v0_config_check._parameter_accounting_violations = original

    def test_horizon_receipt_binds_parameter_manifest(self):
        import fp44_horizon_equiv_gate

        model = TinyMtp()
        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        manifest = build_parameter_manifest(model, optimizer, _config())
        receipt = {
            "arms": {
                "muon": {"val_losses": {"250": 1.0, "1000": 1.0, "2000": 1.0}},
                "adamw": {"val_losses": {"250": 1.0, "1000": 1.0, "2000": 1.0}},
            }
        }
        scored = fp44_horizon_equiv_gate.score_receipt(
            receipt, parameter_manifest=manifest
        )
        self.assertEqual(
            scored["parameter_manifest"]["sha256"], manifest["manifest_sha256"]
        )

    def test_launch_gate_rejects_bad_manifest_and_binds_receipt(self):
        import v0_pretrain_launch_gate

        model = TinyMtp()
        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        manifest = build_parameter_manifest(model, optimizer, _config())
        with tempfile.TemporaryDirectory() as td:
            rows = [(name, "GREEN", "ok") for name in v0_pretrain_launch_gate.ROWS]
            path = v0_pretrain_launch_gate.emit(
                datetime.date(2026, 1, 1),
                rows,
                output_dir=td,
                parameter_manifest=manifest,
            )
            emitted = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual(
                emitted["parameter_manifest"]["sha256"], manifest["manifest_sha256"]
            )
            self.assertEqual(
                emitted["parameter_accounting"], manifest["parameter_accounting"]
            )
            bad = Path(td) / "bad.json"
            bad.write_text(json.dumps({"unexpected": True}), encoding="utf-8")
            blocked = v0_pretrain_launch_gate.gate(
                datetime.date(2026, 1, 1), parameter_manifest_path=str(bad)
            )
            status, detail = next(
                (status, detail)
                for name, status, detail in blocked
                if name == "G-config"
            )
            self.assertEqual(status, "BLOCKED")
            self.assertIn("parameter manifest", detail)
if __name__ == "__main__":
    unittest.main()
