# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""lead 81736 (2026-11-08): delete pg/work/*.zst, wikipedia-20220501/work/*.zst and lvpilot media/text, EACH after a manifest (file, size, sha256, regenerate note) is written.
#2454: NO copy is compared here, so this is the "ruled, no copy" path of verified_remove.py and says so. Nothing runs on import. `python delete_approved_dirs.py` is a DRY RUN (lists what would go); `--go --ruling 'lead NNNNN' --manifest-sha256 JOB=<PLAN_SHA256 JOB=... the dry run printed, one per job>` deletes (a job with no pin or a different plan is skipped):
the manifest of EVERY file of a job (path, size, sha256, mtime_ns, inode, ruling, regenerate note) is fsynced before the first remove, each remove re-checks that the file is still the manifest's file, the receipt row is written before
the remove, paths must be inside the job's root with no link or junction on the way, st_nlink == 1. Explicit extensions only; kept: *.done markers (tick.py counts them), lvpilot pair/label/stat json(l) files.
Receipt: logs/delete-approved-dirs-receipt.json (+ logs/delete-approved-dirs-rows.jsonl, one fsynced row per file)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verified_remove as VR
from lane_config import LANE_ROOT as ROOT; MD = ROOT + "/logs/manifests-20261108"
JOBS = [
 ("pg-work", "/pg/work", (".zst",), "re-run scripts/pg_worker.sh on the matching Project Gutenberg shard (common-pile project_gutenberg; source URL + revision per shard in packed/pg-*.prov.jsonl). The product is packed/pg-*."),
 ("wikipedia-work", "/wikipedia-20220501/work", (".zst",), "re-run scripts/wiki_pilot.py on the matching enwiki-20220501 part (https://archive.org/download/enwiki-20220501/<part>.bz2; sha1s and URLs in wikipedia-20220501/MANIFEST-deleted-20261108.jsonl). The product is packed/wikipedia-20220501-* plus their HF objects."),
 ("lvpilot", "/lvpilot", (".mp3", ".txt", ".bad"), "LibriVox audio from archive.org/librivox.org by section id (origin + archive_sha1 per row in lvpilot/pairs.jsonl, KEPT); text from Project Gutenberg by pg_ebook id (lvpilot/pgids.json, KEPT). Retired lane (lead 81651), MLS replaces it."),
]


def prune_empty(root):
    for dp, dn, fn in sorted(os.walk(root), key=lambda x: -len(x[0])):
        if dp != root and not os.listdir(dp):
            try: os.rmdir(dp)
            except OSError: pass


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    go = "--go" in argv; ruling = argv[argv.index("--ruling") + 1] if "--ruling" in argv else None
    if go and not VR.ruling_ok(ruling): print("REFUSED: --go needs --ruling ID, a mail id such as 'lead 81736' (no copy is compared; the deletion rests on the ruling)"); return 5
    pins = VR.pins_from_argv(argv)            # one --manifest-sha256 NAME=SHA per job, the PLAN_SHA256 the dry run printed for that job
    os.makedirs(MD, exist_ok=True); receipt = []; RC = ROOT + "/logs/delete-approved-dirs-rows.jsonl"; stopped = 0
    for name, rel, exts, how in JOBS:
        root = ROOT + rel
        if not os.path.isdir(root): print(name, "absent"); continue
        files = sorted(os.path.join(dp, f).replace("\\", "/") for dp, dn, fn in os.walk(root) for f in fn if f.lower().endswith(exts))
        kept = sorted(os.path.relpath(os.path.join(dp, f), root).replace("\\", "/") for dp, dn, fn in os.walk(root) for f in fn if not f.lower().endswith(exts))
        tot = sum(os.path.getsize(p) for p in files)
        if not go:
            print("DRY", name, len(files), "files", round(tot / 2**30, 2), "GiB would be deleted; kept", len(kept), "PLAN_SHA256", name + "=" + VR.plan_sha(files)); continue
        if not pins.get(name): print(name, "REFUSED: needs --manifest-sha256", name + "=<PLAN_SHA256 of the dry run> (NO_PIN); job skipped, nothing removed", flush=True); receipt.append(dict(name=name, root=root, ruling=ruling, deleted=0, refused=["NO_PIN"])); stopped += 1; continue
        rows, refused = VR.ruled_manifest(files, f"{MD}/{name}-manifest.jsonl", ruling=ruling, note=how, roots=[root], require_nlink=1, pin=pins[name])
        if refused and refused[0][0] == "*": print(name, "REFUSED:", refused[0][1], flush=True); receipt.append(dict(name=name, root=root, ruling=ruling, deleted=0, refused=[refused[0][1]])); stopped += 1; continue
        print(name, len(rows), "files manifest written", f"{MD}/{name}-manifest.jsonl", "refused", len(refused), flush=True)
        n = 0; bad = []
        for r in rows:
            res = VR.remove_ruled(r, roots=[root], receipt=RC, require_nlink=1)
            if res["ok"]: n += 1
            else: bad.append((r["path"], res["why"]))
        prune_empty(root)
        receipt.append(dict(name=name, root=root, ruling=ruling, deleted=n, bytes=tot, refused=refused[:5], kept_by_check=bad[:5], manifest=f"{MD}/{name}-manifest.jsonl", kept_count=len(kept), kept_sample=kept[:12]))
        print(name, "deleted", n, "files; kept", len(kept), "by extension;", len(bad) + len(refused), "files left in place by the checks", flush=True)
    if go:
        json.dump(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), jobs=receipt), open(ROOT + "/logs/delete-approved-dirs-receipt.json", "w"), indent=1)
    print("DONE", ("(%d job(s) refused: no pin or the plan changed; nothing removed from them)" % stopped) if stopped else ""); return 7 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
