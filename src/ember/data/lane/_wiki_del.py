# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Delete the local wikipedia-20220501 raw dump slices and derived intermediates (lead 81853). NO copy is compared: this is the "ruled, no copy" path of verified_remove.py (the raw dump is re-fetchable from
dumps.wikimedia.org / archive.org, the derived files are regenerable) and it says so. Nothing runs on import; `python _wiki_del.py` is a DRY RUN, `--go --ruling ID` deletes: the manifest of every file (path, size, sha256, mtime_ns, inode,
ruling, kind) is fsynced before the first remove, each remove re-checks the file is still the manifest's file, receipt row first, st_nlink == 1, inside the wikipedia dir with no link or junction on the way.
Kept: the heldout split, the pilot sample and the provenance json."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verified_remove as VR
D = (LANE_ROOT + "/wikipedia-20220501"); MD = (LANE_ROOT + "/logs/manifests-20261108")
KEEP = {"v-heldout-2M.jsonl.zst", "pilot-2000.jsonl.zst", "meta-enwiki-20220501.json"}   # heldout split + provenance + pilot sample stay


def kind(f):
    return ("raw dump slice (dumps.wikimedia.org enwiki 20220501 multistream2 p41243p151573)" if f.startswith("enwiki") else "verification copy of the dump slice" if f.startswith("verified")
            else "derived intermediate of the wikipedia pack pipeline (regenerable; packed/wikipedia-20220501-* + HF hold the result)")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    go = "--go" in argv; ruling = argv[argv.index("--ruling") + 1] if "--ruling" in argv else None
    if not os.path.isdir(D): print("absent", D); return 0
    files = [D + "/" + f for f in sorted(os.listdir(D)) if os.path.isfile(D + "/" + f) and os.path.getsize(D + "/" + f) >= 10000 and f not in KEEP]
    print(("" if go else "DRY ") + "MANIFEST", len(files), "files", round(sum(os.path.getsize(p) for p in files) / 2**30, 2), "GiB")
    if not go: return 0
    if not ruling: print("REFUSED: --go needs --ruling ID (no copy is compared; the deletion rests on the ruling)"); return 5
    rows, refused = VR.ruled_manifest(files, MD + "/wikipedia-20220501-manifest.jsonl", ruling=ruling, note="lead 81853: wikipedia-20220501 raw/derived files; " + "; ".join(sorted({kind(os.path.basename(p)) for p in files})), roots=[D], require_nlink=1)
    n = sum(1 for r in rows if VR.remove_ruled(r, roots=[D], receipt=MD + "/wikipedia-20220501-receipts.jsonl", require_nlink=1)["ok"])
    print("DELETED", n, "of", len(rows), "refused by the manifest step", len(refused)); return 0 if n == len(rows) and not refused else 7


if __name__ == "__main__":
    sys.exit(main())
