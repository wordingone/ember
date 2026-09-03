#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
r"""energy_proxy_logger.py -- the DEGRADED_PROXY energy logger of
docs/domains/governance/spec/ember02-preregistration-v1.md sec5.3.

Emits the frozen sec5.3 `energy` block: an integrated proxy over the run, never a
TDP multiplication, with the boundary flag stated plainly as the program's
permanent declared boundary (operator ruling: no AC wall meter will be bought;
the upgrade is UNPLANNED and nothing conditions on it).

Two legs, each measured independently and each able to be absent:

  GPU leg  -- NVIDIA power.draw sampled at the pinned cadence and integrated
              trapezoidally. Reader chain: pynvml (sub-second capable), then
              nvidia-smi (~1 Hz floor). The chain leg actually used is recorded.

  CPU leg  -- CPU package power counter. There is no portable one: the reader is
              resolved at runtime through an ordered chain and WHICH LEG ANSWERED
              IS RECORDED IN THE RECEIPT. If no leg answers, the CPU package term
              is `null` -- never estimated, never TDP-multiplied -- and "CPU
              package" joins `excluded_components` with an explicit reason.

CPU chain, in order (each probe is executed, and its verdict receipted):
  1. linux_powercap_rapl        /sys/class/powercap/*/energy_uj (native Linux;
                                also the WSL2 path when the guest kernel exposes
                                RAPL -- it does not under the stock WSL2 kernel)
  2. windows_pdh_rapl_package   the Windows Energy Metering Interface counter
                                `\Energy Meter(rapl_package0_pkg)\Energy`, which
                                surfaces the AMD RAPL package domain as a
                                CUMULATIVE energy total
  3. amd_uprof_cli              AMDuProfCLI on PATH (AMD's own package-power path)
  4. ryzen_master_sdk_cli       AMDRyzenMasterCLI --api GetAllInfo, hard-bounded
  -> none                       CPU package UNMEASURED, disclosed

A leg is selected only if its reader is wired AND it returns a live reading, so a
probe can never report "available" while the receipt carries a null term.

Because the RAPL package counter is cumulative, the CPU term is an endpoint
difference rather than a sampled integral: it loses no energy to sampling gaps,
and its coverage is structurally 1.0. The GPU term is genuinely sampled, so
`sample_coverage_fraction` describes the GPU leg -- the leg T-06 can actually
starve.

Sample coverage is the measured fraction of intended samples actually captured;
sec5.3 kills any run below T-06 (0.95) -- an unmetered run is not a frontier point.

Usage:
  python energy_proxy_logger.py --smoke <seconds> [--receipt <path>] [--ticket ID]
  python energy_proxy_logger.py --probe-counters
  python energy_proxy_logger.py --selftest

Stdlib only. No network. CPU-side only -- allocates no GPU memory and starts no
training.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))
sys.path.insert(0, str(HERE))
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
receipt_write = _ember_66ee9e91637922dc_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py  # noqa: E402

# --- Pinned method constants (mirrored into the fixed-prior manifest, sec5.2) ---

SAMPLE_HZ = 1.0
"""Pinned sampling cadence. 1 Hz is the nvidia-smi floor; the pinned value is the
contract, and measured coverage against it is what T-06 adjudicates."""

IDLE_BASELINE_S = 10
"""Pinned idle-baseline interval. Procedure: sample the same counters with no
Ember job resident, immediately before the measured interval, and report the mean
watts per leg. The baseline is REPORTED, never subtracted -- the closed boundary
charges whole-host draw, so subtracting idle would discount charged cost."""

GPU_SANITY_CEILING_W = 450.0
"""RTX 4090 TGP. A sample above this is flagged, not silently clipped."""

RYZEN_CLI = Path(
    r"C:\Program Files\AMD\RyzenMasterSDK\AMDRyzenMasterCLI\bin-prebuilt"
    r"\AMDRyzenMasterCLI.exe"
)
RYZEN_CLI_TIMEOUT_S = 20

PDH_RAPL_PACKAGE_INSTANCE = "rapl_package0_pkg"
PDH_RAPL_ENERGY_COUNTER = rf"\Energy Meter({PDH_RAPL_PACKAGE_INSTANCE})\Energy"
PDH_RAPL_POWER_COUNTER = rf"\Energy Meter({PDH_RAPL_PACKAGE_INSTANCE})\Power"

PWH_TO_JOULES = 3.6e-9
"""The Windows Energy Metering Interface reports absolute energy in picowatt-hours;
1 pWh = 1e-12 W * 3600 s = 3.6e-9 J.

Calibrated on this host rather than assumed, by cross-checking the cumulative
`Energy` counter against the independent `Power` counter (milliwatts) across a
wide dynamic range:

    idle : Power 50.91 W vs Energy-as-pWh 53.48 W
    load : Power 74.71 W vs Energy-as-pWh 80.88 W  (8 busy workers)

Both counters track together across a 24 W swing, which no wrong unit factor
would survive. The residual few percent is a measurement-window artifact of the
calibration harness -- the cumulative reads bracket the power-sampling window, so
dividing that wider energy delta by the narrower stopwatch interval inflates the
rate -- and it does not enter the logger, which times its own endpoint reads."""

BASE_EXCLUDED = ["RAM", "storage", "network", "motherboard", "cooling",
                 "PSU conversion losses"]

ENERGY_BOUNDARY = "DEGRADED_PROXY"
UPGRADE_PATH = "AC_WALL_METERED"

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"

RECEIPT_WORKSTREAM_ID = "EMBER-02B"
"""The workstream this logger's RECEIPTS bind to -- not the one this script binds to.

docs/domains/governance/authority/GOAL.md gives `receipts/ember-restart-3b/` to EMBER-02B exclusively (mode "only"),
while EMBER-02A is "all_except" that prefix. This script lives at
src/ember/governance/scripts/energy_proxy_logger.py, outside the exclusive prefixes, so the file header
is EMBER-02A; the receipts it writes land inside them, and the authority
conservation certificate rejects any artifact whose workstream_id does not match
its path's scope. The pre-registration mandates the path (sec3 R1 Entry:
"dispatch-gate receipts under `receipts/ember-restart-3b/`"), so the workstream
follows the path."""


def _utc_stamp() -> str:
    """ISO-8601 with an explicit offset.

    The compact `%Y%m%dT%H%M%SZ` form does not parse under receipt_check's
    timestamp reader, which silently EXEMPTS the receipt from the post-genesis
    invariant rule instead of enforcing it -- a local pass that CI does not
    share. An unparseable timestamp buying a free pass is the wrong direction to
    fail in, so this writes a form the validator can actually read.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def invariant_sha256() -> str:
    """sha256 of docs/authority/INVARIANT.md -- the F3 stamp every receipt carries (sec5.1 item 9).

    Computed from the file rather than pinned as a literal: a hardcoded copy
    would keep validating after the invariant it claims to stamp had changed.
    """
    return hashlib.sha256((Path(REPO_ROOT) / "docs/authority/INVARIANT.md").read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# CPU package counter resolution -- every leg is probed and its verdict returned
# ---------------------------------------------------------------------------

def _probe_linux_powercap() -> tuple[bool, str, list[str]]:
    """RAPL energy_uj files. Present on bare-metal Linux with the rapl/amd_energy
    module; typically absent under WSL2, whose kernel ships no powercap driver."""
    paths = sorted(glob.glob("/sys/class/powercap/*/energy_uj"))
    readable = []
    for p in paths:
        try:
            with open(p, "r") as fh:
                int(fh.read().strip())
            readable.append(p)
        except (OSError, ValueError):
            continue
    if readable:
        return True, f"readable energy_uj domains: {readable}", readable
    if paths:
        return False, f"powercap domains present but unreadable: {paths}", []
    return False, "/sys/class/powercap exposes no energy_uj domain", []


def _probe_amd_uprof() -> tuple[bool, str, list[str]]:
    exe = shutil.which("AMDuProfCLI") or shutil.which("AMDuProfCLI.exe")
    if exe:
        return True, f"AMDuProfCLI on PATH at {exe}", [exe]
    return False, "AMDuProfCLI not on PATH", []


def _probe_ryzen_master_cli() -> tuple[bool, str, list[str]]:
    """Ryzen Master SDK CLI. The kernel driver may well be loaded, but the CLI is
    an interactive/elevated overclocking sample app: if it cannot answer a
    read-only GetAllInfo within the bound, it is not a sampler."""
    if not RYZEN_CLI.exists():
        return False, f"{RYZEN_CLI} not installed", []
    try:
        r = subprocess.run([str(RYZEN_CLI), "--api", "GetAllInfo"],
                           capture_output=True, text=True,
                           timeout=RYZEN_CLI_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, (f"CLI present but produced no output within "
                       f"{RYZEN_CLI_TIMEOUT_S}s (blocks without an elevated "
                       f"interactive console); unusable as a sampler"), []
    except OSError as exc:
        return False, f"CLI present but not executable: {exc}", []
    text = (r.stdout or "")
    for line in text.splitlines():
        if "power" in line.lower():
            return True, f"GetAllInfo reported a power field: {line.strip()!r}", [line.strip()]
    return False, (f"GetAllInfo exited {r.returncode} with no power field "
                   f"in {len(text)} chars of output"), []


def _powershell() -> str | None:
    return shutil.which("powershell") or shutil.which("powershell.exe")


def _read_pdh_counter(counter: str) -> float | None:
    """One cooked sample from a PDH counter, or None if it cannot be read.

    Deliberately targets a single named instance: a wildcard search for any
    counter matching Power/Energy also matches unrelated NIC power-transition
    counters, which would let the chain report a package counter it does not
    have.
    """
    ps = _powershell()
    if not ps:
        return None
    script = (f"((Get-Counter -Counter '{counter}' -ErrorAction Stop)"
              f".CounterSamples).CookedValue")
    try:
        r = subprocess.run([ps, "-NoProfile", "-Command", script],
                           capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    try:
        return float((r.stdout or "").strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


def _probe_windows_pdh_rapl_package() -> tuple[bool, str, list[str]]:
    """The Windows EMI counter exposing the AMD RAPL package energy domain.

    Availability requires a live reading, not merely the counter's presence in a
    counter set: the set exists on hosts whose hardware publishes no instance.
    """
    if os.name != "nt":
        return False, "not a Windows host", []
    if _powershell() is None:
        return False, "powershell not available to read PDH counters", []
    value = _read_pdh_counter(PDH_RAPL_ENERGY_COUNTER)
    if value is None:
        return False, (f"{PDH_RAPL_ENERGY_COUNTER} exposes no readable instance "
                       f"on this host"), []
    return True, (f"{PDH_RAPL_ENERGY_COUNTER} readable "
                  f"(cumulative picowatt-hours; live read {value:.0f})"), \
           [PDH_RAPL_ENERGY_COUNTER]


CPU_CHAIN = (
    ("linux_powercap_rapl", _probe_linux_powercap),
    ("windows_pdh_rapl_package", _probe_windows_pdh_rapl_package),
    ("amd_uprof_cli", _probe_amd_uprof),
    ("ryzen_master_sdk_cli", _probe_ryzen_master_cli),
)

WIRED_CPU_READERS = frozenset({"linux_powercap_rapl", "windows_pdh_rapl_package"})
"""Legs with a cumulative-energy reader implemented below. A leg that a probe can
detect but that has no reader must never be selected -- otherwise the receipt
would name a counter while carrying a null term."""


def resolve_cpu_counter() -> dict:
    """Execute the whole chain and report which leg (if any) answered.

    The full chain verdict -- including the legs that failed -- is the receipted
    evidence that the CPU term is unmeasured by measurement, not by omission.
    """
    probes = []
    selected = None
    for name, fn in CPU_CHAIN:
        available, detail, handles = fn()
        wired = name in WIRED_CPU_READERS
        probes.append({"leg": name, "available": available, "detail": detail,
                       "reader_wired": wired})
        if available and wired and selected is None:
            selected = {"leg": name, "handles": handles}
    return {
        "selected_counter": selected["leg"] if selected else None,
        "selected_handles": selected["handles"] if selected else [],
        "chain_probed": probes,
    }


def read_cpu_package_joules(resolved: dict) -> float | None:
    """Cumulative package joules from the selected leg, or None when unmeasured.

    Every wired leg reads a counter that is already cumulative, so the run's CPU
    energy is an endpoint difference -- a measured integral the hardware kept, not
    one this process reconstructed from samples.
    """
    leg = resolved.get("selected_counter")
    if leg == "linux_powercap_rapl":
        total_uj = 0
        for path in resolved.get("selected_handles", []):
            try:
                with open(path, "r") as fh:
                    total_uj += int(fh.read().strip())
            except (OSError, ValueError):
                return None
        return total_uj / 1_000_000.0
    if leg == "windows_pdh_rapl_package":
        raw = _read_pdh_counter(PDH_RAPL_ENERGY_COUNTER)
        return None if raw is None else raw * PWH_TO_JOULES
    return None


# ---------------------------------------------------------------------------
# GPU power sampling
# ---------------------------------------------------------------------------

def resolve_gpu_reader() -> dict:
    """pynvml if importable and initializable, else nvidia-smi, else none."""
    probes = []
    try:
        import pynvml  # noqa: F401
        pynvml.nvmlInit()
        pynvml.nvmlShutdown()
        probes.append({"leg": "pynvml", "available": True,
                       "detail": "NVML initialized"})
        return {"selected_counter": "pynvml", "chain_probed": probes}
    except Exception as exc:  # ImportError or any NVMLError
        probes.append({"leg": "pynvml", "available": False,
                       "detail": f"unavailable: {type(exc).__name__}"})
    smi = shutil.which("nvidia-smi") or shutil.which("nvidia-smi.exe")
    if smi:
        probes.append({"leg": "nvidia_smi", "available": True,
                       "detail": f"nvidia-smi at {smi}"})
        return {"selected_counter": "nvidia_smi", "chain_probed": probes}
    probes.append({"leg": "nvidia_smi", "available": False,
                   "detail": "nvidia-smi not on PATH"})
    return {"selected_counter": None, "chain_probed": probes}


def _read_gpu_watts_smi() -> float | None:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=power.draw",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return None
        return float(r.stdout.strip().splitlines()[0])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def _read_gpu_watts(reader: str) -> float | None:
    if reader == "pynvml":
        try:
            import pynvml
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            w = pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0
            pynvml.nvmlShutdown()
            return w
        except Exception:
            return None
    if reader == "nvidia_smi":
        return _read_gpu_watts_smi()
    return None


def trapezoidal_joules(samples: list[tuple[float, float]]) -> float:
    """Integrate (epoch_seconds, watts) samples. Fewer than two samples is zero
    energy, not an extrapolation."""
    if len(samples) < 2:
        return 0.0
    total = 0.0
    for (t0, w0), (t1, w1) in zip(samples, samples[1:]):
        total += (w0 + w1) / 2.0 * (t1 - t0)
    return total


def sample_interval(reader: str, duration_s: float,
                    sample_hz: float = SAMPLE_HZ) -> tuple[list, int]:
    """Sample the GPU leg for duration_s. Returns (samples, intended_count).

    intended_count is computed from the pinned cadence and the wall interval, so
    coverage is measured against the contract rather than against whatever the
    loop happened to achieve.
    """
    interval = 1.0 / sample_hz
    intended = max(1, int(round(duration_s * sample_hz)))
    samples: list[tuple[float, float]] = []
    start = time.time()
    for i in range(intended):
        target = start + i * interval
        now = time.time()
        if target > now:
            time.sleep(target - now)
        w = _read_gpu_watts(reader) if reader else None
        if w is not None:
            samples.append((time.time(), w))
    return samples, intended


# ---------------------------------------------------------------------------
# Energy block assembly (the frozen sec5.3 shape)
# ---------------------------------------------------------------------------

def build_energy_block(gpu_samples, gpu_intended, idle_gpu_w, idle_interval_s,
                       gpu_reader: str | None, cpu_resolved: dict,
                       cpu_pkg_joules: float | None,
                       idle_cpu_pkg_w: float | None = None) -> dict:
    gpu_joules = trapezoidal_joules(gpu_samples)
    coverage = (len(gpu_samples) / gpu_intended) if gpu_intended else 0.0

    excluded = list(BASE_EXCLUDED)
    degradations = []
    if cpu_pkg_joules is None:
        excluded.append("CPU package")
        degradations.append(
            "CPU package power is unmeasured on this host: every leg of the "
            "resolution chain was probed and none answered. The term is null, "
            "never TDP-multiplied and never estimated."
        )
    if gpu_reader is None:
        degradations.append("No NVIDIA power reader resolved; GPU term is zero "
                            "by absence of a counter, not by absence of draw.")

    total = gpu_joules + (cpu_pkg_joules or 0.0)

    peak = max((w for _, w in gpu_samples), default=0.0)
    sanity = "OK" if peak <= GPU_SANITY_CEILING_W else (
        f"FLAG: peak {peak:.2f}W exceeds {GPU_SANITY_CEILING_W}W TGP")

    return {
        "energy_boundary": ENERGY_BOUNDARY,
        "method": {
            "gpu": f"NVML power sampling, integrated over run (reader: {gpu_reader})",
            "cpu": ("CPU package power counter -- resolved leg: "
                    f"{cpu_resolved['selected_counter']}; counter: "
                    f"{cpu_resolved.get('selected_handles') or None}"),
            "sample_hz": SAMPLE_HZ,
            "integration": ("GPU: trapezoidal over (timestamp, watts) samples. "
                            "CPU: endpoint difference of a cumulative hardware "
                            "energy counter (no sampling reconstruction)."),
            "cpu_energy_unit": ("picowatt-hours; joules = raw * 3.6e-9"
                                if cpu_resolved.get("selected_counter")
                                == "windows_pdh_rapl_package" else None),
            "cpu_counter_chain": cpu_resolved["chain_probed"],
        },
        "gpu_joules": gpu_joules,
        "cpu_pkg_joules": cpu_pkg_joules,
        "total_proxy_joules": total,
        "idle_baseline": {
            "gpu_w": idle_gpu_w,
            "cpu_pkg_w": idle_cpu_pkg_w,
            "measured_interval_s": idle_interval_s,
            "procedure": ("counters sampled with no Ember job resident, "
                          "immediately before the measured interval; reported, "
                          "never subtracted"),
        },
        "sample_coverage_fraction": coverage,
        "excluded_components": excluded,
        "boundary_degradations": degradations,
        "uncertainty": {
            "stated_bound_pct": None,
            "basis": ("Integrated 1 Hz GPU power telemetry; quantization and "
                      "sampling-aliasing bounds are not characterized for this "
                      "counter, so no numeric bound is asserted. The CPU package "
                      "term is absent, not bounded."),
        },
        "gpu_sanity_check": sanity,
        "upgrade_path": UPGRADE_PATH,
    }


def run_smoke(duration_s: float, receipt_path: str | None,
              ticket: str) -> tuple[bool, dict]:
    cpu_resolved = resolve_cpu_counter()
    gpu_resolved = resolve_gpu_reader()
    gpu_reader = gpu_resolved["selected_counter"]

    # Idle baseline: both legs, same interval, no Ember job resident.
    idle_cpu_before = read_cpu_package_joules(cpu_resolved)
    idle_t0 = time.time()
    idle_samples, _ = sample_interval(gpu_reader, IDLE_BASELINE_S)
    idle_wall = time.time() - idle_t0
    idle_cpu_after = read_cpu_package_joules(cpu_resolved)
    idle_gpu_w = (sum(w for _, w in idle_samples) / len(idle_samples)
                  if idle_samples else 0.0)
    idle_cpu_pkg_w = (
        None if idle_cpu_before is None or idle_cpu_after is None or idle_wall <= 0
        else (idle_cpu_after - idle_cpu_before) / idle_wall)

    # Measured interval. The CPU endpoint reads bracket the GPU sampling window,
    # so each leg is divided by the wall interval it actually spans.
    cpu_before = read_cpu_package_joules(cpu_resolved)
    t0 = time.time()
    gpu_samples, intended = sample_interval(gpu_reader, duration_s)
    wall = time.time() - t0
    cpu_after = read_cpu_package_joules(cpu_resolved)
    cpu_wall = time.time() - t0
    cpu_joules = (None if cpu_before is None or cpu_after is None
                  else cpu_after - cpu_before)

    energy = build_energy_block(gpu_samples, intended, idle_gpu_w,
                                IDLE_BASELINE_S, gpu_reader, cpu_resolved,
                                cpu_joules, idle_cpu_pkg_w)

    coverage_ok = energy["sample_coverage_fraction"] >= 0.95
    receipt = {
        "ticket": ticket,
        "ts": _utc_stamp(),
        "invariant_sha256": invariant_sha256(),
        "sha_convention": SHA_CONVENTION,
        "schema_version": "ember-energy-proxy-smoke-v1",
        "goal_id": "EMBER-02",
        "workstream_id": RECEIPT_WORKSTREAM_ID,
        "next_executed_outcome": ("EMBER-02 first sufficiently pretrained "
                                  "clean-genesis 3B Ember"),
        "prereg_section": "docs/domains/governance/spec/ember02-preregistration-v1.md sec5.3",
        "purpose": ("R1 entry gate: energy-proxy logger smoke-tested pre-birth "
                    "(sec3 R1 Entry)"),
        "result": "MEASURED",
        "executed": True,
        "gpu_reader_chain": gpu_resolved["chain_probed"],
        "measured_interval_s": wall,
        "cpu_counter_interval_s": cpu_wall,
        "intended_samples": intended,
        "captured_samples": len(gpu_samples),
        "t06_coverage_floor": 0.95,
        "coverage_meets_t06": coverage_ok,
        "coverage_scope": ("sample_coverage_fraction describes the sampled GPU "
                           "leg; the CPU leg is a cumulative-counter endpoint "
                           "difference and cannot lose samples"),
        "energy": energy,
        "host": {
            "platform": sys.platform,
            "python_version": sys.version.split()[0],
        },
        "gpu_allocated": False,
        "training_launched": False,
    }
    if receipt_path:
        Path(receipt_path).parent.mkdir(parents=True, exist_ok=True)
        receipt_write.checked_write(receipt_path, receipt)
    return coverage_ok, receipt


# ---------------------------------------------------------------------------
# Watch mode -- integrate over a certified child's lifetime (R1-E5 wiring)
# ---------------------------------------------------------------------------

WATCH_PIDFILE_WAIT_S = 180.0


def _pid_alive(pid: int) -> bool:
    """Query-only liveness. On Windows, os.kill() is NEVER used: any signal
    other than the two CTRL events TERMINATES the target there, and the CTRL
    events broadcast to the console group (the receipted session-kill class).
    OpenProcess with PROCESS_QUERY_LIMITED_INFORMATION reads state and can
    touch nothing."""
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong(0)
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def samples_path_for(receipt_path: str | Path) -> Path:
    """The raw per-sample sidecar path for a given `run_watch` receipt path:
    same directory, `<receipt-stem>.gpu-samples.jsonl`. A sibling file, not a
    field of the receipt itself, so a consumer of only the aggregate sec5.3
    `energy` block never has to parse it. The `ember-a1-e8-*` per-step energy
    derivation (`tools/ember-restart-3b/a1_energy_apportionment.py`, issue
    #1464) restates this exact naming convention independently rather than
    importing it, the same "two independent transcriptions" discipline
    `a1_e8_evidence.py` documents for its own reopened evidence -- a
    transcription defect surfaces as a missing-samples refusal at first
    contact instead of the derivation module silently trusting this logger's
    internals.
    """
    receipt_path = Path(receipt_path)
    return receipt_path.with_name(receipt_path.stem + ".gpu-samples.jsonl")


def sample_while_pidfile(reader: str, pidfile: Path,
                         sample_hz: float = SAMPLE_HZ,
                         samples_handle=None) -> tuple[list, int, float, str]:
    """Sample the GPU leg on the pinned cadence while the pidfile exists AND
    the pid it names is alive. Returns (samples, intended, wall_s, stop_reason).

    The pidfile's lifetime IS the measured window: the launcher creates it just
    before spawning the certified child and deletes it after the child exits
    (a file operation, never a signal). Pid liveness is the crash backstop --
    a launcher that dies without cleaning up must not leave this loop sampling
    forever. intended is computed from the pinned cadence and the wall the
    window actually spanned, so coverage is measured against the contract.

    When `samples_handle` is given, every captured (timestamp, watts) reading
    is additionally written to it as one JSON line (`{"ts": ..., "watts":
    ...}`) and flushed immediately -- the same per-line durability bar
    `a1_execution.run_dense_a1`'s own telemetry writer holds. This is the raw
    measured-window record issue #1464's per-step energy derivation reopens;
    the idle baseline (sampled separately, before this function is called) is
    never written here, since no training step can fall inside it.
    """
    interval = 1.0 / sample_hz
    samples: list[tuple[float, float]] = []
    start = time.time()
    stop_reason = None
    tick = 0
    while True:
        if not pidfile.exists():
            stop_reason = "pidfile removed (launcher closed the measured window)"
            break
        try:
            pid = int(pidfile.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = None
        if pid is not None and not _pid_alive(pid):
            stop_reason = f"watched pid {pid} exited (crash backstop)"
            break
        target = start + tick * interval
        now = time.time()
        if target > now:
            time.sleep(min(target - now, interval))
        w = _read_gpu_watts(reader) if reader else None
        if w is not None:
            sample_ts = time.time()
            samples.append((sample_ts, w))
            if samples_handle is not None:
                samples_handle.write(json.dumps({"ts": sample_ts, "watts": w}, sort_keys=True) + "\n")
                samples_handle.flush()
        tick += 1
    wall = time.time() - start
    # One read fires at t=0 and one per interval after it, so the contract
    # count over the window is floor(wall*hz)+1 -- never fewer than the loop
    # could have captured, keeping coverage <= 1.0 (the generator and battery
    # both hold sample_coverage_fraction to [0,1]).
    intended = max(1, int(wall * sample_hz) + 1)
    return samples, intended, wall, stop_reason


def run_watch(pidfile_path: str, receipt_path: str, ticket: str) -> int:
    """Sidecar entry: idle baseline BEFORE the child exists, then integrate
    over the pidfile window, then write the receipt. Exit codes: 0 measured
    with coverage >= T-06; 1 measured but below the floor (receipt still
    written -- the battery, not this logger, is the adjudicator); 3 the
    measured window never opened (no receipt: an unopened window has no run
    to attest)."""
    pidfile = Path(pidfile_path)
    cpu_resolved = resolve_cpu_counter()
    gpu_resolved = resolve_gpu_reader()
    gpu_reader = gpu_resolved["selected_counter"]

    # Idle baseline: the launcher spawns this sidecar BEFORE the training
    # child, and holds the child until the marker below appears, so nothing
    # Ember is resident during this interval.
    idle_cpu_before = read_cpu_package_joules(cpu_resolved)
    idle_t0 = time.time()
    idle_samples, _ = sample_interval(gpu_reader, IDLE_BASELINE_S)
    idle_wall = time.time() - idle_t0
    idle_cpu_after = read_cpu_package_joules(cpu_resolved)
    idle_gpu_w = (sum(w for _, w in idle_samples) / len(idle_samples)
                  if idle_samples else 0.0)
    idle_cpu_pkg_w = (
        None if idle_cpu_before is None or idle_cpu_after is None or idle_wall <= 0
        else (idle_cpu_after - idle_cpu_before) / idle_wall)

    marker = Path(receipt_path + ".baseline-done")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(_utc_stamp(), encoding="utf-8")

    waited = 0.0
    while not pidfile.exists():
        if waited >= WATCH_PIDFILE_WAIT_S:
            print(f"energy_proxy_logger: watch window never opened: {pidfile} "
                  f"did not appear within {WATCH_PIDFILE_WAIT_S:.0f}s", file=sys.stderr)
            return 3
        time.sleep(0.5)
        waited += 0.5

    watched_pid = None
    try:
        watched_pid = int(pidfile.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pass

    samples_file_path = samples_path_for(receipt_path)
    samples_handle = None
    samples_open_error = None
    try:
        samples_file_path.parent.mkdir(parents=True, exist_ok=True)
        samples_handle = open(samples_file_path, "w", encoding="utf-8", newline="\n")
    except OSError as error:
        # The raw sample record is a bonus artifact for the downstream
        # per-step energy derivation (issue #1464) -- it must never be able
        # to abort the measured window this receipt is the primary evidence
        # for. A failure to even OPEN the sidecar file degrades to
        # unpersisted sampling (disclosed below); a mid-window write failure
        # is left to propagate, same as any other measured-window defect,
        # rather than silently discarding a partial sample record.
        samples_open_error = repr(error)
    cpu_before = read_cpu_package_joules(cpu_resolved)
    try:
        gpu_samples, intended, wall, stop_reason = sample_while_pidfile(
            gpu_reader, pidfile, samples_handle=samples_handle)
    finally:
        if samples_handle is not None:
            samples_handle.close()
    cpu_after = read_cpu_package_joules(cpu_resolved)
    cpu_joules = (None if cpu_before is None or cpu_after is None
                  else cpu_after - cpu_before)

    energy = build_energy_block(gpu_samples, intended, idle_gpu_w,
                                IDLE_BASELINE_S, gpu_reader, cpu_resolved,
                                cpu_joules, idle_cpu_pkg_w)
    coverage_ok = energy["sample_coverage_fraction"] >= 0.95
    receipt = {
        "ticket": ticket,
        "ts": _utc_stamp(),
        "invariant_sha256": invariant_sha256(),
        "sha_convention": SHA_CONVENTION,
        "schema_version": "ember-energy-proxy-run-v1",
        "goal_id": "EMBER-02",
        "workstream_id": RECEIPT_WORKSTREAM_ID,
        "next_executed_outcome": ("EMBER-02 first sufficiently pretrained "
                                  "clean-genesis 3B Ember"),
        "prereg_section": "docs/domains/governance/spec/ember02-preregistration-v1.md sec5.3",
        "purpose": ("R1 credited-run energy proxy: integrated over the "
                    "certified child's lifetime (sec5.4 leg 5)"),
        "result": "MEASURED",
        "executed": True,
        "gpu_reader_chain": gpu_resolved["chain_probed"],
        "measured_interval_s": wall,
        "cpu_counter_interval_s": wall,
        "intended_samples": intended,
        "captured_samples": len(gpu_samples),
        "t06_coverage_floor": 0.95,
        "coverage_meets_t06": coverage_ok,
        "coverage_scope": ("sample_coverage_fraction describes the sampled GPU "
                           "leg; the CPU leg is a cumulative-counter endpoint "
                           "difference and cannot lose samples"),
        "energy": energy,
        "watch": {
            "pidfile": str(pidfile),
            "watched_pid": watched_pid,
            "stop_reason": stop_reason,
        },
        "energy_step_samples": {
            "path": str(samples_file_path),
            "written": samples_open_error is None,
            "captured": len(gpu_samples),
            "note": samples_open_error,
            "format": ("one JSON object per line, {\"ts\": <unix seconds float>, "
                       "\"watts\": <non-negative float>} -- the raw measured-window "
                       "GPU leg only (never the idle baseline), for the per-step "
                       "energy derivation in "
                       "tools/ember-restart-3b/a1_energy_apportionment.py (issue #1464)"),
        },
        "host": {
            "platform": sys.platform,
            "python_version": sys.version.split()[0],
        },
        "gpu_allocated": True,
        "training_launched": True,
    }
    receipt_write.checked_write(receipt_path, receipt)
    if not coverage_ok:
        print(f"COVERAGE BELOW T-06 FLOOR: "
              f"{energy['sample_coverage_fraction']:.4f} < 0.95", file=sys.stderr)
    return 0 if coverage_ok else 1


# ---------------------------------------------------------------------------
# Selftest -- pure functions only; no counter is required to be present
# ---------------------------------------------------------------------------

def _selftest() -> int:
    failures = []

    j = trapezoidal_joules([(0.0, 100.0), (1.0, 100.0), (2.0, 100.0)])
    if abs(j - 200.0) > 1e-9:
        failures.append(f"constant 100W over 2s should be 200J, got {j}")

    j = trapezoidal_joules([(0.0, 0.0), (2.0, 100.0)])
    if abs(j - 100.0) > 1e-9:
        failures.append(f"ramp 0->100W over 2s should be 100J, got {j}")

    if trapezoidal_joules([(0.0, 100.0)]) != 0.0:
        failures.append("single sample must integrate to 0.0, not extrapolate")
    if trapezoidal_joules([]) != 0.0:
        failures.append("empty sample list must integrate to 0.0")

    blk = build_energy_block([(0.0, 10.0), (1.0, 10.0)], 2, 5.0, 10, "nvidia_smi",
                             {"selected_counter": None, "chain_probed": []}, None)
    if blk["cpu_pkg_joules"] is not None:
        failures.append("unmeasured CPU package must serialize as null")
    if "CPU package" not in blk["excluded_components"]:
        failures.append("unmeasured CPU package must be disclosed as excluded")
    if blk["energy_boundary"] != "DEGRADED_PROXY":
        failures.append("boundary flag must be DEGRADED_PROXY")
    if blk["total_proxy_joules"] != blk["gpu_joules"]:
        failures.append("with no CPU term, total must equal the GPU term")
    if blk["sample_coverage_fraction"] != 1.0:
        failures.append("2 of 2 intended samples must be coverage 1.0")

    partial = build_energy_block([(0.0, 10.0), (1.0, 10.0)], 4, 5.0, 10,
                                 "nvidia_smi",
                                 {"selected_counter": None, "chain_probed": []},
                                 None)
    if abs(partial["sample_coverage_fraction"] - 0.5) > 1e-9:
        failures.append("2 of 4 intended samples must be coverage 0.5")

    hot = build_energy_block([(0.0, 600.0), (1.0, 600.0)], 2, 5.0, 10,
                             "nvidia_smi",
                             {"selected_counter": None, "chain_probed": []}, None)
    if not hot["gpu_sanity_check"].startswith("FLAG"):
        failures.append("peak above the 450W TGP must be flagged, not clipped")

    with_cpu = build_energy_block([(0.0, 10.0), (1.0, 10.0)], 2, 5.0, 10,
                                  "nvidia_smi",
                                  {"selected_counter": "linux_powercap_rapl",
                                   "chain_probed": []}, 25.0)
    if with_cpu["total_proxy_joules"] != with_cpu["gpu_joules"] + 25.0:
        failures.append("total must sum both legs when the CPU term exists")
    if "CPU package" in with_cpu["excluded_components"]:
        failures.append("a measured CPU term must not be listed as excluded")

    # A leg with no wired reader must never be selected: that pairing is exactly
    # what produced a receipt naming a counter while carrying a null term.
    if not set(dict(CPU_CHAIN)) >= WIRED_CPU_READERS:
        failures.append("WIRED_CPU_READERS names a leg absent from CPU_CHAIN")
    for leg in ("amd_uprof_cli", "ryzen_master_sdk_cli"):
        if leg in WIRED_CPU_READERS:
            failures.append(f"{leg} has no reader but is marked wired")
    if read_cpu_package_joules({"selected_counter": "amd_uprof_cli",
                                "selected_handles": []}) is not None:
        failures.append("an unwired leg must read as None, not a fabricated value")

    # Unit conversion: 1 pWh = 3.6e-9 J.
    if abs(1e9 * PWH_TO_JOULES - 3.6) > 1e-12:
        failures.append(f"pWh->J factor wrong: {PWH_TO_JOULES}")

    named = build_energy_block(
        [(0.0, 10.0), (1.0, 10.0)], 2, 5.0, 10, "nvidia_smi",
        {"selected_counter": "windows_pdh_rapl_package",
         "selected_handles": [PDH_RAPL_ENERGY_COUNTER], "chain_probed": []},
        25.0, 40.0)
    if named["idle_baseline"]["cpu_pkg_w"] != 40.0:
        failures.append("measured idle CPU package watts must reach the receipt")
    if named["method"]["cpu_energy_unit"] is None:
        failures.append("the PDH leg must declare its energy unit")

    # issue #1464: the raw per-sample sidecar path is a sibling of the
    # receipt, named by stem -- the exact convention
    # a1_energy_apportionment.py restates independently.
    if samples_path_for(Path("/x/y/energy-proxy-receipt.json")) != Path("/x/y/energy-proxy-receipt.gpu-samples.jsonl"):
        failures.append("samples_path_for must derive a stem-based sibling .gpu-samples.jsonl path")
    if samples_path_for("relative/energy-proxy-receipt.json") != Path("relative/energy-proxy-receipt.gpu-samples.jsonl"):
        failures.append("samples_path_for must accept a str path")

    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("ENERGY_PROXY_LOGGER_SELFTEST_PASS cases=17/17")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--smoke", type=float, metavar="SECONDS",
                    help="run a measured smoke interval of this many seconds")
    ap.add_argument("--watch-pidfile", metavar="PATH",
                    help="sidecar mode: idle baseline, then integrate while "
                         "PATH exists and its pid lives; requires --receipt")
    ap.add_argument("--receipt", help="path to write the smoke receipt")
    ap.add_argument("--ticket", default="R1-ENTRY-ENERGY-SMOKE")
    ap.add_argument("--probe-counters", action="store_true",
                    help="execute the counter chains and print the verdicts")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    if args.probe_counters:
        print(json.dumps({"cpu": resolve_cpu_counter(),
                          "gpu": resolve_gpu_reader()}, indent=2))
        return 0

    if args.watch_pidfile is not None:
        if not args.receipt:
            print("--watch-pidfile requires --receipt", file=sys.stderr)
            return 2
        ticket = ("R1-RUN-ENERGY-PROXY" if args.ticket == "R1-ENTRY-ENERGY-SMOKE"
                  else args.ticket)
        return run_watch(args.watch_pidfile, args.receipt, ticket)

    if args.smoke is not None:
        ok, receipt = run_smoke(args.smoke, args.receipt, args.ticket)
        print(json.dumps(receipt, indent=2))
        if not ok:
            print(f"COVERAGE BELOW T-06 FLOOR: "
                  f"{receipt['energy']['sample_coverage_fraction']:.4f} < 0.95",
                  file=sys.stderr)
        return 0 if ok else 1

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
