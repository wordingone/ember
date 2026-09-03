#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Forecast-recalibration receipt generator -- R1-E6 (issue #1464).

Prereg authority: docs/domains/governance/spec/ember02-preregistration-v1.md (pin 3d48d387), section 3
common structure, closing receipts clause: "forecast-recalibration receipt:
predicted vs measured step time, tokens/s, proxy-joules/token, peak VRAM, loss
trajectory". This script produces that receipt for one run root against one
preregistered forecast document, and refuses -- with the missing quantity named
and NO receipt written -- whenever any of the five quantities cannot be measured
from evidence already in the run root. A partial recalibration must never mint
a receipt (same fail-closed posture as src/ember/governance/scripts/r1_exit_battery.py, which
validates this receipt's content for the E6 verdict).

Measurement sources (each named in the receipt so the battery and any reader can
re-derive the number):

  step_time_ms          median of deduped train_step step_ms rows (dedupe by step,
                        last occurrence wins -- matches the battery's series
                        selection; re-launched attempts append duplicate steps).
  tokens_per_second     preferred: sum of per-step tokens_consumed telemetry
                        (R1-E4 wiring); fallback: checkpoint-manifest data_cursor
                        tokens_seen over global_step, divided by measured median
                        step time. The fallback is lineage-cumulative arithmetic
                        and is only valid for a from-step-1 run, so it REFUSES
                        when the manifest's lineage shows a resume.
  proxy_joules_per_token  total_proxy_joules from the run root's energy-proxy
                        receipt (src/ember/governance/scripts/energy_proxy_logger.py vocabulary --
                        bound here, not re-invented) over the same token count.
  peak_vram_gib         preferred: peak_memory_bytes from an R1-E4 capture;
                        fallback: telemetry max(total_gib - free_gib).
  loss_trajectory       measured loss at every anchor step the forecast names.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "ember02-forecast-recalibration/v1"
FORECAST_SCHEMA = "ember02-r1-forecast/v1"
GENERATOR = "src/ember/governance/scripts/forecast_recalibration.py"
SCALAR_QUANTITIES = ("step_time_ms", "tokens_per_second", "proxy_joules_per_token", "peak_vram_gib")
REPO_ROOT = Path(__file__).resolve().parents[4]


class RecalibrationRefusal(RuntimeError):
    """Raised with a named reason whenever a quantity cannot be measured."""


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def telemetry_paths(run_root: Path) -> list[Path]:
    """Return the exact telemetry domain consumed by the E6 validator.

    The producer must hash the same source-qualified JSONL files that the
    consumer will parse; unrelated JSONL artifacts are deliberately outside
    this content-addressed domain.
    """
    return sorted(
        p for p in run_root.rglob("*.jsonl")
        if ".checkpoint-quarantine" not in p.parts
        and any(
            isinstance(row, dict) and row.get("source") == "ember-restart-3b"
            for row in _iter_jsonl(p)
        )
    )


def _iter_jsonl(path: Path):
    try:
        for raw_line in path.read_bytes().splitlines(keepends=True):
            if len(raw_line) > 4096:
                continue
            line = raw_line.decode("utf-8")
            if line.strip():
                try:
                    value = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(value, dict):
                    yield value
    except (OSError, UnicodeError) as error:
        raise RecalibrationRefusal(f"TELEMETRY_UNREADABLE: {path}: {error}") from error


def telemetry_sha256(run_root: Path) -> str:
    digest = hashlib.sha256()
    paths = telemetry_paths(run_root)
    if not paths:
        raise RecalibrationRefusal(
            f"TELEMETRY_MISSING: no non-quarantined JSONL telemetry under {run_root}"
        )
    for path in paths:
        try:
            relative = path.relative_to(run_root).as_posix().encode("utf-8")
            payload = path.read_bytes()
        except OSError as error:
            raise RecalibrationRefusal(f"TELEMETRY_UNREADABLE: {path}: {error}") from error
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def validate_telemetry_binding(receipt: dict[str, Any], run_root: Path) -> None:
    claimed = receipt.get("telemetry_sha256")
    if not isinstance(claimed, str) or len(claimed) != 64 or any(c not in "0123456789abcdef" for c in claimed):
        raise RecalibrationRefusal("TELEMETRY_SHA256_MISSING: receipt must bind telemetry bytes")
    actual = telemetry_sha256(run_root)
    if claimed != actual:
        raise RecalibrationRefusal(
            f"TELEMETRY_SHA256_MISMATCH: receipt={claimed} actual={actual}"
        )


def load_forecast(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RecalibrationRefusal(f"FORECAST_UNREADABLE: {path}: {error}") from error
    if doc.get("schema_version") != FORECAST_SCHEMA:
        raise RecalibrationRefusal(
            f"FORECAST_SCHEMA_UNRECOGNIZED: {path} carries schema_version "
            f"{doc.get('schema_version')!r}, need {FORECAST_SCHEMA!r}"
        )
    quantities = doc.get("quantities")
    if not isinstance(quantities, dict):
        raise RecalibrationRefusal("FORECAST_SCHEMA_UNRECOGNIZED: no quantities mapping")
    for name in SCALAR_QUANTITIES:
        q = quantities.get(name)
        if not isinstance(q, dict) or not _finite(q.get("predicted")):
            raise RecalibrationRefusal(f"FORECAST_QUANTITY_INVALID: {name} lacks a finite predicted value")
    lt = quantities.get("loss_trajectory")
    anchors = lt.get("predicted_anchors") if isinstance(lt, dict) else None
    if not isinstance(anchors, dict) or not anchors or not all(_finite(v) for v in anchors.values()):
        raise RecalibrationRefusal("FORECAST_QUANTITY_INVALID: loss_trajectory.predicted_anchors must be a non-empty mapping of finite values")
    for key in anchors:
        if not (isinstance(key, str) and key.startswith("step_") and key[5:].isdigit()):
            raise RecalibrationRefusal(f"FORECAST_QUANTITY_INVALID: loss_trajectory anchor key {key!r} is not step_<N>")
    return doc


def load_train_series(run_root: Path) -> dict[str, list[dict[str, Any]]]:
    """Deduped train_step payload rows grouped by run_id.

    A run root may contain resumed or retried attempts.  Keep the latest row
    by timestamp for each ``(run_id, step)`` pair so a different run cannot
    overwrite the selected run's evidence.
    """
    best: dict[tuple[str, int], tuple[str, dict[str, Any]]] = {}
    for telemetry_path in sorted(p for p in run_root.rglob("*.jsonl") if ".checkpoint-quarantine" not in p.parts):
        try:
            lines = telemetry_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("source") != "ember-restart-3b" or row.get("kind") != "train_step":
                continue
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            run_id = payload.get("run_id")
            step = payload.get("step")
            ts = row.get("ts")
            if (
                isinstance(run_id, str) and run_id.strip()
                and isinstance(step, int) and not isinstance(step, bool)
                and isinstance(ts, str) and ts
            ):
                key = (run_id, step)
                prior = best.get(key)
                if prior is None or ts > prior[0]:
                    best[key] = (ts, payload)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for (run_id, _step), (_ts, payload) in best.items():
        grouped.setdefault(run_id, []).append(payload)
    for series in grouped.values():
        series.sort(key=lambda row: row["step"])
    return grouped


def select_train_series(run_root: Path, *, run_id: str | None = None) -> tuple[str, list[dict[str, Any]]]:
    """Select exactly one telemetry run for a recalibration receipt."""
    grouped = load_train_series(run_root)
    if run_id is not None:
        series = grouped.get(run_id)
        if not series:
            raise RecalibrationRefusal(
                f"RUN_ID_NOT_FOUND: requested run_id={run_id!r} has no train_step telemetry "
                f"under {run_root} (run_ids_seen={sorted(grouped)!r})"
            )
        return run_id, series
    if not grouped:
        raise RecalibrationRefusal(f"UNMEASURABLE: no train_step telemetry under {run_root}")
    if len(grouped) != 1:
        raise RecalibrationRefusal(
            "AMBIGUOUS_RUN_ID: more than one telemetry run_id under the run root; "
            f"pass --run-id to select one (run_ids_seen={sorted(grouped)!r})"
        )
    selected_run_id, series = next(iter(grouped.items()))
    return selected_run_id, series


def find_checkpoint_manifest(run_root: Path) -> tuple[Path, dict[str, Any]]:
    candidates = sorted(p for p in run_root.rglob("checkpoint-manifest.json") if ".checkpoint-quarantine" not in p.parts)
    if not candidates:
        raise RecalibrationRefusal(f"MANIFEST_MISSING: no checkpoint-manifest.json under {run_root} outside quarantine")
    if len(candidates) > 1:
        raise RecalibrationRefusal(
            "MANIFEST_AMBIGUOUS: multiple checkpoint manifests under the run root: "
            + ", ".join(str(p) for p in candidates)
        )
    path = candidates[0]
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RecalibrationRefusal(f"MANIFEST_UNREADABLE: {path}: {error}") from error


def measure_step_time_ms(series: list[dict[str, Any]]) -> dict[str, Any]:
    values = [p["step_ms"] for p in series if _finite(p.get("step_ms"))]
    if not values:
        raise RecalibrationRefusal("UNMEASURABLE step_time_ms: no finite step_ms rows in telemetry")
    ordered = sorted(values)
    return {
        "value": statistics.median(values),
        "n": len(values),
        "p10": ordered[len(ordered) // 10],
        "p90": ordered[(9 * len(ordered)) // 10],
        "source": "telemetry train_step step_ms, deduped by step (last occurrence), median",
    }


def measure_tokens_per_second(series: list[dict[str, Any]], run_root: Path, step_time_ms: float) -> dict[str, Any]:
    telemetry_tokens = [p["tokens_consumed"] for p in series if _finite(p.get("tokens_consumed"))]
    if telemetry_tokens and len(telemetry_tokens) == len(series):
        tokens_per_step = sum(telemetry_tokens) / len(telemetry_tokens)
        source = "telemetry per-step tokens_consumed (R1-E4 wiring), mean over all steps"
    else:
        manifest_path, manifest = find_checkpoint_manifest(run_root)
        cursor = manifest.get("data_cursor")
        if not isinstance(cursor, dict):
            raise RecalibrationRefusal(f"UNMEASURABLE tokens_per_second: {manifest_path} has no data_cursor")
        tokens_seen, global_step = cursor.get("tokens_seen"), cursor.get("global_step")
        if not (_finite(tokens_seen) and _finite(global_step) and global_step >= 1):
            raise RecalibrationRefusal(
                "UNMEASURABLE tokens_per_second: data_cursor lacks finite tokens_seen/global_step "
                f"(tokens_seen={tokens_seen!r}, global_step={global_step!r})"
            )
        # src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py writes
        # data_cursor["resume_authority"] ONLY when the run resumed a checkpoint
        # (both write-sites: specialist ~2828-2829 and semantic ~3279-3280) --
        # its presence is the authoritative resume marker. A resumed run's
        # global_step is lineage-cumulative while tokens_seen is not guaranteed
        # to be, so the division is invalid there.
        if cursor.get("resume_authority") is not None:
            raise RecalibrationRefusal(
                "UNMEASURABLE tokens_per_second: data_cursor carries resume_authority (this run resumed "
                "a checkpoint), so tokens_seen/global_step arithmetic is invalid; per-step "
                "tokens_consumed telemetry (R1-E4 wiring) is required instead"
            )
        tokens_per_step = tokens_seen / global_step
        source = f"checkpoint-manifest data_cursor tokens_seen {tokens_seen} / global_step {global_step} (from-step-1 lineage verified)"
    return {
        "value": tokens_per_step / (step_time_ms / 1000.0),
        "tokens_per_step": tokens_per_step,
        "source": source,
    }


def measure_proxy_joules_per_token(run_root: Path, series: list[dict[str, Any]], tokens_per_step: float) -> dict[str, Any]:
    candidates = sorted(p for p in run_root.rglob("*energy-proxy*.json") if ".checkpoint-quarantine" not in p.parts)
    if not candidates:
        raise RecalibrationRefusal(
            "UNMEASURABLE proxy_joules_per_token: no *energy-proxy*.json receipt under the run root "
            "(src/ember/governance/scripts/energy_proxy_logger.py was not invoked for this run -- R1-E5 wiring)"
        )
    if len(candidates) > 1:
        raise RecalibrationRefusal(
            "UNMEASURABLE proxy_joules_per_token: multiple energy-proxy receipts under the run root: "
            + ", ".join(str(p) for p in candidates)
        )
    path = candidates[0]
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RecalibrationRefusal(f"UNMEASURABLE proxy_joules_per_token: {path}: {error}") from error
    # src/ember/governance/scripts/energy_proxy_logger.py (schema ember-energy-proxy-run-v1) nests
    # total_proxy_joules/energy_boundary under an "energy" block -- the same
    # place src/ember/governance/scripts/r1_exit_battery.py's E5 leg reads them from. There is no
    # flat top-level shape in this receipt's history; a top-level read would
    # silently miss every real producer.
    energy = receipt.get("energy") if isinstance(receipt, dict) else None
    if not isinstance(energy, dict):
        raise RecalibrationRefusal(
            f"UNMEASURABLE proxy_joules_per_token: {path} carries no nested \"energy\" object "
            "(src/ember/governance/scripts/energy_proxy_logger.py writes total_proxy_joules/energy_boundary under "
            "energy.*, matching the E5 battery leg)"
        )
    total = energy.get("total_proxy_joules")
    boundary = energy.get("energy_boundary")
    if not _finite(total) or total <= 0 or not boundary:
        raise RecalibrationRefusal(
            f"UNMEASURABLE proxy_joules_per_token: {path} energy block lacks finite positive "
            f"total_proxy_joules ({total!r}) or energy_boundary ({boundary!r})"
        )
    total_tokens = tokens_per_step * len(series)
    if total_tokens <= 0:
        raise RecalibrationRefusal("UNMEASURABLE proxy_joules_per_token: zero tokens over the measured steps")
    return {
        "value": total / total_tokens,
        "total_proxy_joules": total,
        "energy_boundary": boundary,
        "receipt": str(path),
        "source": "energy-proxy receipt energy.total_proxy_joules over tokens_per_step x measured steps",
    }


def measure_peak_vram_gib(run_root: Path, series: list[dict[str, Any]], *, run_id: str | None = None) -> dict[str, Any]:
    peak_bytes = None
    peak_source = None
    for log_path in sorted(run_root.glob("*-child.log")):
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if _finite(row.get("peak_memory_bytes")):
                peak_bytes, peak_source = row["peak_memory_bytes"], f"{log_path.name} final JSON peak_memory_bytes"
            break
    if peak_bytes is not None:
        return {"value": peak_bytes / (1024 ** 3), "source": peak_source}

    # A certified semantic run (the real R1 evidence root) produces neither a
    # *-child.log nor telemetry total_gib/free_gib rows -- it produces
    # e4-measurement-receipt.json (schema ember02-r1-e4-measurement/v1) at the
    # run root, carrying peak_vram.allocated_bytes: the allocator peak, higher
    # fidelity than the device-level telemetry proxy below. Same candidate
    # convention as src/ember/governance/scripts/r1_exit_battery.py's E4 leg (excluded from
    # .checkpoint-quarantine, ambiguous on more than one file).
    e4_candidates = sorted(
        p for p in run_root.rglob("e4-measurement-receipt.json") if ".checkpoint-quarantine" not in p.parts
    )
    if len(e4_candidates) > 1:
        raise RecalibrationRefusal(
            "UNMEASURABLE peak_vram_gib: multiple e4-measurement-receipt.json files under the run root: "
            + ", ".join(str(p) for p in e4_candidates)
        )
    if len(e4_candidates) == 1:
        e4_path = e4_candidates[0]
        try:
            e4_receipt = json.loads(e4_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RecalibrationRefusal(f"UNMEASURABLE peak_vram_gib: {e4_path}: {error}") from error
        if isinstance(e4_receipt, dict) and (run_id is None or e4_receipt.get("run_id") == run_id):
            vram = e4_receipt.get("peak_vram")
            allocated = vram.get("allocated_bytes") if isinstance(vram, dict) else None
            if allocated is not None:
                if not _finite(allocated) or allocated <= 0:
                    raise RecalibrationRefusal(
                        f"UNMEASURABLE peak_vram_gib: {e4_path} peak_vram.allocated_bytes is not "
                        f"finite-positive ({allocated!r})"
                    )
                return {
                    "value": allocated / (1024 ** 3),
                    "source": f"{e4_path.name} peak_vram.allocated_bytes (allocator peak, R1-E4 wiring)",
                }

    used = [p["total_gib"] - p["free_gib"] for p in series if _finite(p.get("total_gib")) and _finite(p.get("free_gib"))]
    if not used:
        raise RecalibrationRefusal(
            "UNMEASURABLE peak_vram_gib: no captured peak_memory_bytes, no e4-measurement-receipt "
            "peak_vram.allocated_bytes, and no telemetry total_gib/free_gib rows"
        )
    return {"value": max(used), "source": "telemetry max(total_gib - free_gib) -- device-level proxy, allocator peak not captured"}


def measure_loss_anchors(series: list[dict[str, Any]], predicted_anchors: dict[str, float]) -> dict[str, Any]:
    by_step = {p["step"]: p for p in series}
    anchors: dict[str, Any] = {}
    missing: list[str] = []
    for key, predicted in predicted_anchors.items():
        step = int(key[5:])
        row = by_step.get(step)
        if row is None or not _finite(row.get("loss")):
            missing.append(key)
            continue
        measured = row["loss"]
        anchors[key] = {"predicted": predicted, "measured": measured, "abs_error": abs(measured - predicted)}
    if missing:
        raise RecalibrationRefusal(
            "UNMEASURABLE loss_trajectory: no finite measured loss at forecast anchor(s) " + ", ".join(sorted(missing))
        )
    return {"anchors": anchors, "source": "telemetry train_step loss at each forecast anchor step"}


def load_t01() -> int:
    """T-01 via the battery's own frozen-thresholds loader (schema, pin, and
    entry parsing live there) -- bound at runtime, never copied: the number's
    authority is that loader plus the frozen file, not this script."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from r1_exit_battery import load_thresholds
        thresholds, _ = load_thresholds()
        return int(thresholds["T-01"])
    except Exception as error:
        raise RecalibrationRefusal(f"THRESHOLDS_UNREADABLE: via r1_exit_battery.load_thresholds: {error}") from error


def repo_relative_forecast_path(forecast_path: Path, *, rung: str = "R1") -> str:
    """The receipt binds the PREREGISTERED document, so the path it records must
    be repo-relative, inside the repo, and equal to THE preregistered path the
    battery pins (rev-1490 finding 2 + round-2: any other repo JSON is a decoy
    the validator refuses -- refusing at generation time keeps the pair aligned
    instead of writing a receipt adjudication will reject). Refuses rather than
    silently rewriting. The canonical path is imported from the battery at
    runtime, never copied."""
    resolved = forecast_path.resolve()
    try:
        rel = resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        raise RecalibrationRefusal(
            f"FORECAST_OUTSIDE_REPO: {forecast_path} does not live inside {REPO_ROOT}; the receipt "
            "must bind the committed preregistered document, not an arbitrary file"
        ) from None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from r1_exit_battery import canonical_e6_forecast_path
    except ImportError as error:
        raise RecalibrationRefusal(f"BATTERY_UNIMPORTABLE: cannot bind the canonical forecast path: {error}") from error
    try:
        canonical_path = canonical_e6_forecast_path(rung)
    except Exception as error:
        raise RecalibrationRefusal(str(error)) from error
    if rel != canonical_path:
        raise RecalibrationRefusal(
            f"FORECAST_NOT_PREREGISTERED: {rel} is not the preregistered forecast document "
            f"for rung {rung} ({canonical_path}); the battery refuses cross-rung or non-canonical files"
        )
    return rel


def build_receipt(
    forecast_path: Path, run_root: Path, *, run_id: str | None = None, rung: str = "R1"
) -> dict[str, Any]:
    forecast = load_forecast(forecast_path)
    forecast_rel = repo_relative_forecast_path(forecast_path, rung=rung)
    t01 = load_t01()
    quantities = forecast["quantities"]
    selected_run_id, series = select_train_series(run_root, run_id=run_id)
    if len(series) < t01:
        raise RecalibrationRefusal(
            f"UNMEASURABLE: series has {len(series)} deduped steps, below the T-01={t01} measured "
            "baseline the prereg requires for recalibration"
        )

    step_time = measure_step_time_ms(series)
    tokens = measure_tokens_per_second(series, run_root, step_time["value"])
    energy = measure_proxy_joules_per_token(run_root, series, tokens["tokens_per_step"])
    vram = measure_peak_vram_gib(run_root, series, run_id=selected_run_id)
    losses = measure_loss_anchors(series, quantities["loss_trajectory"]["predicted_anchors"])
    telemetry_digest = telemetry_sha256(run_root)

    def scalar(name: str, measurement: dict[str, Any]) -> dict[str, Any]:
        predicted = quantities[name]["predicted"]
        measured = measurement.pop("value")
        entry = {
            "predicted": predicted,
            "measured": measured,
            "abs_error": abs(measured - predicted),
            "rel_error": abs(measured - predicted) / abs(predicted),
            "measurement": measurement,
        }
        ci_low, ci_high = quantities[name].get("ci_low"), quantities[name].get("ci_high")
        if _finite(ci_low) and _finite(ci_high):
            entry["within_ci"] = ci_low <= measured <= ci_high
        return entry

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "generator": GENERATOR,
        "rung": rung,
        "forecast_path": forecast_rel,
        "forecast_sha256": sha256_file(forecast_path),
        "run_root": str(run_root),
        "run_id": selected_run_id,
        "steps_measured": len(series),
        "telemetry_sha256": telemetry_digest,
        "quantities": {
            "step_time_ms": scalar("step_time_ms", step_time),
            "tokens_per_second": scalar("tokens_per_second", tokens),
            "proxy_joules_per_token": scalar("proxy_joules_per_token", energy),
            "peak_vram_gib": scalar("peak_vram_gib", vram),
            "loss_trajectory": losses,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--forecast", required=True, type=Path)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--run-id", default=None, help="select one telemetry run when the root contains multiple run IDs")
    parser.add_argument("--rung", default="R1", help="forecast rung whose canonical document is being recalibrated")
    parser.add_argument("--out", type=Path, default=None,
                        help="receipt path (default: <run-root>/forecast-recalibration.json)")
    parser.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    out_path = args.out or (args.run_root / "forecast-recalibration.json")
    try:
        receipt = build_receipt(args.forecast, args.run_root, run_id=args.run_id, rung=args.rung)
    except RecalibrationRefusal as refusal:
        print(f"forecast_recalibration: REFUSED: {refusal}", file=sys.stderr)
        print("no receipt written -- a partial recalibration must never mint one", file=sys.stderr)
        return 2
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"forecast-recalibration receipt written: {out_path}")
    for name in SCALAR_QUANTITIES:
        q = receipt["quantities"][name]
        print(f"  {name}: predicted {q['predicted']:.4g} measured {q['measured']:.4g} rel_error {q['rel_error']:.2%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
