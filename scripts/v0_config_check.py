"""v0_config_check.py — validator for the frozen v0 pretrain config contract.

G-config row of research/v0-launch-gate.md. The launch shim runs this
fail-closed before any v0 dispatch; it also runs standalone as the
contract selftest. Checks are structural (the contract is well-formed and
internally consistent) plus the launch-blocking nulls.
"""
import json
import os
import sys

NC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = f"{NC}/configs/v0-pretrain-config.json"
ASSEMBLY_SHA = ("a29d2e567f1853966cc72a4890eadc963164265e"
                "4f24a89cadea24d9ff5b80c2")
GOVERNOR_FLOOR = {"vram_fraction": 0.80, "margin_gib_floor": 1.5,
                  "pace_s_per_step": 0.05}


def check(cfg, launch=False):
    """Returns list of violations (empty = green). launch=True adds the
    dispatch-blocking checks (tokenizer receipt named + on disk)."""
    v = []
    m = cfg.get("model", {})
    # c03 shape pinned (fp19-bench receipted)
    for f, want in (("hidden", 1024), ("layers", 20), ("heads", 16),
                    ("seq", 1024), ("tied_embeddings", True),
                    ("grad_checkpointing", True)):
        if m.get(f) != want:
            v.append(f"model.{f} != {want} (c03 pin broken)")
    # param pin = the MEASURED c03 count from fp19-bench (its receipt also
    # carries params_formula_est 284426240 — the 12h^2L formula
    # underestimates the real torch model; the measured value is binding)
    if m.get("params_estimate") != 368354304:
        v.append(f"params_estimate {m.get('params_estimate')} != receipted "
                 f"c03 measured 368354304 (fp19-bench)")
    # directed components present (component contract — silent drop = gate
    # violation per break-the-wall directed-path gate)
    if not cfg.get("precision", {}).get("qat", {}).get("enabled"):
        v.append("QAT not enabled (component contract #1)")
    if not cfg.get("objective", {}).get("mtp_aux_heads", {}).get("enabled"):
        v.append("MTP aux heads not enabled (component contract #5)")
    for comp in ("qat", "mtp_aux_heads"):
        blk = (cfg.get("precision", {}).get(comp) or
               cfg.get("objective", {}).get(comp) or {})
        if "fallback" in blk and "RECEIPTED" not in blk["fallback"]:
            v.append(f"{comp} fallback lacks the RECEIPTED-deviation clause")
    # receipted-negative exclusions stay excluded
    for path, key in ((("precision", "excluded"), "fp8"),
                      (("throughput", "excluded"), "sparse_attention")):
        d = cfg
        for p in path:
            d = d.get(p, {})
        if key not in d:
            v.append(f"exclusion {key} missing from {'.'.join(path)}")
    # governor floor never loosened
    g = cfg.get("governor", {})
    if g.get("vram_fraction", 1.0) > GOVERNOR_FLOOR["vram_fraction"]:
        v.append("governor.vram_fraction looser than floor 0.80")
    if g.get("margin_gib_floor", 0) < GOVERNOR_FLOOR["margin_gib_floor"]:
        v.append("governor.margin_gib_floor below 1.5")
    if g.get("pace_s_per_step", 0) < GOVERNOR_FLOOR["pace_s_per_step"]:
        v.append("governor.pace_s_per_step below 0.05")
    # corpus pin
    d = cfg.get("data", {})
    if ASSEMBLY_SHA not in d.get("source", ""):
        v.append("data.source does not pin the v0 assembly receipt sha")
    if d.get("token_budget", {}).get("compute_optimal") != 7367086080:
        v.append("token_budget.compute_optimal != fp19-bench c03 value")
    # launch-blocking checks
    if launch:
        tr = d.get("tokenizer_receipt")
        if not tr:
            v.append("LAUNCH BLOCKED: data.tokenizer_receipt is null "
                     "(G-tokenizer not green)")
        elif not os.path.exists(f"{NC}/receipts/{tr}"):
            v.append(f"LAUNCH BLOCKED: tokenizer receipt {tr} not on disk")
    return v


def _selftest():
    import copy
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    assert check(cfg) == [], check(cfg)
    # launch mode must block when tokenizer_receipt is null (tested on a
    # mutated copy — the live config named the receipt at G-tokenizer
    # green, PR #164)
    blocked = copy.deepcopy(cfg)
    blocked["data"]["tokenizer_receipt"] = None
    lv = check(blocked, launch=True)
    assert any("LAUNCH BLOCKED" in x for x in lv), lv
    # and block when the named receipt is not on disk
    ghost = copy.deepcopy(cfg)
    ghost["data"]["tokenizer_receipt"] = "no-such-receipt.json"
    lv = check(ghost, launch=True)
    assert any("not on disk" in x for x in lv), lv
    # mutations are caught
    bad = copy.deepcopy(cfg)
    bad["model"]["hidden"] = 2048
    assert any("c03 pin" in x for x in check(bad))
    bad = copy.deepcopy(cfg)
    bad["precision"]["qat"]["enabled"] = False
    assert any("component contract #1" in x for x in check(bad))
    bad = copy.deepcopy(cfg)
    bad["governor"]["vram_fraction"] = 0.95
    assert any("looser than floor" in x for x in check(bad))
    bad = copy.deepcopy(cfg)
    del bad["throughput"]["excluded"]["sparse_attention"]
    assert any("sparse_attention" in x for x in check(bad))
    print("V0_CONFIG_CHECK_SELFTEST_PASS")


def main():
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    launch = "--launch" in sys.argv
    v = check(cfg, launch=launch)
    if v:
        for x in v:
            print(f"VIOLATION: {x}")
        raise SystemExit(1)
    print(f"V0_CONFIG_GREEN ({'launch' if launch else 'structural'} mode)")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
