# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute an ACKed drop manifest (lead 82379 ACK of 82377, manifest logs/drop-manifest-20261110T012235Z.tsv).
Tier 1: manifest rows DROP-FREE + DROP-HF-ONLY (waiver recorded in every HF-ONLY receipt row) plus scratch/orphan-packs files that match an HF copy.
Tier 2: named scratch dirs (intermediates of finished jobs). Skipped if any process names the dir or any file in it changed in the last 10 min.
Tier 1 goes through verified_remove.py (#2454): per file, in the remove call itself, the path must be inside packed/ or scratch/orphan-packs (no link or junction on the way) with st_nlink == 1, the server entry is READ BACK
NOW (size AND LFS sha256; no snapshot index, no size-only fallback, an unreadable server keeps the file), the local sha256 is recomputed NOW, and the receipt row (both hashes) is fsynced BEFORE the os.remove.
Tier 2 has no copy to compare ("ruled, no copy": intermediates of finished jobs, lead 82377): ruling id = the ACK, the manifest of every file (path, size, sha256, mtime, inode) is fsynced before the first remove, and each
remove re-checks that the file is still the manifest's file; never labelled verified. No shutil.rmtree anywhere; emptied directories are removed with os.rmdir.
Usage: python drop_execute.py <manifest.tsv> [--go] [--tier2 [--manifest-sha256 NAME=SHA ...]] [--no-orphan] [--ack 'lead NNNNN']   (default: dry, verifies against the server but writes and deletes nothing; the dry run prints one tier2 PLAN_SHA256 NAME=SHA per directory, tier 2 --go removes only a directory whose plan the lead ruled on)"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_TRAIN_REPO, LANE_ROOT
import os, sys, json, time, shutil
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verified_remove as VR

from lane_config import LANE_ROOT as ROOT; REPO = ("wordingone/" + HF_TRAIN_REPO); ACK = "lead 82379 (ack of 82377)"
TIER2 = ["pes2o-00000-00002-pre-redaction-1230", "pes2o-00000-00002-redacted", "thdbg-t691x_z_",
         "wikipedia-20220501-p41243p151573-r2-pre-redaction-1223", "wikipedia-20220501-p41243p151573-r2"]
RC = f"{ROOT}/logs/drop-exec-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.jsonl"
READER = None          # tests inject a fake server reader; production asks the Hub NOW for every file


def prune_empty(d):
    """Remove emptied directories bottom-up with os.rmdir only (it refuses a directory that still holds anything)."""
    for dp, _, _ in sorted(os.walk(d), key=lambda x: -len(x[0])):
        try: os.rmdir(dp)
        except OSError: pass


def main(argv=None):
    global ACK
    argv = sys.argv[1:] if argv is None else argv
    go = "--go" in argv; tier2 = "--tier2" in argv; no_orphan = "--no-orphan" in argv
    if "--ack" in argv: ACK = argv[argv.index("--ack") + 1]
    pins = VR.pins_from_argv(argv); pin_vals = [argv[i + 1] for i, a in enumerate(argv) if a == "--manifest-sha256" and i + 1 < len(argv)]
    man = [a for a in argv if not a.startswith("--") and a != ACK and a not in pin_vals][0]
    reader = READER or VR.hub_reader()
    allowed = [f"{ROOT}/packed", f"{ROOT}/scratch/orphan-packs"]
    work = []
    for l in open(man, encoding="utf-8").read().splitlines()[1:]:
        cls, gib, pack, sub, key, path = l.split("\t")
        if cls in ("DROP-FREE", "DROP-HF-ONLY"): work.append((cls, REPO, key, path))
    # orphan-packs: any file whose (sha,size) matches an HF copy per the scan; the server is read again by path in the remove call
    scans = sorted(f for f in os.listdir(f"{ROOT}/logs") if f.startswith("drop-scan-") and f.endswith(".jsonl"))
    for l in (open(f"{ROOT}/logs/{scans[-1]}", encoding="utf-8") if scans and not no_orphan else []):
        r = json.loads(l)
        if "/scratch/orphan-packs/" in r["path"] and r["hf"] and r["nlink"] == 1:
            repo, _, hp = r["hf"][0].partition(":"); work.append(("ORPHAN", repo, hp, r["path"]))
    print("tier1 candidates:", len(work), flush=True)
    freed = {"DROP-FREE": 0, "DROP-HF-ONLY": 0, "ORPHAN": 0}; skipped = []

    def one(w):
        cls, repo, hp, p = w
        res = VR.remove_verified(p, repo, hp, roots=allowed, receipt=RC, authority=ACK, reader=reader, dry=not go,
                                 extra=dict(tier=1, cls=cls, waiver=(ACK + ": class-guard waiver for admitted-unconsumed shard; pool becomes HF-only" if cls == "DROP-HF-ONLY" else None)))
        if res["ok"]: freed[cls] += res["bytes"]       # list += / dict += under the interpreter lock; counts only
        else:
            skipped.append((p, res["why"]))
            if "sha256 mismatch" in res["why"]: print("MISMATCH kept:", p, flush=True)
    with ThreadPoolExecutor(3) as ex: list(ex.map(one, work))
    print(("" if go else "DRY ") + "tier1 freed GiB:", {k: round(v / 2**30, 2) for k, v in freed.items()}, "skipped", len(skipped), flush=True)
    for p, why in skipped[:20]: print("  skip", p, why, flush=True)
    if go: print("B free GiB after tier1:", round(shutil.disk_usage("B:/").free / 2**30, 1), flush=True)
    if tier2:
        import psutil
        cmd = " ".join(" ".join(p.info["cmdline"] or []) for p in psutil.process_iter(["cmdline"])).replace("\\", "/")
        t2 = 0; scratch = f"{ROOT}/scratch"
        for name in TIER2:
            d = f"{scratch}/{name}"
            if not os.path.isdir(d): print("tier2 absent", name); continue
            if VR.contained(d, [scratch])[0] is None: print("tier2 SKIP (not a plain directory under scratch: link or junction)", name, flush=True); continue
            if name in cmd: print("tier2 SKIP (a live process names it)", name, flush=True); continue
            files = []; newest = 0
            for dp, _, fn in os.walk(d):
                for f in fn:
                    q = os.path.join(dp, f).replace("\\", "/")
                    try: st = os.lstat(q)
                    except OSError: continue
                    files.append((q, st.st_size, st.st_nlink)); newest = max(newest, st.st_mtime)
            if time.time() - newest < 600: print("tier2 SKIP (changed in the last 10 min)", name, flush=True); continue
            if any(n > 1 for _, _, n in files): print("tier2 SKIP (hard-linked file inside)", name, flush=True); continue
            size = sum(s for _, s, _ in files); plan = VR.plan_sha([q for q, _, _ in files])
            if not go: print("tier2 PLAN_SHA256", name + "=" + plan, flush=True)
            if go:
                if not VR.ruling_ok(ACK): print("tier2 SKIP (--ack must be a mail id such as 'lead 82379'; no copy is compared)", name, flush=True); continue
                if not pins.get(name): print("tier2 SKIP (NO_PIN: needs --manifest-sha256 " + name + "=<PLAN_SHA256 of the dry run>)", name, flush=True); continue
                rows, refused = VR.ruled_manifest([q for q, _, _ in files], f"{ROOT}/logs/drop-exec-tier2-manifest.jsonl", ruling=ACK, note="intermediate of a finished job; packed form on HF (lead 82377 tier 2); NO copy compared", roots=[d], require_nlink=1, pin=pins[name])
                if refused: print("tier2 SKIP (manifest refused, nothing removed from this dir)", name, refused[:3], flush=True); continue
                bad = [(r["path"], x["why"]) for r in rows for x in [VR.remove_ruled(r, roots=[d], receipt=RC, require_nlink=1)] if not x["ok"]]
                if bad: print("tier2 kept", len(bad), "files that no longer match the manifest:", bad[:3], flush=True)
                prune_empty(d)
            t2 += size; print(("" if go else "DRY ") + "tier2", name, round(size / 2**30, 2), "GiB", flush=True)
        print("tier2 GiB:", round(t2 / 2**30, 2), flush=True)
    print("B free GiB now:", round(shutil.disk_usage("B:/").free / 2**30, 1), "receipt:", RC, flush=True)


if __name__ == "__main__":
    main()
