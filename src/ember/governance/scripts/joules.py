# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#!/usr/bin/env python3
"""joules.py — GPU power-draw sampler and trapezoidal integration.

Per docs/spec/energy-law-v1.md §4.2:

  Sample nvidia-smi power.draw at 1 Hz (or pynvml sub-second) and integrate
  to compute joules burned over a round. Receipt fields:

    {interval_s, mean_watts, peak_watts, wall_clock_s, joules_total,
     joules_per_token (optional), joules_per_verified_bit (optional)}

  Sanity ceiling: mean_watts <= 450W (RTX 4090 TGP), flag if exceeded.

Usage:
  python joules.py --watch <seconds>         # poll and integrate for N seconds
  python joules.py --selftest                # run synthetic test
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECEIPTS = ROOT / "receipts"
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def sample_power_nvidia_smi(interval_s: float = 1.0, duration_s: float = None):
    """Poll nvidia-smi power.draw at 1 Hz interval.

    Args:
        interval_s: polling interval in seconds (nvidia-smi floor ~1 Hz)
        duration_s: if provided, stop after this many seconds elapsed

    Yields:
        tuples of (timestamp_epoch, power_watts)

    Raises:
        RuntimeError if nvidia-smi not found or GPU not detected
    """
    try:
        # Check nvidia-smi is available
        subprocess.run(
            ["nvidia-smi", "--version"],
            capture_output=True,
            check=True,
            timeout=5
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        raise RuntimeError(f"nvidia-smi not available: {e}")

    start_time = time.time()
    last_sample = start_time

    while True:
        now = time.time()
        elapsed = now - start_time

        if duration_s is not None and elapsed >= duration_s:
            break

        # Sleep until next sample interval
        time_to_next = interval_s - (now - last_sample)
        if time_to_next > 0:
            time.sleep(time_to_next)

        now = time.time()
        last_sample = now

        try:
            # Query power.draw in watts (unformatted, no CSV overhead)
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=power.draw",
                 "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                raise RuntimeError(f"nvidia-smi returned {result.returncode}")

            power_str = result.stdout.strip().split('\n')[0]
            power_w = float(power_str)
            yield (now, power_w)

        except (ValueError, subprocess.TimeoutExpired, RuntimeError) as e:
            raise RuntimeError(f"Failed to read power.draw: {e}")


def sample_power_pynvml(interval_s: float = 1.0, duration_s: float = None):
    """Poll NVIDIA Management Library for power.draw.

    Provides sub-1Hz granularity if available. Falls back to nvidia-smi.

    Args:
        interval_s: polling interval in seconds
        duration_s: if provided, stop after this many seconds elapsed

    Yields:
        tuples of (timestamp_epoch, power_watts)
    """
    try:
        import pynvml
    except ImportError:
        # Fall back to nvidia-smi
        yield from sample_power_nvidia_smi(interval_s, duration_s)
        return

    try:
        pynvml.nvmlInit()
    except pynvml.NVMLError as e:
        raise RuntimeError(f"NVIDIA NVML init failed: {e}")

    try:
        device_count = pynvml.nvmlDeviceGetCount()
        if device_count == 0:
            raise RuntimeError("No NVIDIA GPU detected")

        # Use GPU 0
        device = pynvml.nvmlDeviceGetHandleByIndex(0)
        start_time = time.time()
        last_sample = start_time

        while True:
            now = time.time()
            elapsed = now - start_time

            if duration_s is not None and elapsed >= duration_s:
                break

            # Sleep until next interval
            time_to_next = interval_s - (now - last_sample)
            if time_to_next > 0:
                time.sleep(time_to_next)

            now = time.time()
            last_sample = now

            try:
                # Power draw in mW -> W
                power_mw = pynvml.nvmlDeviceGetPowerUsage(device)
                power_w = power_mw / 1000.0
                yield (now, power_w)
            except pynvml.NVMLError as e:
                raise RuntimeError(f"Failed to read power via NVML: {e}")

    finally:
        try:
            pynvml.nvmlShutdown()
        except:
            pass


def trapezoidal_integrate(samples):
    """Integrate power samples using trapezoidal rule.

    Args:
        samples: list of (timestamp_epoch, power_watts) tuples

    Returns:
        dict with integration results:
        {joules_total, mean_watts, peak_watts, wall_clock_s, samples_n, interval_s}
    """
    if not samples or len(samples) < 2:
        return {
            "joules_total": 0.0,
            "mean_watts": 0.0,
            "peak_watts": 0.0,
            "wall_clock_s": 0.0,
            "samples_n": len(samples),
            "interval_s": 0.0,
        }

    # Extract timestamps and power values
    timestamps = [t for t, _ in samples]
    powers = [p for _, p in samples]

    wall_clock_s = timestamps[-1] - timestamps[0]
    peak_watts = max(powers)
    mean_watts = sum(powers) / len(powers)

    # Trapezoidal integration: sum of (p_i + p_{i+1})/2 * dt
    joules = 0.0
    for i in range(len(samples) - 1):
        t_i, p_i = samples[i]
        t_next, p_next = samples[i + 1]
        dt = t_next - t_i
        joules += (p_i + p_next) / 2.0 * dt

    interval_s = wall_clock_s / (len(samples) - 1) if len(samples) > 1 else 0.0

    return {
        "joules_total": joules,
        "mean_watts": mean_watts,
        "peak_watts": peak_watts,
        "wall_clock_s": wall_clock_s,
        "samples_n": len(samples),
        "interval_s": interval_s,
    }


def generate_receipt(integration, token_count=None, verified_bits=None):
    """Generate a receipt dict with all required fields.

    Args:
        integration: dict from trapezoidal_integrate()
        token_count: optional number of tokens processed
        verified_bits: optional number of verified bits

    Returns:
        dict receipt with all fields including joules_per_token etc.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    receipt = {
        "ticket": "JOULES-SAMPLER",
        "ts": ts,
        "interval_s": integration["interval_s"],
        "mean_watts": round(integration["mean_watts"], 2),
        "peak_watts": round(integration["peak_watts"], 2),
        "wall_clock_s": round(integration["wall_clock_s"], 3),
        "joules_total": round(integration["joules_total"], 4),
        "samples_n": integration["samples_n"],
    }

    # Optional fields
    if token_count is not None and integration["joules_total"] > 0:
        receipt["joules_per_token"] = round(
            integration["joules_total"] / token_count, 6
        )

    if verified_bits is not None and integration["joules_total"] > 0:
        receipt["joules_per_verified_bit"] = round(
            integration["joules_total"] / verified_bits, 6
        )

    # Sanity check: mean_watts must be <= 450W (RTX 4090 TGP)
    if receipt["mean_watts"] > 450:
        receipt["sanity_check"] = "INVALID"
        receipt["sanity_reason"] = (
            f"mean_watts={receipt['mean_watts']}W exceeds 450W "
            "(RTX 4090 TGP ceiling)"
        )
    else:
        receipt["sanity_check"] = "OK"

    return receipt


def run_watch(duration_s: float):
    """Watch GPU power for duration_s seconds and emit receipt."""
    print(f"[joules.py] Sampling GPU power for {duration_s}s...")

    samples = []
    try:
        # Try pynvml first (sub-1Hz capable), fall back to nvidia-smi
        for timestamp, power_w in sample_power_pynvml(duration_s=duration_s):
            samples.append((timestamp, power_w))
            elapsed = timestamp - samples[0][0] if samples else 0
            print(f"  {elapsed:.1f}s: {power_w:.1f}W")

    except RuntimeError as e:
        print(f"[joules.py] NVIDIA access failed, trying nvidia-smi fallback: {e}")
        try:
            for timestamp, power_w in sample_power_nvidia_smi(duration_s=duration_s):
                samples.append((timestamp, power_w))
                elapsed = timestamp - samples[0][0] if samples else 0
                print(f"  {elapsed:.1f}s: {power_w:.1f}W")
        except RuntimeError as e:
            print(f"ERROR: {e}")
            return False

    if not samples or len(samples) < 2:
        print("ERROR: insufficient samples collected")
        return False

    # Integrate and generate receipt
    integration = trapezoidal_integrate(samples)
    receipt = generate_receipt(integration)

    # Write receipt
    RECEIPTS.mkdir(exist_ok=True)
    ts = receipt["ts"]
    receipt_path = RECEIPTS / f"joules-watch-{ts}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

    print(f"\n[joules.py] Receipt written: {receipt_path}")
    print(json.dumps(receipt, indent=2))

    # Check sanity
    if receipt.get("sanity_check") != "OK":
        print(f"WARNING: {receipt.get('sanity_reason')}")
        return False

    return True


def run_selftest():
    """Test integration logic with synthetic power trace."""
    print("[joules.py --selftest] Running synthetic integration test...")

    failures = []

    # Test case 1: Synthetic 10W constant load over 10s
    print("\nTest 1: Constant 10W over 10s (expect ~100J)")
    samples_1 = [(float(i), 10.0) for i in range(11)]  # 0, 1, 2, ..., 10s at 10W
    result_1 = trapezoidal_integrate(samples_1)
    expected_1 = 100.0  # 10W * 10s
    if abs(result_1["joules_total"] - expected_1) > 0.1:
        failures.append(f"Test 1: expected ~{expected_1}J, got {result_1['joules_total']:.2f}J")
        print(f"FAIL: {failures[-1]}")
    else:
        print(f"OK: {result_1['joules_total']:.2f}J (expected {expected_1}J)")

    # Test case 2: Ramp from 0W to 20W (linear)
    print("\nTest 2: Linear ramp 0→20W over 10s (expect ~100J)")
    samples_2 = [(float(i), float(i * 2.0)) for i in range(11)]  # 0,2,4,...,20W
    result_2 = trapezoidal_integrate(samples_2)
    expected_2 = 100.0  # Integral of 2*t from 0 to 10 = t^2 |_0^10 = 100
    if abs(result_2["joules_total"] - expected_2) > 0.1:
        failures.append(f"Test 2: expected ~{expected_2}J, got {result_2['joules_total']:.2f}J")
        print(f"FAIL: {failures[-1]}")
    else:
        print(f"OK: {result_2['joules_total']:.2f}J (expected {expected_2}J)")

    # Test case 3: Mean and peak calculation
    print("\nTest 3: Peak/mean detection (100W peak, variable)")
    samples_3 = [(float(i), float(10.0 if i % 2 == 0 else 100.0)) for i in range(21)]
    result_3 = trapezoidal_integrate(samples_3)
    if result_3["peak_watts"] != 100.0:
        failures.append(f"Test 3: expected peak 100W, got {result_3['peak_watts']}")
        print(f"FAIL: {failures[-1]}")
    else:
        print(f"OK: peak={result_3['peak_watts']}W, mean={result_3['mean_watts']:.1f}W")

    # Test case 4: Sanity ceiling (>450W should flag)
    print("\nTest 4: Sanity ceiling check (>450W)")
    samples_4 = [(float(i), 500.0) for i in range(5)]
    result_4 = trapezoidal_integrate(samples_4)
    receipt_4 = generate_receipt(result_4)
    if receipt_4.get("sanity_check") != "INVALID":
        failures.append(f"Test 4: 500W should fail sanity check, got {receipt_4.get('sanity_check')}")
        print(f"FAIL: {failures[-1]}")
    else:
        print(f"OK: 500W correctly flagged as INVALID")

    # Test case 5: Valid high load (<450W)
    print("\nTest 5: Valid high load check (<450W)")
    samples_5 = [(float(i), 400.0) for i in range(5)]
    result_5 = trapezoidal_integrate(samples_5)
    receipt_5 = generate_receipt(result_5)
    if receipt_5.get("sanity_check") != "OK":
        failures.append(f"Test 5: 400W should pass sanity check, got {receipt_5.get('sanity_check')}")
        print(f"FAIL: {failures[-1]}")
    else:
        print(f"OK: 400W correctly passed sanity check")

    # Write receipt
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    RECEIPTS.mkdir(exist_ok=True)
    receipt_path = RECEIPTS / f"joules-selftest-{ts}.json"

    passed = len(failures) == 0
    receipt = {
        "ticket": "JOULES-SELFTEST",
        "ts": ts,
        "cases_checked": 5,
        "failures": failures,
        "pass": passed,
    }
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

    print(f"\nreceipt: {receipt_path}")
    if passed:
        print("JOULES_SELFTEST_PASS cases=5/5")
    else:
        for f in failures:
            print(f"FAIL: {f}")

    return passed


def main():
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        sys.exit(1)

    if args[0] == "--selftest":
        ok = run_selftest()
        sys.exit(0 if ok else 1)

    if args[0] == "--watch" and len(args) >= 2:
        try:
            duration = float(args[1])
            ok = run_watch(duration)
            sys.exit(0 if ok else 1)
        except ValueError:
            print(f"ERROR: duration must be a number, got {args[1]!r}")
            sys.exit(1)

    print(f"ERROR: unknown args {args}")
    print(__doc__)
    sys.exit(1)


if __name__ == "__main__":
    main()
