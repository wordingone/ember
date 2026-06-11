"""fp6_provenance.py — ledger license-provenance census (#57, fp-6).

fp-6 asks what the owned core would inherit if NC2 pretrains on ledger
episodes: (a) whose DISTRIBUTION wrote the text (idiom), (b) whose LICENSE
terms ride on it. This script answers (b) with a receipt: every episode
classified by provenance (sampler stamp / origin field / era inference),
mapped to its license class, with bits totals where stamped.

License classes (citations in the receipt; texts read 2026-06-10):
  - arc-dsl-mit: Hodel arc-dsl solvers, MIT (t3_seed.py renders them;
    origin field seed-dsl-*). Human expert code, NOT model output.
  - qwen-research: outputs of Qwen/Qwen2.5-Coder-3B-Instruct. The model is
    under the Qwen RESEARCH LICENSE AGREEMENT (2024-09-19): grant is
    "FOR NON-COMMERCIAL PURPOSES ONLY", and §4.b reaches outputs —
    "If you use the Materials or any outputs or results therefrom to
    create, train, fine-tune, or improve an AI model that is distributed
    or made available, you shall prominently display 'Built with Qwen'
    or 'Improved using Qwen'".
  - apache-2.0: outputs of the Apache-licensed cores (Coder 0.5B/1.5B/7B).
    Apache-2.0 carries NO clause on model outputs; outputs-as-training-
    data is unrestricted by the model license.

`python fp6_provenance.py --selftest`.
"""
import json
import sys
from datetime import datetime, timezone

NC_WIN = "B:/M/avir/leo/state/nc-ladder"
LEDGER = f"{NC_WIN}/ledger/episodes.jsonl"
CONTROL = f"{NC_WIN}/ledger/control_pool.jsonl"
RECEIPTS = f"{NC_WIN}/receipts"

# Adapters directory (relative to NC_WIN) — paths under here are OUR own
# fine-tuned adapters; the license of their outputs follows the BASE model.
ADAPTERS_DIR = f"{NC_WIN}/adapters"

LICENSE_BY_SAMPLER = {
    "Qwen/Qwen2.5-Coder-3B-Instruct": "qwen-research",
    "Qwen/Qwen2.5-Coder-1.5B-Instruct": "apache-2.0",
    "unsloth/Qwen2.5-Coder-7B-Instruct": "apache-2.0",
    "unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit": "apache-2.0",
}

import os as _os
import re as _re


def _adapter_tag(adapter_path):
    """Return the last path component of an adapter path as the adapter tag."""
    return _os.path.basename(adapter_path.rstrip("/\\"))


def _canon_path(p):
    """Canonicalize path for prefix comparison.

    Converts both Windows-style 'B:/M/...' and WSL-style '/mnt/b/M/...'
    to a lowercase forward-slash form with a consistent drive prefix, so
    that ADAPTERS_DIR (Windows path) and sampler paths (WSL /mnt/ path)
    resolve to the same canonical string.

    Examples:
      'B:/M/avir/...'            -> 'b/M/avir/...'
      '/mnt/b/M/avir/...'        -> 'b/M/avir/...'
    """
    p = p.replace("\\", "/").strip()
    # WSL mount: /mnt/X/... -> X/...
    m = _re.match(r"^/mnt/([a-zA-Z])/(.*)", p)
    if m:
        return m.group(1).lower() + "/" + m.group(2)
    # Windows drive: X:/... -> x/...
    m = _re.match(r"^([a-zA-Z]):/?(.*)", p)
    if m:
        return m.group(1).lower() + "/" + m.group(2)
    return p


def classify(rec):
    """-> (license_class, basis). Precedence: explicit sampler stamp >
    seed-dsl origin > unknown (fail-visible, never silently clean).

    AC1: sampler of form '<BASE>+<ADAPTER_PATH>' where ADAPTER_PATH is
    under ADAPTERS_DIR resolves via BASE.  Basis is
    'sampler-stamp-with-own-adapter:<base>+<adapter-tag>'.
    Unknown bases still produce UNKNOWN (fail-visible).
    Both Windows ('B:/M/...') and WSL ('/mnt/b/M/...') adapter paths
    are recognized via _canon_path normalization.
    """
    sampler = rec.get("sampler")
    if sampler:
        # AC1: adapter-suffixed sampler — '<BASE>+<ADAPTER_PATH>'
        if "+" in sampler:
            base, adapter_path = sampler.split("+", 1)
            canon_adapter = _canon_path(adapter_path)
            canon_adapters_dir = _canon_path(ADAPTERS_DIR)
            if canon_adapter.startswith(canon_adapters_dir + "/") or \
                    canon_adapter == canon_adapters_dir:
                lic = LICENSE_BY_SAMPLER.get(base)
                tag = _adapter_tag(adapter_path)
                if lic:
                    return lic, f"sampler-stamp-with-own-adapter:{base}+{tag}"
                return "UNKNOWN", f"sampler-unmapped:{base}+{tag}"
        lic = LICENSE_BY_SAMPLER.get(sampler)
        if lic:
            return lic, f"sampler-stamp:{sampler}"
        return "UNKNOWN", f"sampler-unmapped:{sampler}"
    origin = str(rec.get("origin", ""))
    # seed-dsl-* = arc-dsl solvers; seed-verifier-rearc-* = re-arc verifier
    # programs (also Hodel, also MIT, vendored — t3_seed.py header). Both
    # are HUMAN code, not model output. seed-control-wrongtask (eng #80) =
    # the SAME intact solver text on mismatched pairs (t3_seed Phase D:
    # src = progs[wrong]) — license rides on the text, so MIT too.
    if origin.startswith(("seed-dsl", "seed-verifier-rearc",
                          "seed-control-wrongtask")):
        return "arc-dsl-mit", f"origin:{origin}"
    return "UNKNOWN", f"no-provenance(origin={origin or 'absent'})"


def census(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            lic, basis = classify(rec)
            d = out.setdefault(lic, {"n": 0, "bits": 0.0,
                                     "bits_stamped_n": 0, "bases": {}})
            d["n"] += 1
            b = rec.get("bits")
            if isinstance(b, (int, float)):
                d["bits"] += b
                d["bits_stamped_n"] += 1
            k = basis.split(":")[0]
            d["bases"][k] = d["bases"].get(k, 0) + 1
    for d in out.values():
        d["bits"] = round(d["bits"], 1)
    return out


def main():
    eps = census(LEDGER)
    ctl = census(CONTROL)
    unknown = eps.get("UNKNOWN", {}).get("n", 0)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP6-PROVENANCE", "ts": ts,
        "ledger": LEDGER.split("/")[-1],
        "license_texts_read": {
            "qwen-research": "Qwen RESEARCH LICENSE AGREEMENT 2024-09-19 "
                             "(huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct"
                             "/raw/main/LICENSE): non-commercial-only grant; "
                             "S4.b attribution clause reaches outputs used "
                             "to train/improve distributed models",
            "apache-2.0": "Qwen/Qwen2.5-Coder-1.5B-Instruct license tag "
                          "apache-2.0; no output-use clause exists in "
                          "Apache-2.0",
            "arc-dsl-mit": "vendor/arc-dsl (Hodel), MIT per t3_seed.py "
                           "header; human expert code, not model output",
        },
        "episodes_by_license": eps,
        "control_pool_by_license": ctl,
        "unknown_provenance_episodes": unknown,
        "reading": "ledger today = MIT human-expert code (arc-dsl solvers "
                    "+ re-arc verifier variants) + qwen-research-encumbered "
                    "3B output; ZERO apache-clean model-output episodes "
                    "(1.5B q15 verified samples were never ingested)",
        "bits_note": "bits = sum of per-record ledger stamps (pre-cap); "
                     "NOT the 252.2 bits-weighted post-cap dataset figure "
                     "(easy 2/mid 4/frontier 8 caps applied at build)",
    }
    out = f"{RECEIPTS}/fp6-provenance-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP6_PROVENANCE_DONE {out}")


def _selftest():
    # sampler stamp wins and maps
    lic, basis = classify({"sampler": "Qwen/Qwen2.5-Coder-3B-Instruct"})
    assert lic == "qwen-research" and basis.startswith("sampler-stamp")
    lic, _ = classify({"sampler": "Qwen/Qwen2.5-Coder-1.5B-Instruct"})
    assert lic == "apache-2.0"
    # unmapped sampler is VISIBLE, not silently clean
    lic, basis = classify({"sampler": "some/other-model"})
    assert lic == "UNKNOWN" and "unmapped" in basis

    # AC1: adapter-suffixed sampler — known base -> resolves via base (branch A)
    # Test with Windows-style path (ADAPTERS_DIR format)
    adapter_win = ADAPTERS_DIR.replace("\\", "/") + "/r1w-q3-mtp"
    lic, basis = classify({
        "sampler": f"Qwen/Qwen2.5-Coder-3B-Instruct+{adapter_win}"
    })
    assert lic == "qwen-research", f"AC1 branch-A (win) lic wrong: {lic}"
    assert basis == "sampler-stamp-with-own-adapter:Qwen/Qwen2.5-Coder-3B-Instruct+r1w-q3-mtp", \
        f"AC1 branch-A (win) basis wrong: {basis}"
    # AC1: WSL-style path (/mnt/b/...) must also match ADAPTERS_DIR
    # Derive WSL equivalent: B:/M/... -> /mnt/b/M/...
    import re as _re_test
    wsl_adapters = _re_test.sub(
        r"^([a-zA-Z]):/", lambda m: f"/mnt/{m.group(1).lower()}/",
        ADAPTERS_DIR.replace("\\", "/")
    )
    adapter_wsl = wsl_adapters + "/r1w-q3-mtp"
    lic_wsl, basis_wsl = classify({
        "sampler": f"Qwen/Qwen2.5-Coder-3B-Instruct+{adapter_wsl}"
    })
    assert lic_wsl == "qwen-research", f"AC1 branch-A (wsl) lic wrong: {lic_wsl}"
    assert basis_wsl == "sampler-stamp-with-own-adapter:Qwen/Qwen2.5-Coder-3B-Instruct+r1w-q3-mtp", \
        f"AC1 branch-A (wsl) basis wrong: {basis_wsl}"
    # AC1: unknown base + own adapter -> UNKNOWN (fail-visible, not silent)
    lic2, basis2 = classify({
        "sampler": f"some/unknown-base+{adapter_wsl}"
    })
    assert lic2 == "UNKNOWN" and "unmapped" in basis2, \
        f"AC1 unknown-base should be UNKNOWN: {lic2!r} {basis2!r}"
    # AC1: adapter path NOT under ADAPTERS_DIR -> treated as plain sampler (unmapped)
    lic3, basis3 = classify({
        "sampler": "Qwen/Qwen2.5-Coder-3B-Instruct+/some/other/path/adapter"
    })
    assert lic3 == "UNKNOWN" and "unmapped" in basis3, \
        f"AC1 foreign-adapter-path should be UNKNOWN: {lic3!r} {basis3!r}"
    # seed-dsl origin (orig + aug variants) -> MIT
    assert classify({"origin": "seed-dsl-orig"})[0] == "arc-dsl-mit"
    assert classify({"origin": "seed-verifier-rearc-v2"})[0] == "arc-dsl-mit"
    # control-pool wrongtask rows = intact arc-dsl solver text on mismatched
    # pairs (t3_seed Phase D: src = progs[wrong]) -> MIT (eng #80; was
    # UNKNOWN-visible before the t3_seed source audit)
    lic, basis = classify({"origin": "seed-control-wrongtask"})
    assert lic == "arc-dsl-mit" and basis == "origin:seed-control-wrongtask"
    # other unrecognized origins still UNKNOWN-visible
    assert classify({"origin": "some-future-origin"})[0] == "UNKNOWN"
    # nothing -> UNKNOWN
    assert classify({})[0] == "UNKNOWN"
    # census math on constructed rows
    import io, json as j
    rows = [{"sampler": "Qwen/Qwen2.5-Coder-3B-Instruct", "bits": 2.0},
            {"sampler": "Qwen/Qwen2.5-Coder-3B-Instruct"},
            {"origin": "seed-dsl-orig"}]
    import tempfile, os
    fd, p = tempfile.mkstemp(suffix=".jsonl"); os.close(fd)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(j.dumps(r) + "\n")
    c = census(p); os.unlink(p)
    assert c["qwen-research"]["n"] == 2
    assert c["qwen-research"]["bits"] == 2.0
    assert c["qwen-research"]["bits_stamped_n"] == 1
    assert c["arc-dsl-mit"]["n"] == 1
    print("FP6_PROVENANCE_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
