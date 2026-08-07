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
    build_parameter_manifest_from_parts,
    build_pricing_receipt,
    manifest_sha256,
    validate_parameter_manifest,
    validate_pricing_receipt,
    pricing_receipt_sha256,
    write_parameter_manifest,
    write_pricing_receipt,
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

    def test_horizon_scoring_requires_live_manifest_and_pricing_evidence(self):
        import fp44_horizon_equiv_gate

        receipt = {
            "arms": {
                "muon_split_baseline": {"val_losses": {"250": 1.0, "1000": 1.0, "2000": 1.0}},
                "full_fused_adamw": {"val_losses": {"250": 1.0, "1000": 1.0, "2000": 1.0}},
            }
        }
        missing = fp44_horizon_equiv_gate.score_receipt(
            receipt, require_parameter_manifest=True
        )
        self.assertEqual(missing["status"], "SCHEMA_MISMATCH")
        self.assertIn("pricing", missing["parameter_manifest_error"])

    def test_horizon_scoring_accepts_two_actual_pricing_receipts(self):
        import fp44_horizon_equiv_gate

        model = TinyMtp()
        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        manifest = build_parameter_manifest(model, optimizer, _config())
        receipt = {
            "arms": {
                "muon_split_baseline": {
                    "val_losses": {"250": 1.0, "1000": 1.0, "2000": 1.0},
                    "parameter_pricing_receipt": build_pricing_receipt(manifest, "muon-run"),
                },
                "full_fused_adamw": {
                    "val_losses": {"250": 1.0, "1000": 1.0, "2000": 1.0},
                    "parameter_pricing_receipt": build_pricing_receipt(manifest, "adamw-run"),
                },
            }
        }
        scored = fp44_horizon_equiv_gate.score_receipt(
            receipt, parameter_manifest=manifest, require_parameter_manifest=True
        )
        self.assertEqual(scored["status"], "SCORED")
        self.assertEqual(
            set(scored["parameter_pricing_receipts"]),
            {"muon_split_baseline", "full_fused_adamw"},
        )
    def test_actual_run_pricing_receipt_binds_post_update_live_parts(self):
        model = TinyMtp()
        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        loss = sum(parameter.square().sum() for parameter in model.parameters())
        loss.backward()
        optimizer.step()
        manifest = build_parameter_manifest_from_parts(
            model.base, model.base, model.mtp_heads, {"sgd": optimizer}, _config()
        )
        receipt = build_pricing_receipt(manifest, "issue688-test-run")
        validate_pricing_receipt(receipt, manifest)
        self.assertEqual(receipt["evidence"], "actual-run")
        self.assertEqual(receipt["realized_parameter_count"], 12)
        self.assertEqual(receipt["receipt_sha256"], pricing_receipt_sha256(receipt))
        tampered = copy.deepcopy(receipt)
        tampered["realized_parameter_count"] += 1
        tampered["receipt_sha256"] = pricing_receipt_sha256(tampered)
        with self.assertRaisesRegex(MtpParameterManifestError, "realized count"):
            validate_pricing_receipt(tampered, manifest)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "pricing-receipt.json"
            self.assertEqual(write_pricing_receipt(path, manifest, "issue688-test-run"), receipt)

    def test_optimizer_boundary_source_binds_actual_manifest_and_pricing(self):
        source = (ROOT / "scripts" / "fp44_horizon_optimizer_equiv.py").read_text(encoding="utf-8")
        self.assertIn("write_parameter_manifest_from_parts", source)
        self.assertIn("write_pricing_receipt", source)
        self.assertIn("_bind_live_parameter_evidence", source)
        timeshare_source = (ROOT / "scripts" / "timeshare_pretrain.py").read_text(encoding="utf-8")
        self.assertIn("write_parameter_manifest", timeshare_source)
        self.assertIn("write_pricing_receipt", timeshare_source)

    def test_launch_receipt_requires_manifest(self):
        import v0_pretrain_launch_gate

        rows = [(name, "GREEN", "ok") for name in v0_pretrain_launch_gate.ROWS]
        with self.assertRaisesRegex(ValueError, "parameter manifest"):
            v0_pretrain_launch_gate.emit(datetime.date(2026, 1, 1), rows)
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
    def test_live_boundary_binds_manifest_before_first_optimizer_update(self):
        source = (ROOT / "scripts" / "timeshare_pretrain.py").read_text(encoding="utf-8")
        prelaunch = source.index("_write_live_parameter_manifest(")
        optimizer_boundary = source.index("optimizers, base_lrs, routing = build_split_optimizer(")
        prelaunch_call = source.index('f"{segment_id}-prelaunch"')
        strict_gate = source.index("require_parameter_manifest=True", prelaunch)
        first_update = source.index("_run_production_step(", strict_gate)
        self.assertLess(optimizer_boundary, prelaunch_call)
        self.assertLess(prelaunch_call, strict_gate)
        self.assertLess(prelaunch, strict_gate)
        self.assertLess(strict_gate, first_update)
        self.assertIn("parameter_manifest_path=str(_prelaunch_manifest_path)", source)
        self.assertIn("require_parameter_manifest=False", source)

        import v0_pretrain_launch_gate

        rows = v0_pretrain_launch_gate.gate(
            datetime.date(2026, 1, 1),
            require_parameter_manifest=True,
        )
        status, detail = next(
            (status, detail)
            for name, status, detail in rows
            if name == "G-config"
        )
        self.assertEqual(status, "BLOCKED")
        self.assertIn("parameter manifest", detail)
if __name__ == "__main__":
    unittest.main()
