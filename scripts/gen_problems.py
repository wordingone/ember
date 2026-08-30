#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Generate docs/roadmap/PROBLEMS.md — the single human-readable Ember problem ledger.

Hands-off by design: STATUS (OPEN/CLAIMED/SOLVED) is DERIVED from the JSON
totality board + integrity audit (receipts-only truth); the human layer
(title/meaning/difficulty/atomization/proof) comes from docs/problems-meta.yaml.
PROBLEMS.md is regenerated, never hand-edited.

  OPEN     board RED (or no probe yet)            -> unsolved
  CLAIMED  board GREEN, no proof block            -> provisionally solved, NOT trusted
  SOLVED   board GREEN AND meta has a `proof:`     -> proven; moves to archive

Difficulty order is COMPUTED (tier, then audit severity, then rank_hint), so a
new problem only needs a tier+severity in the overlay — nothing is renumbered.

Run:  python scripts/gen_problems.py     (no args; finds the latest board+audit)
Wire: called at the end of the 2-hourly board-integrity audit so it stays live.

Provenance: landed from stage dryrun-20260704T211712Z (ember issue #210 Tier 2)
with a portability fix over the staged original — a comment illustrated the
computed REPO value with an absolute drive-letter path, and BOARD_DIRS carried
two absolute-path fallback candidates wrapping already-redacted segments that
can never resolve off the export machine. Comment genericized; the two
non-portable fallbacks dropped (EMBER_BOARD_DIR is the only real board-dir
source — the verdict-layer JSON tree is intentionally outside this repo, so
no repo-relative default applies; main() already refuses clearly via sys.exit
when no board is found). No other lines changed.
See receipts/ember-c-scale/land210e-*.
"""
import os, sys, glob, json, hashlib, datetime, re

try:
    import yaml
except Exception as e:  # pragma: no cover
    sys.exit("gen_problems: PyYAML required (pip install pyyaml): %s" % e)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # repo root

# Where the verdict-layer JSON lives — an operator-local tree, intentionally
# separate from this repo. No repo-relative default applies; set
# EMBER_BOARD_DIR to point at it. main() refuses clearly if unset/not found.
BOARD_DIRS = [
    os.environ.get("EMBER_BOARD_DIR", ""),
]

TIER_ORDER = {"frontier": 0, "training": 1, "efficiency": 2, "integrity": 3, "scaffolding": 4}
TIER_LABEL = {
    "frontier": "Research frontier — self-modification / falsifiable field-level proof",
    "training": "Training reality — make a real (non-toy) model train (gated by H0)",
    "efficiency": "Efficiency & scale — the 4090 compute adversary",
    "integrity": "Integrity & accounting — the board auditing itself",
    "scaffolding": "Scaffolding — describe / observe / port / federate (claimed green; not the core)",
}
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "none": 4, "": 4, None: 4}


def norm(s):
    s = str(s).lower().replace("(-1)", "neg1")
    return "".join(ch for ch in s if ch.isalnum())


def sha8(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()[:8]


def find_latest(patterns):
    for d in BOARD_DIRS:
        if not d:
            continue
        d = os.path.abspath(d)
        if not os.path.isdir(d):
            continue
        hits = []
        for p in patterns:
            hits += glob.glob(os.path.join(d, p))
        if hits:
            return max(hits, key=os.path.getmtime)
    return None


def fold(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def main():
    board_path = find_latest(["ember-totality-run-*.json"])
    audit_path = find_latest(["ember-audit-latest.json", "ember-audit-*.json"])
    if not board_path:
        sys.exit("gen_problems: no ember-totality-run-*.json found in %s" % BOARD_DIRS)

    board = json.load(open(board_path, encoding="utf-8"))
    rows = {norm(r["condition"]): r for r in board.get("rows", [])}

    audit = json.load(open(audit_path, encoding="utf-8")) if audit_path else {}
    honest_green = audit.get("adversary_honest_green_count", "n/a")
    audit_idx = []  # (norm_slug, entry)
    for e in audit.get("needs_work_summary", []):
        audit_idx.append((norm(e.get("slug", "")), e))

    def audit_for(cid_norm):
        for n, e in audit_idx:                       # exact
            if n == cid_norm:
                return e
        for n, e in audit_idx:                       # prefix, not bleeding into c1->c14
            if n.startswith(cid_norm) and (len(n) == len(cid_norm) or not n[len(cid_norm)].isdigit()):
                return e
        return None

    meta = yaml.safe_load(open(OVERLAY, encoding="utf-8"))
    numbering_note = fold(meta.get("numbering_note"))
    difficulty_metric = fold(meta.get("difficulty_metric"))

    items = []
    for c in meta.get("conditions", []):
        cid = c["id"]
        cn = norm(cid)
        row = rows.get(cn)
        bstatus = (row.get("status") if row else "").upper() if row else ""
        breason = fold(row.get("reason")) if row else ""
        a = audit_for(cn)
        sev = (a.get("severity") if a else None) or c.get("severity") or "none"
        own = a.get("ownership") if a else None

        if not row:
            state = "OPEN"; state_note = "unprobed"
        elif bstatus == "GREEN":
            state = "SOLVED" if c.get("proof") else "CLAIMED"; state_note = ""
        else:
            state = "OPEN"; state_note = ""

        items.append({
            "id": cid, "norm": cn, "title": c.get("title", cid),
            "tier": c.get("tier", "frontier"), "sev": sev, "own": own,
            "rank_hint": c.get("rank_hint", 50), "root": c.get("root_cause", []),
            "deffile": c.get("defining_file", "docs/domains/governance/authority/GOAL.md"), "meaning": fold(c.get("meaning")),
            "compound": c.get("compound", []), "proof": c.get("proof"),
            "state": state, "state_note": state_note, "breason": breason,
        })

    items.sort(key=lambda x: (TIER_ORDER.get(x["tier"], 9), SEV_ORDER.get(x["sev"], 4),
                              x["rank_hint"], x["norm"]))

    active = [x for x in items if x["state"] in ("OPEN", "CLAIMED")]
    solved = [x for x in items if x["state"] == "SOLVED"]
    n_open = sum(1 for x in active if x["state"] == "OPEN")
    n_claim = sum(1 for x in active if x["state"] == "CLAIMED")

    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    L = []
    L.append("# Ember — Problems ledger (GENERATED — do not edit)\n")
    L.append("> Generated `%s` by `scripts/gen_problems.py`." % ts)
    L.append("> STATUS source (receipts-only): `%s` (sha %s)%s." % (
        os.path.basename(board_path), sha8(board_path),
        " + `%s` (sha %s)" % (os.path.basename(audit_path), sha8(audit_path)) if audit_path else ""))
    L.append("> Add/edit problems in `docs/problems-meta.yaml` — never edit this file.\n")
    L.append("**Totals:** %d OPEN · %d CLAIMED (green, unverified) · %d SOLVED · %d total."
             % (n_open, n_claim, len(solved), len(items)))
    L.append("**Audit honest-green (max-skeptical):** %s.\n" % honest_green)
    L.append("**State machine:** `OPEN` (board RED / unprobed) → `CLAIMED` (board GREEN, "
             "proof not yet certified — stays here, untrusted) → `SOLVED` (board GREEN **and** "
             "a proof block; moves to the archive). Greens cannot pile up: `CLAIMED` needs proof "
             "to exit, `SOLVED` lives in the archive.\n")
    if difficulty_metric:
        L.append("**Difficulty metric:** %s\n" % difficulty_metric)
    if numbering_note:
        L.append("**Numbering:** %s\n" % numbering_note)

    # meta-problems
    L.append("---\n\n## Meta-problems — the roots (why everything below is hard)\n")
    L.append("_Full prose + proof obligations: `docs/domains/governance/ledgers/hardest-problems-register-v1.md`._\n")
    for m in sorted(meta.get("meta_problems", []), key=lambda x: x.get("meta_rank", 50)):
        L.append("- **%s — %s** · %s · gates %s" % (
            m["id"], m["title"], m.get("status", "OPEN"), ", ".join(m.get("gates", [])) or "—"))
        L.append("  %s" % fold(m.get("meaning")))
    L.append("")

    # active, global difficulty ranking across tiers
    L.append("---\n\n## Active problems — hardest → easiest (%d)\n" % len(active))
    cur_tier = None
    for i, x in enumerate(active, 1):
        if x["tier"] != cur_tier:
            cur_tier = x["tier"]
            L.append("\n### %s\n" % TIER_LABEL.get(cur_tier, cur_tier))
        badge = "**OPEN**" if x["state"] == "OPEN" else "**CLAIMED** ⚠ green-but-unverified"
        if x["state_note"]:
            badge += " (%s)" % x["state_note"]
        root = (" · root " + ", ".join(x["root"])) if x["root"] else ""
        L.append("%d. `%s` — %s" % (i, x["id"], x["title"]))
        L.append("   %s · severity %s%s · defined `%s`" % (badge, x["sev"], root, x["deffile"]))
        if x["meaning"]:
            L.append("   %s" % x["meaning"])
        if x["compound"]:
            subs = "; ".join(s.get("sub", "") for s in x["compound"])
            cnt = " (%d)" % len(x["compound"]) if len(x["compound"]) > 1 else ""
            L.append("   ⚠ compound%s: %s" % (cnt, subs))
        if x["own"]:
            L.append("   _audit: ownership=%s_" % x["own"])
        if x["breason"]:
            L.append("   _board: %s_" % (x["breason"][:160]))
        L.append("")

    # solved archive
    L.append("---\n\n## Solved — proof-carrying archive (%d)\n" % len(solved))
    if not solved:
        L.append("_None yet. A green enters here only with a `proof:` block in "
                 "`problems-meta.yaml` (receipt path(s) + probe file + audit spot-verify + "
                 "flip date) — i.e. the probe passed AND the integrity audit confirmed it is "
                 "execution-binding, not a cheap-pass._")
    else:
        for x in solved:
            p = x["proof"] or {}
            L.append("- `%s` — %s · flipped %s" % (x["id"], x["title"], p.get("date", "?")))
            if p.get("receipts"):
                L.append("  receipts: %s" % ", ".join(p["receipts"]))
            if p.get("probe"):
                L.append("  probe: `%s`" % p["probe"])
            if p.get("audit_spot_verify"):
                L.append("  audit spot-verify: %s" % p["audit_spot_verify"])
    L.append("")

    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L))
    print("gen_problems: wrote %s — %d OPEN, %d CLAIMED, %d SOLVED (board %s, audit honest-green=%s)"
          % (os.path.relpath(OUT, REPO), n_open, n_claim, len(solved),
             os.path.basename(board_path), honest_green))


if __name__ == "__main__":
    main()
