# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""w2_derive_s_config.py -- issue #108 frozen spec: W2 S-arm config derivation.

Derives the S arm's from-scratch model config MECHANICALLY from the G arm's
post-grow architecture dump -- zero free parameters. Built by the pubgate
lane specifically because it must NOT be the lane that builds/runs the G arm
(W2 pre-registration docs/spec/w2-scale-preregistration-v1.md sec.5:
"control-authorship separation -- the S arm's config is derived mechanically
from the G arm's architecture dump, never hand-tuned").

WHAT "2x WIDTH" MEANS HERE (grounded, not assumed): this repo's growth ladder
only scales FF width (`model.ff`) rung-to-rung -- hidden/layers/heads/vocab
are fixed constants across the whole ladder (confirmed by reading
docs/dossier/rung2-growth-ladder-dossier-v1.md's own strict-doubling table:
rung-1 ff 8192->16384, rung-2 ff 16384->32768, hidden/layers/heads/vocab never
move) and scripts/growth_refutation/capacity.py's net2net_grow, which widens
ONLY the SwiGLU gate/up/down_proj tensors, never touches attention hidden
size. So "identical architecture at 2x width" IS the G arm's post-grow
config verbatim -- every field copied 1:1, `model.ff` included (it is
already the grown value in the dump).

G-ARM DUMP CONTRACT (the two files this tool consumes -- specified here since
no W2 G-arm runner exists yet; src/ember/governance/scripts/w2_heldout/launch_gate.py's own
docstring confirms this precondition: "No W2 runner file exists yet"):

  <dump-dir>/config.json
      Same nesting as the standing contract-file convention
      (configs/v0-pretrain-config.json): model.{vocab,hidden,layers,heads,
      ff,seq,tied_embeddings,norm_placement}, objective.mtp_aux_heads.n_heads.
      `model.ff` is the POST-GROW width (the net2net grow target).

  <dump-dir>/state_dict_shape_manifest.json
      Flat {state_dict_key: [shape...]} map -- SHAPES ONLY, never tensors
      (the "no model loads" rail). Keys follow this repo's established
      naming (model.embed_tokens.weight, model.layers.<n>.mlp.gate_proj.
      weight, mtp_heads.<k>.weight, lm_head.weight -- grepped directly from
      src/ember/governance/scripts/w1_collapse_control_run.py's RealW1Model).

Every REQUIRED config.json field is either present or the tool raises
DerivationError -- never a default. Fields with an independent shape
signature (vocab, hidden, layers, ff, n_mtp, tied_embeddings) are
cross-validated against the manifest; fields with no shape signature
(heads -- head_dim isn't recoverable from a single proj shape without an
extra assumption; seq -- a data/runtime choice, not baked into any weight;
norm_placement -- an architectural convention string) are copied verbatim
and the gap is DISCLOSED in the receipt, never silently claimed as
cross-validated. Same disclosed-gap idiom as
w1_collapse_control_run.derive_real_arch_config's layers_assumed/
heads_assumed fields.

Seed handling (frozen spec point 2): --seed is a CLI arg, recorded only in
the receipt's s_arm_seed field -- NEVER embedded in the derived config (the
recipe match is W1's: seeded random init, config and seed are independent
axes).

Verify mode (frozen spec point 4, the launch hook): re-derives fresh from
the SAME dump and diffs against an on-disk S-arm config file; any mismatch
is a fail-closed refusal, same GateResult/assert_launch_allowed shape as
src/ember/governance/scripts/w2_heldout/launch_gate.py's sec.4 decontamination hook. A future W2
runner imports `assert_launch_allowed` from this module exactly the way it
will import the same-named function from launch_gate.py.

Rails: CPU-only (no torch import, no model load -- JSON + stdlib only);
shape-manifest-only; no commits; LF line endings.

CLI:
  python w2_derive_s_config.py derive --dump-dir D --seed N \
      --out-config C --out-receipt R
  python w2_derive_s_config.py verify --dump-dir D --seed N --s-config C
  python w2_derive_s_config.py selftest   (also default with no subcommand)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

CONFIG_FILENAME = "config.json"
MANIFEST_FILENAME = "state_dict_shape_manifest.json"

# Dotted config.json paths this tool requires -> whether an independent
# shape-manifest cross-check exists. Declared once so derivation and receipt
# agree on what was, and was not, cross-validated.
REQUIRED_FIELDS = [
    ("model.vocab", True),
    ("model.hidden", True),
    ("model.layers", True),
    ("model.heads", False),
    ("model.ff", True),
    ("model.seq", False),
    ("model.tied_embeddings", True),
    ("model.norm_placement", False),
    ("objective.mtp_aux_heads.n_heads", True),
]


class DerivationError(Exception):
    """Any missing/inconsistent field -- never defaulted, never swallowed."""


@dataclass
class GateResult:
    allowed: bool
    reason: str


# ---------------------------------------------------------------------------
# Dump loading + field access
# ---------------------------------------------------------------------------

def load_json(path: str) -> dict:
    if not os.path.isfile(path):
        raise DerivationError(f"required dump file missing: {path!r}")
    with open(path, "r", encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError as e:
            raise DerivationError(f"dump file {path!r} unparseable: {e}") from e


def _get(cfg: dict, dotted_path: str):
    node = cfg
    parts = dotted_path.split(".")
    for i, p in enumerate(parts):
        if not isinstance(node, dict) or p not in node:
            raise DerivationError(
                f"required field {dotted_path!r} missing from config.json "
                f"(stopped at {'.'.join(parts[:i + 1])!r}) -- ERROR, never defaulted")
        node = node[p]
    return node


def _set(d: dict, dotted_path: str, value) -> None:
    parts = dotted_path.split(".")
    node = d
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = value


def _delete(d: dict, dotted_path: str) -> None:
    parts = dotted_path.split(".")
    node = d
    for p in parts[:-1]:
        node = node[p]
    del node[parts[-1]]


def sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# ---------------------------------------------------------------------------
# Shape-manifest cross-validation
# ---------------------------------------------------------------------------

def _prefixed_indices(manifest: dict, prefix: str) -> set:
    idxs = set()
    for key in manifest:
        if key.startswith(prefix):
            m = re.match(r"(\d+)\.", key[len(prefix):])
            if m:
                idxs.add(int(m.group(1)))
    return idxs


def cross_validate(cfg: dict, manifest: dict) -> dict:
    """Independently re-derives every field with a shape signature and
    asserts it matches config.json. Raises DerivationError on any mismatch.
    Returns {dotted_field: cross_validation_note}."""
    notes = {}

    embed_key = "model.embed_tokens.weight"
    if embed_key not in manifest:
        raise DerivationError(f"manifest missing {embed_key!r} -- cannot cross-validate vocab/hidden")
    embed_shape = manifest[embed_key]
    if len(embed_shape) != 2:
        raise DerivationError(f"{embed_key!r} shape {embed_shape!r} is not rank-2")
    manifest_vocab, manifest_hidden = embed_shape

    cfg_vocab = _get(cfg, "model.vocab")
    if manifest_vocab != cfg_vocab:
        raise DerivationError(f"model.vocab={cfg_vocab} != manifest {embed_key} shape[0]={manifest_vocab}")
    notes["model.vocab"] = f"cross-validated against {embed_key} shape[0]"

    cfg_hidden = _get(cfg, "model.hidden")
    if manifest_hidden != cfg_hidden:
        raise DerivationError(f"model.hidden={cfg_hidden} != manifest {embed_key} shape[1]={manifest_hidden}")
    notes["model.hidden"] = f"cross-validated against {embed_key} shape[1]"

    layer_idxs = _prefixed_indices(manifest, "model.layers.")
    if not layer_idxs:
        raise DerivationError("manifest has zero model.layers.<n>.* keys -- cannot cross-validate layers")
    manifest_layers = max(layer_idxs) + 1
    if sorted(layer_idxs) != list(range(manifest_layers)):
        raise DerivationError(f"manifest layer indices {sorted(layer_idxs)} are not a dense 0..N-1 range")
    cfg_layers = _get(cfg, "model.layers")
    if manifest_layers != cfg_layers:
        raise DerivationError(
            f"model.layers={cfg_layers} != manifest distinct model.layers.<n>.* count={manifest_layers}")
    notes["model.layers"] = "cross-validated against distinct model.layers.<n>.* prefix count"

    gate_key = "model.layers.0.mlp.gate_proj.weight"
    if gate_key not in manifest:
        raise DerivationError(f"manifest missing {gate_key!r} -- cannot cross-validate ff")
    gate_shape = manifest[gate_key]
    if len(gate_shape) != 2:
        raise DerivationError(f"{gate_key!r} shape {gate_shape!r} is not rank-2")
    manifest_ff = gate_shape[0]
    cfg_ff = _get(cfg, "model.ff")
    if manifest_ff != cfg_ff:
        raise DerivationError(f"model.ff={cfg_ff} != manifest {gate_key} shape[0]={manifest_ff}")
    notes["model.ff"] = f"cross-validated against {gate_key} shape[0] (the grown width)"

    mtp_idxs = _prefixed_indices(manifest, "mtp_heads.")
    manifest_n_mtp = (max(mtp_idxs) + 1) if mtp_idxs else 0
    if mtp_idxs and sorted(mtp_idxs) != list(range(manifest_n_mtp)):
        raise DerivationError(f"manifest mtp_heads indices {sorted(mtp_idxs)} are not a dense 0..N-1 range")
    cfg_n_mtp = _get(cfg, "objective.mtp_aux_heads.n_heads")
    if manifest_n_mtp != cfg_n_mtp:
        raise DerivationError(
            f"objective.mtp_aux_heads.n_heads={cfg_n_mtp} != "
            f"manifest distinct mtp_heads.<k>.* count={manifest_n_mtp}")
    notes["objective.mtp_aux_heads.n_heads"] = "cross-validated against distinct mtp_heads.<k>.* prefix count"

    cfg_tied = _get(cfg, "model.tied_embeddings")
    lm_head_present = "lm_head.weight" in manifest
    if cfg_tied and lm_head_present:
        raise DerivationError(
            "model.tied_embeddings=true but manifest carries a separate lm_head.weight key "
            "(a tied model must not carry an independent head weight)")
    if not cfg_tied and not lm_head_present:
        raise DerivationError("model.tied_embeddings=false but manifest has no lm_head.weight key")
    notes["model.tied_embeddings"] = (
        f"cross-validated against lm_head.weight {'absence' if cfg_tied else 'presence'} in manifest")

    return notes


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------

def derive_s_config(dump_dir: str, seed: int) -> tuple[dict, dict]:
    config_path = os.path.join(dump_dir, CONFIG_FILENAME)
    manifest_path = os.path.join(dump_dir, MANIFEST_FILENAME)
    cfg = load_json(config_path)
    manifest = load_json(manifest_path)

    s_config: dict = {}
    sources = {}
    for dotted, has_cross_check in REQUIRED_FIELDS:
        value = _get(cfg, dotted)  # raises DerivationError if missing -- never defaulted
        _set(s_config, dotted, value)
        sources[dotted] = {"dump_file": CONFIG_FILENAME, "field_path": dotted,
                            "cross_validated": has_cross_check}

    cross_notes = cross_validate(cfg, manifest)
    for dotted, note in cross_notes.items():
        sources[dotted]["cross_validation_note"] = note
        sources[dotted]["manifest_file"] = MANIFEST_FILENAME

    for dotted, has_cross_check in REQUIRED_FIELDS:
        if not has_cross_check:
            sources[dotted]["disclosed_gap"] = (
                "not independently derivable from the state_dict shape manifest alone -- "
                "copied verbatim from config.json; same disclosed-gap class as "
                "w1_collapse_control_run.derive_real_arch_config's layers_assumed/heads_assumed")

    receipt = {
        "ticket": "ISSUE-108-W2-S-CONFIG-DERIVATION",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "dump_dir": os.path.abspath(dump_dir),
        "g_arm_config_sha256": sha256_file(config_path),
        "g_arm_manifest_sha256": sha256_file(manifest_path),
        "s_arm_seed": seed,
        "s_arm_seed_note": (
            "CLI arg, recorded here only -- never embedded in the derived config "
            "(frozen spec point 2; config and seed are independent axes)"),
        "sources": sources,
        "s_arm_config_sha256": hashlib.sha256(
            json.dumps(s_config, sort_keys=True).encode("utf-8")).hexdigest(),
    }
    return s_config, receipt


# ---------------------------------------------------------------------------
# Verify mode == the launch-gate hook (frozen spec point 4)
# ---------------------------------------------------------------------------

def _diff_configs(derived: dict, on_disk) -> list:
    diffs = []

    def walk(a, b, path):
        if isinstance(a, dict) or isinstance(b, dict):
            if not isinstance(a, dict) or not isinstance(b, dict):
                diffs.append(f"{path}: type mismatch derived={a!r} on_disk={b!r}")
                return
            for k in sorted(set(a) | set(b)):
                if k not in a:
                    diffs.append(f"{path}.{k}: present on disk, missing from derivation")
                elif k not in b:
                    diffs.append(f"{path}.{k}: derived={a[k]!r}, missing on disk")
                else:
                    walk(a[k], b[k], f"{path}.{k}")
        elif a != b:
            diffs.append(f"{path}: derived={a!r} != on_disk={b!r}")

    walk(derived, on_disk, "root")
    return diffs


def refuse_or_pass(*, dump_dir: str, seed: int, s_config_path: str) -> GateResult:
    """Fail-closed re-derive-and-diff check. Never raises for an ordinary
    refusal case -- missing dump fields, missing/unparseable on-disk config,
    or a mismatch are all valid REFUSE outcomes, not exceptions."""
    try:
        derived, _receipt = derive_s_config(dump_dir, seed)
    except DerivationError as e:
        return GateResult(False, f"re-derivation from dump {dump_dir!r} failed: {e} -- "
                                  "W2 S-arm launch refused")

    if not os.path.isfile(s_config_path):
        return GateResult(False, f"S-arm config file {s_config_path!r} does not exist -- "
                                  "W2 S-arm launch refused")
    try:
        with open(s_config_path, "r", encoding="utf-8") as fh:
            on_disk = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        return GateResult(False, f"S-arm config file {s_config_path!r} unreadable/unparseable "
                                  f"({type(e).__name__}: {e}) -- W2 S-arm launch refused")

    diffs = _diff_configs(derived, on_disk)
    if diffs:
        return GateResult(False, "S-arm config diverges from mechanical re-derivation: "
                                  + "; ".join(diffs) + " -- W2 S-arm launch refused")

    return GateResult(True, f"S-arm config {s_config_path!r} matches fresh re-derivation from "
                             f"{dump_dir!r} field-for-field -- W2 S-arm launch ALLOWED")


def assert_launch_allowed(*, dump_dir: str, seed: int, s_config_path: str) -> GateResult:
    """Fail-closed one-liner for the future W2 runner: raises SystemExit on
    refusal so a caller that forgets to check `.allowed` still can't
    proceed past an unchecked call site. Same shape as
    src/ember/governance/scripts/w2_heldout/launch_gate.py's assert_launch_allowed."""
    result = refuse_or_pass(dump_dir=dump_dir, seed=seed, s_config_path=s_config_path)
    if not result.allowed:
        raise SystemExit(f"W2_S_CONFIG_LAUNCH_GATE_REFUSED: {result.reason}")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _write_json(path: str, obj: dict) -> None:
    out_dir = os.path.dirname(os.path.abspath(path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode")

    d = sub.add_parser("derive", help="derive the S-arm config from a G-arm dump")
    d.add_argument("--dump-dir", required=True)
    d.add_argument("--seed", type=int, required=True)
    d.add_argument("--out-config", required=True)
    d.add_argument("--out-receipt", required=True)

    v = sub.add_parser("verify", help="the launch-gate hook: re-derive and diff")
    v.add_argument("--dump-dir", required=True)
    v.add_argument("--seed", type=int, required=True)
    v.add_argument("--s-config", required=True)

    sub.add_parser("selftest", help="script-style RED/GREEN selftests (default)")

    args = ap.parse_args(argv)

    if args.mode == "derive":
        try:
            s_config, receipt = derive_s_config(args.dump_dir, args.seed)
        except DerivationError as e:
            print(f"DERIVATION_ERROR: {e}")
            return 1
        _write_json(args.out_config, s_config)
        _write_json(args.out_receipt, receipt)
        print(f"DERIVED s-arm config -> {args.out_config}; receipt -> {args.out_receipt}")
        return 0

    if args.mode == "verify":
        result = refuse_or_pass(dump_dir=args.dump_dir, seed=args.seed, s_config_path=args.s_config)
        if result.allowed:
            print(f"VERIFY_PASS: {result.reason}")
            return 0
        print(f"VERIFY_REFUSE: {result.reason}")
        return 1

    return _selftest()


# ---------------------------------------------------------------------------
# Script-style RED/GREEN selftests (frozen spec point 3) -- toy-scale
# synthetic fixtures only, no real corpus/checkpoint touched, no torch.
# ---------------------------------------------------------------------------

def _toy_dump(td: str, *, ff: int = 32, layers: int = 2, mtp: int = 2, vocab: int = 16,
              hidden: int = 8, tied: bool = True, norm: str = "pre_rmsnorm",
              broken_field: str | None = None) -> None:
    cfg = {
        "model": {"vocab": vocab, "hidden": hidden, "layers": layers, "heads": 2,
                   "ff": ff, "seq": 4, "tied_embeddings": tied, "norm_placement": norm},
        "objective": {"mtp_aux_heads": {"n_heads": mtp}},
    }
    if broken_field:
        _delete(cfg, broken_field)

    manifest = {"model.embed_tokens.weight": [vocab, hidden]}
    for i in range(layers):
        manifest[f"model.layers.{i}.mlp.gate_proj.weight"] = [ff, hidden]
        manifest[f"model.layers.{i}.mlp.up_proj.weight"] = [ff, hidden]
        manifest[f"model.layers.{i}.mlp.down_proj.weight"] = [hidden, ff]
    for k in range(mtp):
        manifest[f"mtp_heads.{k}.weight"] = [vocab, hidden]
    if not tied:
        manifest["lm_head.weight"] = [vocab, hidden]

    with open(os.path.join(td, CONFIG_FILENAME), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    with open(os.path.join(td, MANIFEST_FILENAME), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)


def _selftest() -> int:
    import tempfile
    failures = []

    # GREEN: a synthetic G-dump at toy scale round-trips.
    with tempfile.TemporaryDirectory() as td:
        _toy_dump(td)
        try:
            s_config, receipt = derive_s_config(td, seed=1234)
        except DerivationError as e:
            failures.append(f"GREEN_ROUNDTRIP: unexpected DerivationError: {e}")
        else:
            if s_config["model"]["ff"] != 32 or s_config["model"]["hidden"] != 8:
                failures.append(f"GREEN_ROUNDTRIP: unexpected derived config {s_config}")
            elif receipt["s_arm_seed"] != 1234:
                failures.append("GREEN_ROUNDTRIP: seed not recorded correctly")
            else:
                print("GREEN_ROUNDTRIP: PASS (toy-scale G-dump round-trips)")

    # GREEN: derivation is deterministic -- two runs byte-identical.
    with tempfile.TemporaryDirectory() as td:
        _toy_dump(td)
        s1, r1 = derive_s_config(td, seed=7)
        s2, r2 = derive_s_config(td, seed=7)
        if json.dumps(s1, sort_keys=True) != json.dumps(s2, sort_keys=True):
            failures.append("GREEN_DETERMINISM: two derivations differ")
        elif r1["s_arm_config_sha256"] != r2["s_arm_config_sha256"]:
            failures.append("GREEN_DETERMINISM: receipt sha differs across identical runs")
        else:
            print("GREEN_DETERMINISM: PASS (two runs byte-identical)")

    # RED: a dump with a missing field errors, never defaults.
    with tempfile.TemporaryDirectory() as td:
        _toy_dump(td, broken_field="model.norm_placement")
        try:
            derive_s_config(td, seed=1)
            failures.append("RED_MISSING_FIELD: expected DerivationError, got none")
        except DerivationError as e:
            if "norm_placement" in str(e):
                print(f"RED_MISSING_FIELD: PASS (refused: {e})")
            else:
                failures.append(f"RED_MISSING_FIELD: wrong error: {e}")

    # RED: a hand-edited on-disk S-arm config (one field differs) is caught
    # by verify mode -- the exact case the launch hook exists to catch.
    with tempfile.TemporaryDirectory() as td:
        _toy_dump(td)
        s_config, _ = derive_s_config(td, seed=99)
        s_config_path = os.path.join(td, "s_arm_config.json")
        tampered = json.loads(json.dumps(s_config))
        tampered["model"]["ff"] = tampered["model"]["ff"] + 1  # hand edit
        _write_json(s_config_path, tampered)
        result = refuse_or_pass(dump_dir=td, seed=99, s_config_path=s_config_path)
        if result.allowed:
            failures.append("RED_HAND_EDIT: expected refusal, got ALLOWED")
        else:
            print(f"RED_HAND_EDIT: PASS (refused: {result.reason[:80]}...)")

    # Bonus GREEN: an untouched config verifies clean through the same gate.
    with tempfile.TemporaryDirectory() as td:
        _toy_dump(td)
        s_config, _ = derive_s_config(td, seed=5)
        s_config_path = os.path.join(td, "s_arm_config.json")
        _write_json(s_config_path, s_config)
        result = refuse_or_pass(dump_dir=td, seed=5, s_config_path=s_config_path)
        if not result.allowed:
            failures.append(f"GREEN_VERIFY_PASS: expected ALLOWED, got refusal: {result.reason}")
        else:
            print("GREEN_VERIFY_PASS: PASS (untouched config verifies clean)")

    if failures:
        print("SELFTEST_FAIL:")
        for f in failures:
            print(" ", f)
        return 1
    print("selftest=PASS (4 required cases + 1 bonus) exit=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
