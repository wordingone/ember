"""grow_respec_280.py -- #280 K1 respec: antisymmetric out-proj perturbation
grow-operator cure + supporting tick-6 rails, at CPU/toy-fixture scale.

Authority: issue #280's second comment (frozen, panel-recommended) mandates
the exact mechanism reproduced here verbatim:

  "Mechanism (panel-recommended): antisymmetric out-proj perturbation. Split
  each halved down_proj column pair as (a/2 + eps, a/2 - eps) instead of
  (a/2, a/2). Function preservation is EXACT in real arithmetic (the pair
  still sums to a while gate/up twins stay identical at t=0), yet the twin
  in-proj gradients differ from step 1 (dL/dW_in[:,j] depends on down_proj
  column j) -- breaking exactly the symmetry Newton-Schulz provably
  preserves ... In-proj noise is DOMINATED: it costs O(eps) function error
  at t=0 and contaminates the R0 preservation receipt."

This module holds the NEW, reusable machinery the mechanism and its five
companion tick-6 rails need. It does NOT reimplement the grow surgery
itself -- the surgery (widen_state_dict) lives in cbase_grow_dryrun.py,
which this respec extends in place (eps_sigma/eps_seed params, default 0.0
== the proven-capacity-null exact-duplication behaviour, unchanged for
every existing caller). Placement: cbase_grow_rung.py -- the unified chain
issue #113's own ruling names as the ONE live-grow vehicle ("no second
live-grow implementation gets built") -- imports both that widened operator
and this module's audit/telemetry helpers.

PROVENANCE (disclosed, mirroring the pattern #113's own runner used for the
same situation): the "R1 twin-audit machinery" #280 calls "reusable as the
acceptance test" is NOT actually committed anywhere in this tree (grepped:
no twin_cosine / cos_sim / twin_audit hit anywhere except
reconstruct_pregrow.py's bitwise torch.equal guard, which checks EXACT
identity, not a continuous cosine metric). twin_cosine_audit() below is
therefore NEW code, flagged as such -- not a reuse of pre-existing
machinery, because none is committed to reuse.

Functions:
  twin_cosine_audit        -- measures twin-pair cosine similarity (gate/up
                               rows, down_proj columns) on a grown state
                               dict. The tick-6 acceptance-gate quantity is
                               down_proj_twin_cosine.median.
  expected_twin_cosine      -- closed-form band DERIVED from eps_sigma
                               alone, computable before any measurement
                               exists (tick-6 item 3: "not copied from the
                               H-twin audit").
  checkpoint_identity        -- {path, sha256, segment_id, step} tuple so a
                               checkpoint is NEVER referenced by step number
                               alone (tick-6 item 5; closes the
                               #280-comment-1-cited step-00000730 collision
                               class structurally: two on-disk checkpoints
                               share that step number today).
  schedule_position_block    -- LR-schedule-position record reusing
                               timeshare_pretrain.wsd_lr_frac (reuse, never
                               reimplement) so receipts state a pure
                               step-fraction, never a bare step (tick-6
                               item 6).

Derivation of expected_twin_cosine (recorded here so the acceptance band is
reproducible from the noise spec, not asserted after the fact):

  Down-proj twin pair: w1 = a/2 + eta, w2 = a/2 - eta, where a is the
  original (pre-grow) down_proj column (length h = hidden/out_features),
  and eta ~ N(0, tau^2 I_h) with tau = eps_sigma * ||a||_2 / sqrt(h) -- i.e.
  eps_sigma is the REGISTERED, dimensionless noise scale relative to the
  column's own norm (tick-6 item 2's "per-column scale relative to column
  norm").

  Let A = ||a||^2/4, B = a.eta (mean 0, Var = 4*A*tau^2), C = ||eta||^2
  (mean h*tau^2). Exactly: w1.w2 = A - C, ||w1||^2*||w2||^2 = (A+C)^2 - B^2.
  Writing x = tau^2/A (small) and expanding numerator and denominator to
  O(x) BOTH (dropping the denominator's O(x) term is the wrong shortcut --
  it understates the effect by 2x, caught by the toy-scale test below):

    E[cos] ~ (1 - h*x) / sqrt(1 + x*(2h-4))  ~  1 - 2*x*(h-1)

  Substituting x = tau^2/A = 4*eps_sigma^2/h:

    E[cos(w1, w2)] ~ 1 - 8 * eps_sigma^2 * (h-1)/h  ~  1 - 8 * eps_sigma^2
                                                         (h >> 1)

  eps_sigma=0 reproduces the exact-duplication capacity-null point
  (cos == 1 exactly), matching #280's measured positive control
  (median twin cosine 1.0000001 -- float-eps around exact 1.0). The
  h-independent form (1 - 8*eps_sigma^2) is used below since realistic
  hidden sizes make (h-1)/h ~ 1; test_grow_respec_280.py verifies this
  stays within the registered acceptance tolerance even at toy scale
  (h=16-32), where the correction is a few percent.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def twin_cosine_audit(sd: dict, n_layers: int, ff_seed: int) -> dict:
    """
    Twin-pair cosine audit on a GROWN (2x-widened) state dict.

    For each layer, compares:
      - gate_proj / up_proj: twin ROW k vs row k+ff_seed. These stay exact
        duplicates under the #280 mechanism (perturbation touches down_proj
        only) -- median is expected EXACTLY 1.0 at construction; ties break
        via gradient divergence from training step 1, never at t=0.
      - down_proj: twin COLUMN k vs column k+ff_seed. This is exactly where
        the antisymmetric perturbation acts -- median is the tick-6
        acceptance-gate quantity.

    Returns per-layer medians plus median/min/max over ALL (layer, pair)
    cosines, separately for gate/up and down_proj.

    torch is imported lazily HERE ONLY (matching cbase_grow_rung.py's own
    module-top convention) so the rest of this module -- in particular
    expected_twin_cosine, the pure-math closed-form band -- stays importable
    and testable in a torch-free --selftest context.
    """
    import torch

    down_cos_all: list[float] = []
    gateup_cos_all: list[float] = []
    per_layer: list[dict] = []

    for i in range(n_layers):
        p = f"backbone_model.layers.{i}.mlp."
        g = sd[p + "gate_proj.weight"]
        u = sd[p + "up_proj.weight"]
        d = sd[p + "down_proj.weight"]

        g1, g2 = g[:ff_seed, :], g[ff_seed:, :]
        u1, u2 = u[:ff_seed, :], u[ff_seed:, :]
        d1, d2 = d[:, :ff_seed], d[:, ff_seed:]

        g_cos = torch.nn.functional.cosine_similarity(g1, g2, dim=1)   # per row, (ff_seed,)
        u_cos = torch.nn.functional.cosine_similarity(u1, u2, dim=1)   # per row, (ff_seed,)
        d_cos = torch.nn.functional.cosine_similarity(d1, d2, dim=0)   # per column, (ff_seed,)

        gateup_cos_all.extend(g_cos.tolist())
        gateup_cos_all.extend(u_cos.tolist())
        down_cos_all.extend(d_cos.tolist())

        per_layer.append({
            "layer": i,
            "gate_cos_median": float(g_cos.median()),
            "up_cos_median": float(u_cos.median()),
            "down_cos_median": float(d_cos.median()),
        })

    down_t = torch.tensor(down_cos_all)
    gateup_t = torch.tensor(gateup_cos_all)
    return {
        "n_layers": n_layers,
        "ff_seed": ff_seed,
        "per_layer": per_layer,
        "down_proj_twin_cosine": {
            "median": float(down_t.median()), "min": float(down_t.min()),
            "max": float(down_t.max()), "n_pairs": int(down_t.numel()),
        },
        "gate_up_twin_cosine": {
            "median": float(gateup_t.median()), "min": float(gateup_t.min()),
            "max": float(gateup_t.max()), "n_pairs": int(gateup_t.numel()),
            "note": "expected exactly 1.0 at construction under the #280 "
                    "mechanism -- perturbation is down_proj-only; ties break "
                    "via gradient divergence from step 1, not at t=0",
        },
    }


def expected_twin_cosine(eps_sigma: float) -> float:
    """
    Closed-form band DERIVED from eps_sigma alone (module docstring),
    computed BEFORE any measurement exists (tick-6 item 3: acceptance bands
    "derived from the injected sigma, not copied from the H-twin audit").
    eps_sigma=0.0 -> 1.0, the measured capacity-null point.
    """
    val = 1.0 - 8.0 * (eps_sigma ** 2)
    return max(val, -1.0)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def checkpoint_identity(ckpt_dir, segment_id: str, step: int) -> dict:
    """
    Structured checkpoint reference: {path, model_pt_sha256, segment_id,
    step}. NEVER collapse this to a bare step number -- tick-6 item 5 names
    the live collision class directly: two on-disk checkpoints both named
    step-00000730 exist today (models/cbase-grow-live/live-20260703T053225Z/
    post/checkpoints/step-00000730 and models/cbase-grow-rung/
    rung1-20260703T155447Z/checkpoints/step-00000730 -- see
    reconstruct_pregrow.py's own COLLISION WARNING). A consumer that keys on
    this dict's sha256 (or the (path, segment_id) pair) cannot confuse the
    two; a consumer keying on `step` alone can and did.
    """
    ckpt_dir = Path(ckpt_dir).resolve()
    model_pt = ckpt_dir / "model.pt"
    return {
        "path": str(ckpt_dir),
        "segment_id": segment_id,
        "step": step,
        "model_pt_sha256": _sha256_file(model_pt) if model_pt.exists() else None,
    }


def schedule_position_block(step: int, total_steps: int, warmup_frac: float,
                             stable_until_frac: float, decay_to_lr_frac: float) -> dict:
    """
    LR-schedule-position record for a grow/respec receipt (tick-6 item 6:
    "schedule is a pure step-fraction function (timeshare_pretrain
    wsd_lr_frac); the executed rung-1 event ran at 16-17% base LR (steps
    730-766 of total_steps=449651, deep warmup) -- respec acceptance
    receipts must state their schedule position the same way"). Reuses
    timeshare_pretrain's own wsd_lr_frac directly (reuse, never
    reimplement) -- never recomputes the schedule shape here. Parameter
    names match configs/v0-pretrain-config.json's own "schedule" block
    (warmup_frac / stable_until_frac / decay_to_lr_frac) verbatim.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from timeshare_pretrain import wsd_lr_frac  # noqa: E402

    frac = wsd_lr_frac(step, total_steps, warmup_frac, stable_until_frac, decay_to_lr_frac)
    return {
        "step": step,
        "total_steps": total_steps,
        "step_fraction": (step / total_steps) if total_steps else None,
        "wsd_lr_frac": frac,
        "warmup_frac": warmup_frac,
        "stable_until_frac": stable_until_frac,
        "decay_to_lr_frac": decay_to_lr_frac,
    }
