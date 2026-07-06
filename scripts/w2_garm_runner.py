"""w2_garm_runner.py -- issue #113: W2 G-arm runner (grow rung-1 terminal to
2x FF, train per preregistration, emit the frozen dump contract).

Authority precedence (per #113's own framing): docs/spec/w2-scale-
preregistration-v1.md governs all training parameters and arm semantics;
docs/spec/rung2-grow-spec-v1.md governs the rung-2 grow shape (strict
doubling, fp_diff tolerance); #113 adds the execution contract around both.
Divergences are reported (see the coordination mail to team-lead), never
silently reconciled.

THIS FILE implements acceptance criterion (a) ONLY: a CPU dry-run mode
proving the full sequence minus the training leg. The real GPU leg
(acceptance (b)) is maintainer-window-gated per issue #113 and is
deliberately NOT implemented here -- `--live` refuses unconditionally with
a pointer to the gated window, mirroring w1_collapse_control_run.py's
MAINTAINER_WINDOW_ENV pattern (never fabricate a live run from a builder
session).

Grow operator (reuse, never reimplement): scripts/growth_refutation/
capacity.py's net2net_grow. NOTE ON PROVENANCE: this file did not exist
anywhere in the public wordingone/ember repo before this change (no git
history). Landed byte-for-byte from previously-uncommitted local scratch on
the maintainer's work tree; provenance anchor = sha256 in the grow receipt
(capacity_py_sha256) -- this is the first time it is committed to any
tracked repo. Reported to team-lead before landing; see the coordination
mail for the full divergence report (this file, the event-log convention,
and the rung-2 dossier citation all diverge between what #113/#108 assume
exists and what is actually committed anywhere).

Launch gates (both imported, both hard-refuse):
  (a) W2 sec.4 decontamination gate -- scripts/w2_heldout/launch_gate.py's
      refuse_or_pass, imported and exercised against ISOLATED toy fixtures
      (never the shared receipts/ember-c-scale default glob -- a fabricated
      dry-run receipt must never be mistaken for a real decontamination
      result by a future real launch attempt).
  (b) Governed-fit gate -- governor.py's env_limits()/preflight() encode the
      real policy (VRAM fraction cap, free-VRAM margin assert, fail-closed,
      never fix-forward) but preflight() itself hard-imports torch.cuda and
      is therefore uncallable in a CPU-only dry run. _governed_fit_gate()
      below reuses env_limits() (the real, CPU-safe policy constants) and
      mirrors preflight()'s exact refusal condition/receipt shape against an
      INJECTED free_gb (disclosed as governed_fit_dry_run_simulated=true) --
      this is a CPU-safe test harness around the existing policy, not a new
      policy.

Event-log convention: no "C11 runner" / state/runs/active-runs.jsonl
producer exists anywhere (public or local tree; grepped both). The closest
real precedent is heartbeat_runner.py's append+fsync JSONL idiom (different
states, different path). append_run_event() below is NEW code (flagged as
such) implementing the exact five states team-lead specified (started,
pid_assigned, heartbeat, completed, failed, refused) at
state/runs/active-runs.jsonl, modeled on heartbeat_runner.py's write idiom.

Dump contract (binding, #108 coordination ruling): config.json nested like
configs/v0-pretrain-config.json (model.{vocab,hidden,layers,heads,ff,seq,
tied_embeddings,norm_placement}, objective.mtp_aux_heads.n_heads -- ff
carries the GROWN value) + state_dict_shape_manifest.json (flat key->shape,
RealW1Model naming per #113's own text: model.embed_tokens.weight,
model.layers.<n>.mlp.{gate,up,down}_proj.weight, mtp_heads.<k>.weight,
lm_head.weight). The manifest is HAND-ASSEMBLED from the post-grow config,
never a raw dump of model.state_dict() -- a raw state_dict() of a
tie_word_embeddings=True transformers LlamaForCausalLM still emits a
separate lm_head.weight key (verified directly: tied weights share storage
but PyTorch's named_parameters() walk still lists both names), which would
violate #108's own cross_validate() rule ("model.tied_embeddings=true but
manifest carries a separate lm_head.weight key" -> DerivationError). The
manifest therefore omits lm_head.weight whenever tied_embeddings is true,
by construction, matching the contract #108 actually checks rather than
whatever raw PyTorch would emit.

Acceptance (a) verification: scripts/w2_derive_s_config.py's derive_s_config
+ refuse_or_pass are imported and run directly against this run's dump
(never reimplemented) -- both must succeed clean for this runner's own
dry-run receipt to claim PASS.

Rails: CPU-only (run with CUDA_VISIBLE_DEVICES="" -- also asserted at
startup); no capability-side model import in gate/dump code (governor.py
and launch_gate.py are imported only for their gate logic, never wired into
the dump); LF line endings; no commits performed by this script.

Usage:
  CUDA_VISIBLE_DEVICES= python scripts/w2_garm_runner.py --dry-run \
      --out-dir scratch/w2-garm/dry-run/<label>

  python scripts/w2_garm_runner.py --live   # refuses unconditionally here
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "growth_refutation"))
sys.path.insert(0, os.path.join(HERE, "w2_heldout"))

import capacity  # scripts/growth_refutation/capacity.py -- reused, not edited
import launch_gate  # scripts/w2_heldout/launch_gate.py -- reused, not edited
import governor  # scripts/governor.py -- reused, not edited
import w2_derive_s_config  # issue #108's tool -- reused, not edited

ISSUE_REF = "#113"
SPEC_REF = "docs/spec/w2-scale-preregistration-v1.md"
RUNG2_SPEC_REF = "docs/spec/rung2-grow-spec-v1.md"

RECEIPT_DIR = os.path.join(REPO, "receipts", "ember-c-scale")
EVENT_LOG_PATH = os.path.join(REPO, "state", "runs", "active-runs.jsonl")

# Rung-2 spec's own frozen fp_diff tolerance (tighter than capacity.py's own
# default of 1e-3 -- rung-1 measured 2.38e-6, this run's toy scale measured
# below).
GROW_FP_DIFF_TOL = 1e-4

MAINTAINER_WINDOW_ENV = "EMBER_W2_MAINTAINER_WINDOW_CONFIRMED"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _assert_cpu_only() -> None:
    """Fail loudly unless CUDA_VISIBLE_DEVICES was EXPLICITLY cleared -- the
    CPU-only rail ("set CUDA_VISIBLE_DEVICES='' for every python invocation")
    is a launch precondition, not a suggestion. An unset env var is NOT the
    same as an explicitly-cleared one: the first cut of this check accepted
    both (`cvd not in ("", None)`), which meant a caller who simply forgot to
    export the var passed silently -- caught by testing the negative case
    (invoking without the env var set) before landing, not assumed safe."""
    cvd = os.environ.get("CUDA_VISIBLE_DEVICES")
    if cvd != "":
        raise SystemExit(
            f"W2_GARM_RAIL_VIOLATION: CUDA_VISIBLE_DEVICES={cvd!r} (must be "
            "explicitly set to the empty string, not merely unset) -- this "
            "runner is CPU-only until the maintainer window opens (issue "
            "#113 acceptance (b)); re-invoke with CUDA_VISIBLE_DEVICES=''")


def _write_json(path: str, obj: dict) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# ---------------------------------------------------------------------------
# CONVENTION (binding for every receipt this module writes, and for anyone
# extending it): a receipt's JSON content NEVER carries an absolute
# filesystem path. Absolute paths root at wherever this script happened to
# be checked out, which can embed the caller's local directory naming (e.g.
# a per-session sandbox path) -- exactly how a founder-name substring leaked
# into two committed receipts on the first cut of this file (repo-guard
# caught it; see the coordination mail). Every path written into a receipt
# -- directly as a field, or indirectly via a reason string returned by an
# imported gate function that echoes whatever path it was called with --
# must go through _repo_relpath() or _scrub_absolute_paths() first. Actual
# filesystem operations (open/os.makedirs) still use real absolute paths;
# only the JSON OUTPUT is scrubbed.
# ---------------------------------------------------------------------------

def _repo_relpath(path: str) -> str:
    """Repo-relative, forward-slashed path for receipt fields."""
    rel = os.path.relpath(os.path.abspath(path), REPO)
    return rel.replace(os.sep, "/")


def _scrub_absolute_paths(text: str) -> str:
    """Strips this repo's absolute root prefix out of a string before it is
    embedded in a receipt. Covers reason strings returned by imported gate
    functions (launch_gate.refuse_or_pass, w2_derive_s_config.refuse_or_pass)
    that echo whatever absolute path they were called with verbatim -- the
    caller has no control over that formatting, so scrubbing the known
    absolute prefix is the reuse-safe fix (never edit the imported gate to
    change its message)."""
    if not text:
        return text
    normalized = text.replace("\\", "/")
    repo_fwd = REPO.replace("\\", "/")
    return normalized.replace(repo_fwd + "/", "")


# ---------------------------------------------------------------------------
# Event log -- state/runs/active-runs.jsonl. NEW convention (no existing
# producer of this exact shape found anywhere -- see module docstring).
# Append+fsync per line, modeled on heartbeat_runner.py's tick-writer idiom.
# ---------------------------------------------------------------------------

EVENT_STATES = ("started", "pid_assigned", "heartbeat", "completed", "failed", "refused")


def append_run_event(run_id: str, event: str, extra: dict | None = None) -> None:
    if event not in EVENT_STATES:
        raise ValueError(f"unknown event state {event!r}, expected one of {EVENT_STATES}")
    row = {"ts": _ts(), "run_id": run_id, "issue": ISSUE_REF, "event": event}
    if extra:
        row.update(extra)
    d = os.path.dirname(EVENT_LOG_PATH)
    os.makedirs(d, exist_ok=True)
    with open(EVENT_LOG_PATH, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


# ---------------------------------------------------------------------------
# Toy G-arm model -- transformers.LlamaForCausalLM chosen deliberately: its
# native attribute layout (self.model.layers[i].mlp.{gate,up,down}_proj)
# satisfies capacity.py's _get_transformer_layers(model.model.layers) with
# zero custom model code, and its state_dict naming (model.embed_tokens.
# weight, model.layers.<n>.mlp.*, lm_head.weight) matches #113's own named
# manifest convention directly (verified: sanity-probed shapes before
# wiring, not assumed).
# ---------------------------------------------------------------------------

TOY_CONFIG = {
    "vocab": 64,
    "hidden": 16,
    "layers": 2,
    "heads": 2,
    "ff": 32,          # PRE-grow width
    "seq": 8,
    "tied_embeddings": True,
    "norm_placement": "pre_rmsnorm",  # Llama's actual placement -- not a guess
    "n_mtp": 2,
}


class _TokStub:
    """net2net_grow only ever reads tokenizer.vocab_size (verified by
    reading capacity.py's _probe_batch) -- no real tokenizer needed for a
    shape-manifest-only dry run."""

    def __init__(self, vocab_size: int):
        self.vocab_size = vocab_size


def build_toy_model(cfg: dict):
    from transformers import LlamaConfig, LlamaForCausalLM
    import torch

    conf = LlamaConfig(
        vocab_size=cfg["vocab"], hidden_size=cfg["hidden"],
        intermediate_size=cfg["ff"], num_hidden_layers=cfg["layers"],
        num_attention_heads=cfg["heads"], num_key_value_heads=cfg["heads"],
        max_position_embeddings=cfg["seq"],
        tie_word_embeddings=cfg["tied_embeddings"])
    model = LlamaForCausalLM(conf)
    # mtp_heads: NOT touched by net2net_grow (which only walks
    # model.model.layers's MLP blocks) -- attached as an ordinary submodule,
    # same per-head shape convention as w1_collapse_control_run.RealW1Model
    # (Linear(hidden, vocab, bias=False), one per n_mtp).
    model.mtp_heads = torch.nn.ModuleList(
        [torch.nn.Linear(cfg["hidden"], cfg["vocab"], bias=False)
         for _ in range(cfg["n_mtp"])])
    return model


# ---------------------------------------------------------------------------
# Component 1: grow step
# ---------------------------------------------------------------------------

def run_grow_step(run_id: str, out_dir: str) -> dict:
    model = build_toy_model(TOY_CONFIG)
    tok = _TokStub(TOY_CONFIG["vocab"])
    old_ff = model.model.layers[0].mlp.gate_proj.out_features

    model, tok, metrics = capacity.net2net_grow(
        model, tok, round_idx=1, tier=2,  # tier=2: rung-2, per rung2-grow-spec-v1.md
        expand_frac=1.0,  # strict doubling (rung2-grow-spec-v1.md: ff 16384->32768 pattern)
        assert_tol=GROW_FP_DIFF_TOL, seed=20260705)
    new_ff = model.model.layers[0].mlp.gate_proj.out_features

    assert new_ff == old_ff * 2, f"expected strict doubling, got {old_ff}->{new_ff}"

    receipt = {
        "ticket": "ISSUE-113-W2-GARM-GROW",
        "ts": _ts(),
        "run_id": run_id,
        "dry_run": True,
        "is_real_lineage": False,
        "operator": {
            "module": "scripts/growth_refutation/capacity.py",
            "function": "net2net_grow",
            "provenance": (
                "landed byte-for-byte from previously-uncommitted local "
                "scratch on the maintainer's work tree; never committed "
                "anywhere before this PR -- see coordination mail to "
                "team-lead"),
            "capacity_py_sha256": sha256_file(
                os.path.join(HERE, "growth_refutation", "capacity.py")),
        },
        "input_shape": {"ff": old_ff, "hidden": TOY_CONFIG["hidden"],
                         "layers": TOY_CONFIG["layers"]},
        "output_shape": {"ff": new_ff, "hidden": TOY_CONFIG["hidden"],
                          "layers": TOY_CONFIG["layers"]},
        "strict_doubling_verified": new_ff == old_ff * 2,
        "identity_preservation": {
            "gate": "net2net_grow's internal GATE_A (fp64 forward pre/post on "
                    "the fixed probe batch)",
            "fp_diff_tolerance_source": f"{RUNG2_SPEC_REF} (fp_diff <= 1e-4)",
            "fp_diff_tolerance": GROW_FP_DIFF_TOL,
            "measured": metrics,
            "passed": metrics["net2net_fp32_max_abs_diff"] < GROW_FP_DIFF_TOL,
        },
    }
    path = os.path.join(RECEIPT_DIR, f"w2-garm-grow-{run_id}.json")
    _write_json(path, receipt)
    return {"model": model, "tok": tok, "receipt": receipt, "receipt_path": path,
            "grown_ff": new_ff}


# ---------------------------------------------------------------------------
# Component 2a: W2 sec.4 decontamination launch gate -- exercised in BOTH
# directions against ISOLATED toy fixtures (never the shared default glob).
# ---------------------------------------------------------------------------

def run_decontam_gate_selftest(run_id: str, out_dir: str) -> dict:
    import numpy as np

    fixtures_dir = os.path.join(out_dir, "gate-fixtures", "decontam")
    os.makedirs(fixtures_dir, exist_ok=True)

    seq = 4
    rows = np.array([[1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12, 13, 14, 15]],
                     dtype=np.int64)
    xs, ys = rows[:, :seq], rows[:, 1:seq + 1]
    sha = hashlib.sha256(np.concatenate([xs, ys], axis=1).tobytes()).hexdigest()

    batch_path = os.path.join(fixtures_dir, "toy-heldout-batch.npy")
    np.save(batch_path, rows)

    def _write_receipt(name, *, pass_field=True, confirmed=0):
        p = os.path.join(fixtures_dir, name)
        _write_json(p, {"pass": pass_field, "seq": seq, "batch_sha256": sha,
                         "contamination_recheck": {"confirmed_non_self_matches": confirmed}})
        return p

    allow_receipt = _write_receipt("w2-heldout-decontam-toy-ALLOW.json",
                                    pass_field=True, confirmed=0)
    refuse_receipt = _write_receipt("w2-heldout-decontam-toy-REFUSE.json",
                                     pass_field=True, confirmed=42)

    allow_result = launch_gate.refuse_or_pass(batch_path=batch_path,
                                               receipt_path=allow_receipt)
    refuse_result = launch_gate.refuse_or_pass(batch_path=batch_path,
                                                receipt_path=refuse_receipt)

    receipt = {
        "ticket": "ISSUE-113-W2-GARM-GATE-DECONTAM",
        "ts": _ts(),
        "run_id": run_id,
        "gate": "w2_heldout/launch_gate.py:refuse_or_pass (imported, not reimplemented)",
        "isolation_note": "toy fixtures under scratch out-dir; explicit "
                           "receipt_path passed so the shared receipts/"
                           "ember-c-scale/w2-heldout-decontam-*.json default "
                           "glob is never touched by this dry run",
        "allow_case": {"allowed": allow_result.allowed,
                        "reason": _scrub_absolute_paths(allow_result.reason)},
        "refuse_case": {"allowed": refuse_result.allowed,
                         "reason": _scrub_absolute_paths(refuse_result.reason)},
        "both_directions_verified": allow_result.allowed and not refuse_result.allowed,
    }
    path = os.path.join(RECEIPT_DIR, f"w2-garm-gate-decontam-{run_id}.json")
    _write_json(path, receipt)
    return receipt


# ---------------------------------------------------------------------------
# Component 2b: governed-fit gate. governor.preflight() hard-requires
# torch.cuda and cannot run on this CPU-only dry run -- env_limits() (real,
# CPU-safe) is reused for the policy constants; the refusal condition and
# receipt shape below mirror preflight()'s own EXACTLY, against an injected
# free_gb (disclosed, never silently passed off as a real VRAM reading).
# ---------------------------------------------------------------------------

def _governed_fit_gate_dry(free_gb_injected: float) -> dict:
    frac, margin_gb, _throttle_s = governor.env_limits()
    allowed = free_gb_injected >= margin_gb
    reason = (
        f"free_gb={free_gb_injected} >= margin_gb={margin_gb} -- ALLOWED"
        if allowed else
        f"VRAM-PREFLIGHT (simulated): {free_gb_injected}GB free -- need >= "
        f"{margin_gb}GB free before load; refusing launch")
    return {"allowed": allowed, "reason": reason,
            "vram_fraction": frac, "free_gb_injected": free_gb_injected,
            "margin_gb": margin_gb}


def run_governed_fit_gate_selftest(run_id: str) -> dict:
    allow_case = _governed_fit_gate_dry(free_gb_injected=8.0)
    refuse_case = _governed_fit_gate_dry(free_gb_injected=0.5)

    receipt = {
        "ticket": "ISSUE-113-W2-GARM-GATE-GOVERNED-FIT",
        "ts": _ts(),
        "run_id": run_id,
        "gate": "governor.py:env_limits() policy constants reused; "
                "preflight()'s exact refusal condition/receipt shape mirrored "
                "in a CPU-safe wrapper (preflight() itself hard-imports "
                "torch.cuda and cannot run in this dry run)",
        "governed_fit_dry_run_simulated": True,
        "allow_case": allow_case,
        "refuse_case": refuse_case,
        "both_directions_verified": allow_case["allowed"] and not refuse_case["allowed"],
    }
    path = os.path.join(RECEIPT_DIR, f"w2-garm-gate-governed-fit-{run_id}.json")
    _write_json(path, receipt)
    return receipt


# ---------------------------------------------------------------------------
# Component 3: training leg -- explicitly SKIPPED per acceptance (a)
# ("proving the full sequence minus the training leg"). Real leg is
# maintainer-window-gated (issue #113 (b)); never fabricated here.
# ---------------------------------------------------------------------------

def run_training_leg_receipt(run_id: str) -> dict:
    receipt = {
        "ticket": "ISSUE-113-W2-GARM-TRAINING-LEG",
        "ts": _ts(),
        "run_id": run_id,
        "status": "SKIPPED_DRY_RUN",
        "reason": ("acceptance (a) proves the full sequence minus the "
                   "training leg; the real GPU training leg (acceptance (b)) "
                   "fires only inside a maintainer-opened window, behind the "
                   "decontam receipt -- never fired by this builder"),
        "maintainer_window_env": MAINTAINER_WINDOW_ENV,
        "window_confirmed": os.environ.get(MAINTAINER_WINDOW_ENV) == "1",
    }
    path = os.path.join(RECEIPT_DIR, f"w2-garm-training-leg-{run_id}.json")
    _write_json(path, receipt)
    return receipt


# ---------------------------------------------------------------------------
# Component 4: dump contract
# ---------------------------------------------------------------------------

def build_dump(run_id: str, out_dir: str, grown_ff: int) -> dict:
    dump_dir = os.path.join(out_dir, "dump")
    os.makedirs(dump_dir, exist_ok=True)

    config = {
        "model": {
            "vocab": TOY_CONFIG["vocab"], "hidden": TOY_CONFIG["hidden"],
            "layers": TOY_CONFIG["layers"], "heads": TOY_CONFIG["heads"],
            "ff": grown_ff, "seq": TOY_CONFIG["seq"],
            "tied_embeddings": TOY_CONFIG["tied_embeddings"],
            "norm_placement": TOY_CONFIG["norm_placement"],
        },
        "objective": {"mtp_aux_heads": {"n_heads": TOY_CONFIG["n_mtp"]}},
    }

    # HAND-ASSEMBLED (never a raw model.state_dict() dump -- see module
    # docstring): omits lm_head.weight when tied, per #108's own
    # cross_validate() contract.
    manifest: dict = {
        "model.embed_tokens.weight": [TOY_CONFIG["vocab"], TOY_CONFIG["hidden"]],
    }
    for i in range(TOY_CONFIG["layers"]):
        manifest[f"model.layers.{i}.mlp.gate_proj.weight"] = [grown_ff, TOY_CONFIG["hidden"]]
        manifest[f"model.layers.{i}.mlp.up_proj.weight"] = [grown_ff, TOY_CONFIG["hidden"]]
        manifest[f"model.layers.{i}.mlp.down_proj.weight"] = [TOY_CONFIG["hidden"], grown_ff]
    for k in range(TOY_CONFIG["n_mtp"]):
        manifest[f"mtp_heads.{k}.weight"] = [TOY_CONFIG["vocab"], TOY_CONFIG["hidden"]]
    if not TOY_CONFIG["tied_embeddings"]:
        manifest["lm_head.weight"] = [TOY_CONFIG["vocab"], TOY_CONFIG["hidden"]]

    config_path = os.path.join(dump_dir, w2_derive_s_config.CONFIG_FILENAME)
    manifest_path = os.path.join(dump_dir, w2_derive_s_config.MANIFEST_FILENAME)
    _write_json(config_path, config)
    _write_json(manifest_path, manifest)

    receipt = {
        "ticket": "ISSUE-113-W2-GARM-DUMP",
        "ts": _ts(),
        "run_id": run_id,
        "dump_dir": _repo_relpath(dump_dir),
        "config_sha256": sha256_file(config_path),
        "manifest_sha256": sha256_file(manifest_path),
        "manifest_construction": "hand-assembled from post-grow config, not a "
                                  "raw state_dict() dump (see module docstring "
                                  "re: tied-embeddings lm_head.weight)",
    }
    path = os.path.join(RECEIPT_DIR, f"w2-garm-dump-{run_id}.json")
    _write_json(path, receipt)
    return {"receipt": receipt, "receipt_path": path, "dump_dir": dump_dir}


# ---------------------------------------------------------------------------
# Component 5: #108 verification -- derive + verify against THIS run's dump.
# ---------------------------------------------------------------------------

def run_108_verification(run_id: str, out_dir: str, dump_dir: str) -> dict:
    seed = 20260705
    s_config_path = os.path.join(out_dir, "s_arm_config.json")
    derive_receipt_path = os.path.join(out_dir, "s_arm_derivation_receipt.json")

    s_config, derive_receipt = w2_derive_s_config.derive_s_config(dump_dir, seed)
    _write_json(s_config_path, s_config)
    _write_json(derive_receipt_path, derive_receipt)

    verify_result = w2_derive_s_config.refuse_or_pass(
        dump_dir=dump_dir, seed=seed, s_config_path=s_config_path)

    receipt = {
        "ticket": "ISSUE-113-W2-GARM-108-VERIFICATION",
        "ts": _ts(),
        "run_id": run_id,
        "tool": "scripts/w2_derive_s_config.py (imported, not reimplemented)",
        "derive": {"s_config_path": _repo_relpath(s_config_path),
                   "derive_receipt_path": _repo_relpath(derive_receipt_path),
                   "s_arm_config_sha256": derive_receipt["s_arm_config_sha256"]},
        "verify": {"allowed": verify_result.allowed,
                   "reason": _scrub_absolute_paths(verify_result.reason)},
        "acceptance_a_derive_and_verify_pass": verify_result.allowed,
    }
    path = os.path.join(RECEIPT_DIR, f"w2-garm-108-verification-{run_id}.json")
    _write_json(path, receipt)
    return receipt


# ---------------------------------------------------------------------------
# Main dry-run sequence
# ---------------------------------------------------------------------------

def run_dry_run(out_dir: str) -> dict:
    _assert_cpu_only()
    run_id = f"w2-garm-dryrun-{_ts()}"
    os.makedirs(out_dir, exist_ok=True)

    append_run_event(run_id, "started", {"mode": "cpu-dry-run"})
    append_run_event(run_id, "pid_assigned", {"pid": os.getpid()})

    try:
        append_run_event(run_id, "heartbeat", {"phase": "grow"})
        grow = run_grow_step(run_id, out_dir)

        append_run_event(run_id, "heartbeat", {"phase": "launch-gates"})
        decontam_receipt = run_decontam_gate_selftest(run_id, out_dir)
        if not decontam_receipt["both_directions_verified"]:
            append_run_event(run_id, "refused", {"gate": "decontam"})
            raise SystemExit("W2_GARM_DRY_RUN_FAIL: decontam gate selftest did "
                              "not verify both directions")

        governed_fit_receipt = run_governed_fit_gate_selftest(run_id)
        if not governed_fit_receipt["both_directions_verified"]:
            append_run_event(run_id, "refused", {"gate": "governed-fit"})
            raise SystemExit("W2_GARM_DRY_RUN_FAIL: governed-fit gate selftest "
                              "did not verify both directions")

        append_run_event(run_id, "heartbeat", {"phase": "training-leg-skip"})
        training_receipt = run_training_leg_receipt(run_id)

        append_run_event(run_id, "heartbeat", {"phase": "dump"})
        dump = build_dump(run_id, out_dir, grow["grown_ff"])

        append_run_event(run_id, "heartbeat", {"phase": "108-verification"})
        verification_receipt = run_108_verification(run_id, out_dir, dump["dump_dir"])

        acceptance_a_pass = (
            grow["receipt"]["identity_preservation"]["passed"]
            and decontam_receipt["both_directions_verified"]
            and governed_fit_receipt["both_directions_verified"]
            and verification_receipt["acceptance_a_derive_and_verify_pass"]
        )

        summary = {
            "ticket": "ISSUE-113-W2-GARM-DRY-RUN-SUMMARY",
            "ts": _ts(),
            "run_id": run_id,
            "issue": ISSUE_REF,
            "acceptance_a_pass": acceptance_a_pass,
            "components": {
                "grow": _repo_relpath(grow["receipt_path"]),
                "decontam_gate": _repo_relpath(os.path.join(RECEIPT_DIR, f"w2-garm-gate-decontam-{run_id}.json")),
                "governed_fit_gate": _repo_relpath(os.path.join(RECEIPT_DIR, f"w2-garm-gate-governed-fit-{run_id}.json")),
                "training_leg": _repo_relpath(os.path.join(RECEIPT_DIR, f"w2-garm-training-leg-{run_id}.json")),
                "dump": _repo_relpath(dump["receipt_path"]),
                "issue_108_verification": _repo_relpath(os.path.join(RECEIPT_DIR, f"w2-garm-108-verification-{run_id}.json")),
            },
            "event_log": _repo_relpath(EVENT_LOG_PATH),
        }
        summary_path = os.path.join(RECEIPT_DIR, f"w2-garm-dry-run-summary-{run_id}.json")
        _write_json(summary_path, summary)
        summary["summary_path"] = _repo_relpath(summary_path)

        if not acceptance_a_pass:
            append_run_event(run_id, "failed", {"summary_path": _repo_relpath(summary_path)})
            raise SystemExit(f"W2_GARM_DRY_RUN_FAIL: acceptance (a) not met -- see {summary_path}")

        append_run_event(run_id, "completed", {"summary_path": _repo_relpath(summary_path)})
        return summary
    except SystemExit:
        raise
    except Exception as e:
        append_run_event(run_id, "failed", {"error": f"{type(e).__name__}: {e}"})
        raise


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--out-dir", default=os.path.join(
        REPO, "scratch", "w2-garm", "dry-run", _ts()))
    args = ap.parse_args(argv)

    if args.live:
        print("W2_GARM_LAUNCH_REFUSED: the real GPU G-arm leg (issue #113 "
              "acceptance (b)) fires only inside a maintainer-opened window, "
              "behind the decontam receipt -- never fired by this builder. "
              f"Set {MAINTAINER_WINDOW_ENV}=1 only from the maintainer's own "
              "GPU-launch runbook (this script does not implement that path).")
        return 1

    if not args.dry_run:
        ap.print_help()
        return 1

    summary = run_dry_run(args.out_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["acceptance_a_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
