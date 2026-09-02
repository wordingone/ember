# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Issue #1464 residual: the semantic (and shared governed) `run_vertical_slice.py`
routes emit the frozen `train_step` envelope's `tokens`/`wall_seconds` fields, so a
real semantic run's telemetry can be energy-enriched and accepted into an R1-E8
liveness series -- not just a run through `a1_execution.py::run_dense_a1`.

Every progress dict exercised here comes from the REAL, unmocked shared producer
(`pretrain.py::run_pretraining_segment`, which `run_manifest_bound_semantic_segment`
delegates to for the semantic route) -- never a hand-typed dict. The end-to-end leg
carries that real telemetry through the REAL, unmocked
`a1_energy_apportionment.enrich_telemetry_with_energy` and
`a1_e8_evidence.derive_liveness_series` -- the two real downstream consumers this
residual exists to satisfy.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

import torch

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
TOOLS = ROOT / "tools" / "ember-restart-3b"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load(name: str):
    inserted = str(TOOLS) not in sys.path
    if inserted:
        sys.path.insert(0, str(TOOLS))
    try:
        return _load_module(TOOLS / f"{name}.py", f"{name}_under_test_1464_semantic_envelope")
    finally:
        if inserted:
            sys.path.remove(str(TOOLS))


VERTICAL_SLICE = _load("run_vertical_slice")
EVIDENCE = _load("a1_e8_evidence")
APPORTIONMENT = _load("a1_energy_apportionment")

sys.path.insert(0, str(TOOLS))
from model import RestartDecoderConfig, UnifiedDecoder  # noqa: E402
from pretrain import run_pretraining_segment  # noqa: E402


def _core_text_record(index: int) -> dict[str, object]:
    """A core-only text episode -- routes no expert, so `require_complete_coverage`
    can stay False without needing every modality present (mirrors test_pretrain.py's
    convention)."""

    base = 8 + index
    return {
        "schema_version": "ember-owned-semantic-text-v1",
        "active_expert": "shared",
        "token_ids": [base, base + 1, base + 2, base + 3],
        "target_ids": [base + 1, base + 2, base + 3, base + 4],
    }


def _write_samples(path: Path, rows: list[tuple[float, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for ts, watts in rows:
            handle.write(json.dumps({"ts": ts, "watts": watts}, sort_keys=True) + "\n")


class SemanticEnvelopeTests(unittest.TestCase):
    def _run_steps(self, *, steps: int, progress_callback) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=41)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        records = [_core_text_record(index) for index in range(steps)]
        run_pretraining_segment(
            model=model, optimizer=optimizer, records=records, config=config, device=torch.device("cpu"),
            checkpoint_every=steps, checkpoint_callback=lambda *_: None,
            progress_callback=progress_callback, require_complete_coverage=False,
        )

    def test_frozen_envelope_fields_transcribes_the_real_producers_own_measurements(self) -> None:
        """The real per-step progress dict from `run_pretraining_segment` -- the
        exact shape both `run()` and `run_semantic()` receive -- carries
        `tokens_consumed`/`step_ms` but not yet `tokens`/`wall_seconds`. This is
        the base-commit gap: `_frozen_envelope_fields` must transcribe, honestly,
        from the real values the producer already measured."""

        captured: list[dict[str, object]] = []
        self._run_steps(steps=3, progress_callback=captured.append)
        self.assertEqual(len(captured), 3)
        for progress in captured:
            self.assertNotIn("tokens", progress)
            self.assertNotIn("wall_seconds", progress)
            tokens_consumed = progress["tokens_consumed"]
            step_ms = progress["step_ms"]
            self.assertIsInstance(tokens_consumed, int)
            self.assertGreater(tokens_consumed, 0)
            self.assertIsInstance(step_ms, float)
            self.assertGreater(step_ms, 0.0)
            fields = VERTICAL_SLICE._frozen_envelope_fields(progress)
            self.assertEqual(fields, {"tokens": tokens_consumed, "wall_seconds": step_ms / 1000.0})
            # Byte-compatibility: the source keys stay untouched for the E4
            # accumulator/battery, which still read them under their own names.
            self.assertEqual(progress["tokens_consumed"], tokens_consumed)
            self.assertEqual(progress["step_ms"], step_ms)

    def test_frozen_envelope_fields_omits_rather_than_fabricates_on_a_missing_source(self) -> None:
        self.assertEqual(VERTICAL_SLICE._frozen_envelope_fields({"step": 1}), {})
        self.assertEqual(
            VERTICAL_SLICE._frozen_envelope_fields({"tokens_consumed": 0, "step_ms": 0.0}), {},
        )
        self.assertEqual(
            VERTICAL_SLICE._frozen_envelope_fields({"tokens_consumed": -4, "step_ms": float("nan")}), {},
        )

    def test_unenriched_semantic_shaped_telemetry_stays_liveness_incomplete(self) -> None:
        """Regression guard for the pre-fix shape: a `train_step` row carrying
        only the producer's own `tokens_consumed`/`step_ms` names (no
        `_frozen_envelope_fields` applied) is correctly refused by the real,
        unmocked liveness derivation -- documents exactly the gap this issue
        closes, and must stay true (an un-enriched row must never be silently
        accepted)."""

        with tempfile.TemporaryDirectory() as raw:
            tmp_path = Path(raw)
            telemetry_path = tmp_path / "telemetry.jsonl"
            run_id = "semantic-unenriched-1464"

            def progress_callback(progress: dict[str, object]) -> None:
                VERTICAL_SLICE.append_training_telemetry(
                    telemetry_path, kind="train_step", payload={"run_id": run_id, **progress},
                )

            self._run_steps(steps=2, progress_callback=progress_callback)
            with self.assertRaises(EVIDENCE.E8EvidenceProducerError) as context:
                EVIDENCE.derive_liveness_series(telemetry_path, run_id=run_id, run_receipt_sha256="a" * 64)
            self.assertIn("no liveness-complete train_step rows", str(context.exception))

    def test_semantic_route_progress_callback_shape_is_liveness_and_energy_acceptable_end_to_end(self) -> None:
        """Replicates `run_semantic`'s real `progress_callback` closure body
        verbatim (module-level `append_training_telemetry` +
        `_frozen_envelope_fields`, both the real functions under test -- the
        semantic route never wraps GPU-memory fields the way the governed
        route's closure does, so nothing else needs stubbing) driven by the
        real producer, then proves the two real downstream consumers accept
        the result: `a1_energy_apportionment.enrich_telemetry_with_energy`
        (real trapezoidal apportionment against a real raw samples file) and
        `a1_e8_evidence.derive_liveness_series` (real, unmocked)."""

        with tempfile.TemporaryDirectory() as raw:
            tmp_path = Path(raw)
            telemetry_path = tmp_path / "telemetry.jsonl"
            samples_path = tmp_path / "telemetry.gpu-samples.jsonl"
            run_id = "semantic-enriched-1464"

            def progress_callback(progress: dict[str, object]) -> None:
                # Verbatim body of run_vertical_slice.run_semantic's real
                # progress_callback closure.
                VERTICAL_SLICE.append_training_telemetry(telemetry_path, kind="train_step", payload={
                    "run_id": run_id,
                    **progress,
                    **VERTICAL_SLICE._frozen_envelope_fields(progress),
                })

            before = time.time()
            self._run_steps(steps=3, progress_callback=progress_callback)
            after = time.time()

            # Pre-apportionment: tokens/wall_seconds are now present, but
            # proxy_joules is still deliberately absent (no sidecar has run
            # yet) -- the row must still read as liveness-incomplete, exactly
            # as `a1_execution._train_step_envelope`'s own docstring requires.
            with self.assertRaises(EVIDENCE.E8EvidenceProducerError):
                EVIDENCE.derive_liveness_series(telemetry_path, run_id=run_id, run_receipt_sha256="b" * 64)

            # `_integrate_step` correctly refuses to attribute a step's interval
            # unless a REAL sample timestamp falls inside that interval, not
            # merely inside some broad bracket -- so the fixture must sample
            # densely enough (1ms) to actually touch each ms-scale step, the
            # same density a real 1Hz sidecar would only sometimes achieve.
            dense_samples = [
                (before - 0.05 + index * 0.001, 100.0 + (index % 5))
                for index in range(int((after - before + 0.1) / 0.001) + 2)
            ]
            _write_samples(samples_path, dense_samples)
            enriched_count = APPORTIONMENT.enrich_telemetry_with_energy(telemetry_path, samples_path, run_id=run_id)
            self.assertEqual(enriched_count, 3)

            series = EVIDENCE.derive_liveness_series(telemetry_path, run_id=run_id, run_receipt_sha256="c" * 64)
            self.assertEqual(series["run_receipt_sha256"], "c" * 64)
            self.assertEqual([sample["step"] for sample in series["samples"]], [1, 2, 3])
            for sample in series["samples"]:
                self.assertGreater(int(sample["tokens"]), 0)
                self.assertGreater(float(sample["wall_seconds"]), 0.0)
                self.assertGreaterEqual(float(sample["proxy_joules"]), 0.0)


if __name__ == "__main__":
    unittest.main()
