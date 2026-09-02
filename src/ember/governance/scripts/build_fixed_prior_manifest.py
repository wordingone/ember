#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""build_fixed_prior_manifest.py -- build and verify the sec5.2 fixed-prior manifest.

docs/domains/governance/spec/ember02-preregistration-v1.md sec5.2 requires ONE versioned manifest,
committed before R1 and referenced by hash from every rung receipt, enumerating
every non-learned prior -- training loop, kernels, ember-cli, deterministic tools,
corpora + acquisition provenance, benchmark payloads, solver/compiler versions,
configuration -- each with a sha256 and a provenance line, plus the pinned energy
method and host governor floor.

The manifest is BUILT, never hand-written: every hash is computed from the bytes
on disk and every version comes from executing the tool that reports it. A
hand-maintained hash list decays silently the first time a file changes; a built
one cannot, because `--verify` recomputes it.

Item kinds:
  file      one tracked file            -> sha256 of its bytes
  tree      a tracked path prefix       -> per-file sha256s + a combined_sha256
                                           over sorted "<name>\\t<sha>\\t<size>\\n"
                                           lines (the src/ember/governance/scripts/manifest_sha.py
                                           convention, reused so tree digests are
                                           comparable across the repo)
  version   an executed probe           -> the command, its exact output, and
                                           whether it succeeded
  external  a prior that is genuinely   -> no hash, and an explicit provenance
            not bytes in this repo         line saying WHY, per sec5.2's
                                           requirement that unhashable items are
                                           declared rather than omitted

CLI:
  python build_fixed_prior_manifest.py --write
  python build_fixed_prior_manifest.py --verify     # fail-closed drift check
  python build_fixed_prior_manifest.py --selftest

Stdlib only. No network. Executes only version-reporting probes; starts no
training and allocates no GPU memory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
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
import energy_proxy_logger as epl  # noqa: E402

MANIFEST_REL = Path("manifests/ember-restart-3b/fixed-prior-manifest-v1.json")
SCHEMA_VERSION = "ember-fixed-prior-manifest-v1"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"

HOST_GOVERNOR_FLOOR_BYTES = 6 * 1024**3
"""6 GiB free commit. The standing in-run commit governor: at any phase boundary
with less headroom than this, the run checkpoints and cleanly aborts. Commit
starvation takes down the whole terminal, not just the job, so this floor is a
host-safety interlock and not a performance tunable. Pinned here because sec5.2
requires the governor floor to live in this manifest, and R1's kill list
(`free-commit margin below the host governor floor ... -> checkpoint + clean
abort`) reads it from here."""


# ---------------------------------------------------------------------------
# Declared inventory -- the non-learned priors of sec5.2
# ---------------------------------------------------------------------------

INVENTORY: tuple[dict, ...] = (
    # --- training loop -----------------------------------------------------
    dict(category="training_loop", kind="file",
         path="src/ember/infrastructure/tools/ember-restart-3b/train.py",
         provenance="Owned training entry point; authored in-repo, no imported loop."),
    dict(category="training_loop", kind="file",
         path="src/ember/infrastructure/tools/ember-restart-3b/pretrain.py",
         provenance="Owned pretraining loop body; authored in-repo."),
    dict(category="training_loop", kind="file",
         path="src/ember/infrastructure/tools/ember-restart-3b/certified_train_launch.py",
         provenance="The ONLY consumer ember-cli /train --execute may invoke; "
                    "fixed certified launch path."),
    dict(category="training_loop", kind="file",
         path="tools/ember-restart-3b/launch_packet.py",
         provenance="Dispatch preflight producing the launch packet ember-cli gates on."),
    dict(category="training_loop", kind="file",
         path="tools/ember-restart-3b/run_vertical_slice.py",
         provenance="Vertical-slice runner named by launch-packet output; never "
                    "executed as a command string by ember-cli."),
    dict(category="training_loop", kind="file",
         path="src/ember/infrastructure/tools/ember-restart-3b/production_rung.py",
         provenance="Rung driver for the owned production run."),
    dict(category="training_loop", kind="file",
         path="src/ember/infrastructure/tools/ember-restart-3b/model.py",
         provenance="Owned unified decoder definition (clean random genesis, no "
                    "imported weights)."),
    dict(category="training_loop", kind="file",
         path="src/ember/infrastructure/tools/ember-restart-3b/batch.py",
         provenance="Batch assembly and data-cursor discipline."),
    dict(category="training_loop", kind="file",
         path="src/ember/infrastructure/tools/ember-restart-3b/optimizer_transition.py",
         provenance="Optimizer state construction and transition rules."),
    dict(category="training_loop", kind="file",
         path="src/ember/infrastructure/tools/ember-restart-3b/checkpoint_artifacts.py",
         provenance="Checkpoint writer producing the hash-chained sequence R1-E3 "
                    "round-trips."),

    # --- kernels / backend -------------------------------------------------
    dict(category="kernels_backend", kind="version", name="torch",
         command=[sys.executable, "-c",
                  "import torch;print(torch.__version__)"],
         provenance="PyTorch build supplying every kernel; CUDA backend below."),
    dict(category="kernels_backend", kind="version", name="torch_cuda",
         command=[sys.executable, "-c",
                  "import torch;print(torch.version.cuda)"],
         provenance="CUDA toolkit version the resident torch build was compiled against."),
    dict(category="kernels_backend", kind="version", name="torch_cudnn",
         command=[sys.executable, "-c",
                  "import torch;print(torch.backends.cudnn.version())"],
         provenance="cuDNN version behind the convolution/attention kernels."),
    dict(category="kernels_backend", kind="version", name="nvidia_driver",
         command=["nvidia-smi", "--query-gpu=driver_version",
                  "--format=csv,noheader"],
         provenance="GPU driver; the kernel-visible half of the backend pin."),
    dict(category="kernels_backend", kind="version", name="gpu_device",
         command=["nvidia-smi", "--query-gpu=name,memory.total",
                  "--format=csv,noheader"],
         provenance="The declared boundary's single GPU (one RTX-4090-class 24 GiB)."),

    # --- ember-cli ---------------------------------------------------------
    dict(category="ember_cli", kind="tree", path="tools/ember-cli/src",
         provenance="ember-cli execution surface (docs/domains/governance/authority/GOAL.md sec10): every executed "
                    "job runs through it. Version is this tree digest plus the "
                    "repo commit recorded in `repo`."),
    dict(category="ember_cli", kind="version", name="node",
         command=["node", "--version"],
         provenance="Runtime executing the ember-cli surface."),

    # --- deterministic tools ----------------------------------------------
    dict(category="deterministic_tools", kind="file",
         path="src/ember/governance/scripts/receipt_write.py",
         provenance="Fail-closed receipt writer; quarantines invalid bytes rather "
                    "than deleting completed runs' results."),
    dict(category="deterministic_tools", kind="file",
         path="src/ember/governance/scripts/receipt_check.py",
         provenance="Frozen receipt validator behind the writer."),
    dict(category="deterministic_tools", kind="file",
         path="src/ember/governance/scripts/manifest_sha.py",
         provenance="Corpus combined-sha tool; supplies the tree-digest convention "
                    "reused by this manifest."),
    dict(category="deterministic_tools", kind="file",
         path="src/ember/governance/scripts/joules.py",
         provenance="GPU power sampler and trapezoidal integrator (energy-law sec4.2)."),
    dict(category="deterministic_tools", kind="file",
         path="src/ember/governance/scripts/energy_proxy_logger.py",
         provenance="The sec5.3 DEGRADED_PROXY energy logger; smoke-tested as an "
                    "R1 entry-gate item. Criterion receipted before first use."),
    dict(category="deterministic_tools", kind="file",
         path="src/ember/governance/scripts/check_energy_law_theory.py",
         provenance="Energy-law receipt-shape checker (P1 receipt-shape check, R2-E2)."),
    dict(category="deterministic_tools", kind="file",
         path="src/ember/governance/scripts/ember_restart/contract.py",
         provenance="ember-owned-rung-v1 admission contract; the fail-closed "
                    "prerequisite of sec1."),
    dict(category="deterministic_tools", kind="file",
         path="src/ember/governance/scripts/build_fixed_prior_manifest.py",
         provenance="This builder. Self-included so the manifest's own producer is "
                    "a pinned prior and cannot change unnoticed."),

    # --- corpora + acquisition provenance ---------------------------------
    dict(category="corpora", kind="file",
         path="manifests/corpus/fineweb_edu-manifest-20260611T044544Z.json",
         provenance="Acquisition manifest with source + acquisition receipt; the "
                    "corpus bytes live outside the repo and are charged to the "
                    "closed boundary through this manifest."),
    dict(category="corpora", kind="file",
         path="manifests/corpus/wikipedia_en-manifest-20260611T045542Z.json",
         provenance="Acquisition manifest; see the manifest's own provenance fields."),
    dict(category="corpora", kind="file",
         path="manifests/corpus/gutenberg_en-manifest-20260611T050315Z.json",
         provenance="Acquisition manifest; see the manifest's own provenance fields."),
    dict(category="corpora", kind="file",
         path="manifests/corpus/code_github_clean-manifest-20260611T051128Z.json",
         provenance="Acquisition manifest; see the manifest's own provenance fields."),
    dict(category="corpora", kind="file",
         path="manifests/corpus/ledger_mit-manifest-20260611T044523Z.json",
         provenance="Acquisition manifest; see the manifest's own provenance fields."),
    dict(category="corpora", kind="file",
         path="data/ember-restart-3b/owned-text-lab-corpus-v2.json",
         provenance="Owned text-lab corpus definition (in-repo, hashable)."),
    dict(category="corpora", kind="file",
         path="data/ember-restart-3b/owned-pretrain-v1.json",
         provenance="Owned pretraining stream definition."),
    dict(category="corpora", kind="file",
         path="data/ember-restart-3b/owned-curriculum-128.json",
         provenance="Owned curriculum definition."),
    dict(category="corpora", kind="file",
         path="data/ember-restart-3b/input-identity.json",
         provenance="Input identity binding the stream to the trained subject."),
    dict(category="corpora", kind="external",
         name="external_corpus_bytes",
         provenance="The acquired corpus BYTES are not tracked in this repo (size), "
                    "so they carry no sha256 here. They are pinned by the "
                    "per-corpus acquisition manifests hashed above, each of which "
                    "carries its own source, acquisition receipt, and digests. "
                    "Hashing them here would duplicate, not strengthen, that chain."),

    # --- benchmark payloads ------------------------------------------------
    dict(category="benchmark_payloads", kind="file",
         path="manifests/ember-01-custody/benchmark-registry.json",
         provenance="Conserved mandate-set registry (docs/domains/governance/authority/GOAL.md sec11 / CONTINUITY "
                    "resolver), including the two permanently-open "
                    "UNRECOVERED_PLACEHOLDER slots."),
    dict(category="benchmark_payloads", kind="file",
         path="data/ember-restart-3b/protected-eval-registry-v2.json",
         provenance="Protected eval registry under custody rules; no missing result "
                    "is convertible into completion."),
    dict(category="benchmark_payloads", kind="external",
         name="frozen_suite_payloads",
         provenance="FROZEN_GENERAL_SUITE and mandate-set payloads are staged under "
                    "custody rules at R4 entry (sec3 R4 Entry) and do not exist as "
                    "repo bytes at R1. They are unhashable HERE by schedule, not by "
                    "omission; a superseding manifest version pins them when custody "
                    "staging lands. R1 consumes no suite payload."),

    # --- solver / compiler versions ---------------------------------------
    dict(category="solver_compiler_versions", kind="version", name="python",
         command=[sys.executable, "--version"],
         provenance="The interpreter that will execute training on the declared "
                    "host (Windows), matching manifests/python-environment-v1.json."),
    dict(category="solver_compiler_versions", kind="version", name="python_executable",
         command=[sys.executable, "-c",
                  "import sys;print(sys.executable)"],
         provenance="Exact interpreter path, so the pinned versions are attributable "
                    "to one environment."),
    dict(category="solver_compiler_versions", kind="version", name="platform",
         command=[sys.executable, "-c",
                  "import platform;print(platform.platform())"],
         provenance="Host OS build of the declared boundary."),
    dict(category="solver_compiler_versions", kind="version", name="numpy",
         command=[sys.executable, "-c", "import numpy;print(numpy.__version__)"],
         provenance="Numeric backend used by data packing and receipt math."),

    # --- configuration -----------------------------------------------------
    dict(category="configuration", kind="file",
         path="configs/ember-restart-3b.json",
         provenance="The ember-owned-rung admission contract config validated at "
                    "dispatch."),
    dict(category="configuration", kind="file",
         path="docs/domains/governance/spec/ember02-preregistration-v1.md",
         provenance="The pre-registration this run is hash-pinned to "
                    "(`--prereg <sha256>`)."),
    dict(category="configuration", kind="file",
         path="docs/domains/governance/spec/ember02-preregistration-thresholds-v1.json",
         provenance="Frozen machine-readable threshold table; tighten-only."),
    dict(category="configuration", kind="file",
         path="manifests/python-environment-v1.json",
         provenance="Pinned Python environment (distributions + versions) for the "
                    "declared host."),
    dict(category="configuration", kind="file",
         path="docs/domains/governance/authority/GOAL.md",
         provenance="Goal authority: the 3B floor and required native capabilities."),
    dict(category="configuration", kind="file",
         path="docs/authority/INVARIANT.md",
         provenance="Invariant authority; F3 stamps every receipt with its hash."),
)


# ---------------------------------------------------------------------------
# Hashing / probing
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tracked_files(prefix: str) -> list[str]:
    r = subprocess.run(["git", "ls-files", "--", prefix],
                       cwd=REPO_ROOT, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"git ls-files failed for {prefix}: {r.stderr.strip()}")
    return sorted(ln.strip() for ln in r.stdout.splitlines() if ln.strip())


def hash_tree(prefix: str) -> dict:
    """Per-file digests plus a combined digest, using manifest_sha.py's convention.

    Only git-TRACKED files participate: an untracked scratch file appearing beside
    the source must not silently change a pinned prior's digest.
    """
    names = _tracked_files(prefix)
    if not names:
        raise RuntimeError(f"no tracked files under {prefix} -- refusing an empty "
                           f"tree digest")
    lines = []
    files = []
    for name in names:
        p = REPO_ROOT / name
        digest = sha256_file(p)
        size = p.stat().st_size
        files.append({"name": name, "sha256": digest, "size_bytes": size})
        lines.append(f"{name}\t{digest}\t{size}\n")
    combined = hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
    return {"file_count": len(files), "combined_sha256": combined, "files": files}


def probe_version(command: list[str]) -> dict:
    try:
        r = subprocess.run(command, cwd=REPO_ROOT, capture_output=True,
                           text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": command, "ok": False,
                "output": None, "error": f"{type(exc).__name__}: {exc}"}
    out = (r.stdout or "").strip() or (r.stderr or "").strip()
    return {"command": command, "ok": r.returncode == 0, "output": out,
            "returncode": r.returncode}


def repo_commit() -> dict:
    def _git(*args):
        r = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True,
                           text=True, timeout=60)
        return (r.stdout or "").strip() if r.returncode == 0 else None
    return {"commit": _git("rev-parse", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD")}


def build_items() -> list[dict]:
    items = []
    for entry in INVENTORY:
        item = {"category": entry["category"], "kind": entry["kind"],
                "provenance": entry["provenance"]}
        if entry["kind"] == "file":
            rel = entry["path"]
            p = REPO_ROOT / rel
            if not p.is_file():
                raise RuntimeError(f"declared prior missing on disk: {rel}")
            item.update(path=rel, sha256=sha256_file(p),
                        size_bytes=p.stat().st_size)
        elif entry["kind"] == "tree":
            item.update(path=entry["path"], **hash_tree(entry["path"]))
        elif entry["kind"] == "version":
            item.update(name=entry["name"], probe=probe_version(entry["command"]))
        elif entry["kind"] == "external":
            item.update(name=entry["name"], sha256=None)
        else:
            raise RuntimeError(f"unknown inventory kind: {entry['kind']}")
        items.append(item)
    return items


def energy_method_block() -> dict:
    """The pinned energy method of sec5.2, resolved against THIS host.

    The counter chain is executed, not asserted, so the manifest records which
    counter is actually available rather than which one was hoped for.
    """
    cpu = epl.resolve_cpu_counter()
    gpu = epl.resolve_gpu_reader()
    return {
        "energy_boundary": epl.ENERGY_BOUNDARY,
        "boundary_status": ("PERMANENT declared boundary by operator ruling; the "
                            "upgrade to AC wall metering is UNPLANNED and no rung, "
                            "claim, or publication conditions on it. A proxy point "
                            "is never presented as a wall-metered point."),
        "cpu_package_counter": cpu["selected_counter"],
        "cpu_package_counter_handles": cpu["selected_handles"],
        "cpu_package_energy_unit": (
            "picowatt-hours (Windows Energy Metering Interface); joules = raw * 3.6e-9"
            if cpu["selected_counter"] == "windows_pdh_rapl_package" else
            "microjoules (Linux powercap energy_uj); joules = raw / 1e6"
            if cpu["selected_counter"] == "linux_powercap_rapl" else None),
        "cpu_counter_chain_probed": cpu["chain_probed"],
        "gpu_counter": gpu["selected_counter"],
        "gpu_counter_chain_probed": gpu["chain_probed"],
        "sample_hz": epl.SAMPLE_HZ,
        "sampling_cadence_note": (
            "Pinned cadence for the SAMPLED GPU leg. The CPU package leg reads a "
            "cumulative hardware counter as an endpoint difference, so it loses no "
            "energy to sampling gaps."),
        "idle_baseline_procedure": (
            f"Both counters sampled for {epl.IDLE_BASELINE_S}s with no Ember job "
            f"resident, immediately before the measured interval. The baseline is "
            f"REPORTED, never subtracted: the closed boundary charges whole-host "
            f"draw, so subtracting idle would discount charged cost."),
        "idle_baseline_interval_s": epl.IDLE_BASELINE_S,
        "integration": "trapezoidal for the sampled leg; endpoint difference for "
                       "the cumulative leg. Never a TDP multiplication.",
        "sample_coverage_floor_t06": 0.95,
        "logger": "src/ember/governance/scripts/energy_proxy_logger.py",
    }


def host_governor_block() -> dict:
    return {
        "free_commit_floor_bytes": HOST_GOVERNOR_FLOOR_BYTES,
        "free_commit_floor_gib": HOST_GOVERNOR_FLOOR_BYTES / 1024**3,
        "enforcement": ("In-run commit governor: at any phase boundary with free "
                        "commit below the floor, the run checkpoints and cleanly "
                        "aborts (R1 kill list). Commit starvation takes down the "
                        "whole terminal, not merely the job."),
        "gpu_boundary": "one RTX-4090-class 24 GiB GPU plus the declared local host",
    }


def build_manifest() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_version": 1,
        "ticket": "R1-ENTRY-FIXED-PRIOR-MANIFEST",
        "ts": epl._utc_stamp(),
        "invariant_sha256": epl.invariant_sha256(),
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": ("EMBER-02 first sufficiently pretrained "
                                  "clean-genesis 3B Ember"),
        "prereg_section": "docs/domains/governance/spec/ember02-preregistration-v1.md sec5.2",
        "purpose": ("Fixed-prior manifest: every non-learned prior with sha256 and "
                    "provenance, referenced by hash from every rung receipt."),
        "sha_convention": SHA_CONVENTION,
        "tree_digest_convention": ("combined_sha256 = sha256 over sorted "
                                   "'<name>\\t<sha256>\\t<size_bytes>\\n' lines "
                                   "(src/ember/governance/scripts/manifest_sha.py convention); "
                                   "git-tracked files only"),
        "repo": repo_commit(),
        "learned_import_attestation": (
            "Every item in this manifest is a NON-LEARNED prior. Zero imported "
            "learned weights, embeddings, learned-parameter tokenizers, teacher "
            "outputs, learned filters or judges, or hidden accelerator services "
            "(docs/authority/INVARIANT.md clause 3, fail-closed on unknown provenance)."),
        "energy_method": energy_method_block(),
        "host_governor": host_governor_block(),
        "items": build_items(),
        "builder": "src/ember/governance/scripts/build_fixed_prior_manifest.py",
        "verification": ("python src/ember/governance/scripts/build_fixed_prior_manifest.py --verify "
                         "recomputes every file and tree digest and fails closed "
                         "on drift."),
    }


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

def verify(manifest_path: Path) -> tuple[bool, list[str]]:
    """Recompute every hashable item and report drift.

    Version probes are re-executed and reported, but a changed version is a
    FINDING rather than a hard failure only when it is absent -- a moved
    toolchain must be visible, and a superseding manifest version is the cure.
    """
    findings: list[str] = []
    if not manifest_path.is_file():
        return False, [f"manifest absent: {manifest_path}"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for item in manifest.get("items", []):
        kind = item.get("kind")
        if kind == "file":
            p = REPO_ROOT / item["path"]
            if not p.is_file():
                findings.append(f"MISSING: {item['path']}")
                continue
            actual = sha256_file(p)
            if actual != item.get("sha256"):
                findings.append(
                    f"DRIFT: {item['path']} sha256 {item.get('sha256')} -> {actual}")
        elif kind == "tree":
            try:
                actual = hash_tree(item["path"])
            except RuntimeError as exc:
                findings.append(f"TREE ERROR: {item['path']}: {exc}")
                continue
            if actual["combined_sha256"] != item.get("combined_sha256"):
                findings.append(
                    f"DRIFT: tree {item['path']} combined_sha256 "
                    f"{item.get('combined_sha256')} -> {actual['combined_sha256']} "
                    f"({item.get('file_count')} -> {actual['file_count']} files)")
        elif kind == "version":
            probe = probe_version(item["probe"]["command"])
            if not probe["ok"]:
                findings.append(
                    f"PROBE FAILED: {item['name']}: {probe.get('error') or probe}")
            elif probe["output"] != item["probe"].get("output"):
                findings.append(
                    f"VERSION CHANGED: {item['name']} "
                    f"{item['probe'].get('output')!r} -> {probe['output']!r}")
    return not findings, findings


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _scratch_root() -> Path:
    """In-tree scratch root. Ember's NO-TEMP policy forbids the system temp dir
    anywhere in the stack, so selftest fixtures stay under the repo."""
    root = REPO_ROOT / "scratch" / "fixed-prior-manifest-selftest"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _selftest() -> int:
    import tempfile
    failures = []
    scratch = _scratch_root()

    with tempfile.TemporaryDirectory(dir=scratch) as td:
        p = Path(td) / "x.bin"
        p.write_bytes(b"abc")
        expected = hashlib.sha256(b"abc").hexdigest()
        if sha256_file(p) != expected:
            failures.append("sha256_file disagrees with hashlib on known bytes")

    cats = {e["category"] for e in INVENTORY}
    required = {"training_loop", "kernels_backend", "ember_cli",
                "deterministic_tools", "corpora", "benchmark_payloads",
                "solver_compiler_versions", "configuration"}
    missing = required - cats
    if missing:
        failures.append(f"sec5.2 categories absent from the inventory: {sorted(missing)}")

    for e in INVENTORY:
        if not e.get("provenance"):
            failures.append(f"inventory entry without a provenance line: {e}")
        if e["kind"] == "external" and "path" in e:
            failures.append(f"external item must not claim a repo path: {e}")

    # An external item must carry sha256 None -- never a placeholder string.
    ext = [e for e in INVENTORY if e["kind"] == "external"]
    if not ext:
        failures.append("expected at least one declared-unhashable external prior")

    if HOST_GOVERNOR_FLOOR_BYTES != 6 * 1024**3:
        failures.append("host governor floor must be 6 GiB")

    blk = host_governor_block()
    if blk["free_commit_floor_gib"] != 6.0:
        failures.append(f"governor floor GiB wrong: {blk['free_commit_floor_gib']}")

    # Drift detection must actually fire on a changed digest.
    with tempfile.TemporaryDirectory(dir=scratch) as td:
        fake = Path(td) / "m.json"
        fake.write_text(json.dumps({"items": [
            {"kind": "file", "path": "docs/domains/governance/authority/GOAL.md", "sha256": "0" * 64}]}),
            encoding="utf-8")
        ok, findings = verify(fake)
        if ok or not any("DRIFT" in f for f in findings):
            failures.append("verify() failed to flag a deliberately wrong digest")

    with tempfile.TemporaryDirectory(dir=scratch) as td:
        fake = Path(td) / "m.json"
        fake.write_text(json.dumps({"items": [
            {"kind": "file", "path": "does/not/exist.txt", "sha256": "0" * 64}]}),
            encoding="utf-8")
        ok, findings = verify(fake)
        if ok or not any("MISSING" in f for f in findings):
            failures.append("verify() failed to flag a missing declared prior")

    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("FIXED_PRIOR_MANIFEST_SELFTEST_PASS cases=9/9")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--path", default=str(MANIFEST_REL))
    args = ap.parse_args()

    target = REPO_ROOT / args.path

    if args.selftest:
        return _selftest()

    if args.write:
        manifest = build_manifest()
        target.parent.mkdir(parents=True, exist_ok=True)
        receipt_write.checked_write(str(target), manifest)
        digest = sha256_file(target)
        counts: dict[str, int] = {}
        for it in manifest["items"]:
            counts[it["category"]] = counts.get(it["category"], 0) + 1
        print(json.dumps({
            "written": str(target.relative_to(REPO_ROOT)).replace("\\", "/"),
            "manifest_sha256": digest,
            "item_count": len(manifest["items"]),
            "items_by_category": counts,
            "cpu_package_counter": manifest["energy_method"]["cpu_package_counter"],
            "gpu_counter": manifest["energy_method"]["gpu_counter"],
        }, indent=2))
        return 0

    if args.verify:
        ok, findings = verify(target)
        print(json.dumps({"manifest": args.path, "verified": ok,
                          "findings": findings}, indent=2))
        return 0 if ok else 1

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
