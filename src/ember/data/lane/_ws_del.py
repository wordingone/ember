# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Delete the local wikisource-20220501 dump and its derived files (lead 81781; refetch if we use it: https://archive.org/download/enwikisource-20220501/enwikisource-20220501-pages-articles.xml.bz2). NO copy is compared: this is
the "ruled, no copy" path of verified_remove.py. Nothing runs on import; `python _ws_del.py` is a DRY RUN, `--go --ruling ID` deletes: manifest of every file (path, size, sha256, mtime_ns, inode, ruling) fsynced before the first remove, each
remove re-checks that the file is still the manifest's file, receipt row first, inside the dir with no link or junction on the way. The directory itself goes with os.rmdir only if it is empty afterwards."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verified_remove as VR
D = (LANE_ROOT + "/wikisource-20220501"); MD = (LANE_ROOT + "/logs/manifests-20261108")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    go = "--go" in argv; ruling = argv[argv.index("--ruling") + 1] if "--ruling" in argv else None
    if not os.path.isdir(D): print("absent", D); return 0
    files = [D + "/" + f for f in sorted(os.listdir(D)) if os.path.isfile(D + "/" + f)]
    print(("" if go else "DRY ") + "MANIFEST", len(files), sum(os.path.getsize(p) for p in files))
    if not go: return 0
    if not ruling: print("REFUSED: --go needs --ruling ID (no copy is compared; the deletion rests on the ruling)"); return 5
    rows, refused = VR.ruled_manifest(files, MD + "/wikisource-manifest.jsonl", ruling=ruling, note="lead 81781: refetch if we use it (archive.org enwikisource-20220501)", roots=[D], require_nlink=1)
    n = sum(1 for r in rows if VR.remove_ruled(r, roots=[D], receipt=MD + "/wikisource-receipts.jsonl", require_nlink=1)["ok"])
    try: os.rmdir(D); print("DELETED", D)
    except OSError: print("directory kept (not empty):", D)
    print("deleted", n, "of", len(rows), "refused", len(refused)); return 0 if n == len(rows) and not refused else 7


if __name__ == "__main__":
    sys.exit(main())
