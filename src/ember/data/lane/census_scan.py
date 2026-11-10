# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Census phase 1 (lead 81208/81209): READ-ONLY scan of A:, B:, C: for candidate data files. No deletes, no moves, no writes outside OUT.
Usage: census_scan.py OUT.jsonl
Candidate = extension in EXT and size >= MIN_BYTES. Skips system/program dirs and personal Downloads/Software (those are listed to a side file `OUT.skipped-personal` only when they contain candidates)."""
import os, sys, json, time
OUT = sys.argv[1]
EXT = {".parquet", ".jsonl", ".gz", ".zst", ".arrow", ".tar", ".tgz", ".bin", ".npy", ".wav", ".flac", ".mp3", ".opus", ".ogg", ".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm", ".pdf", ".json", ".csv", ".txt", ".7z", ".bz2", ".xz", ".zip", ".safetensors"}
MIN_BYTES = 1_000_000
SKIP_SYS = ("c:/windows", "c:/program files", "c:/program files (x86)", "c:/programdata", "c:/$recycle.bin", "c:/system volume information", "b:/$recycle.bin", "a:/$recycle.bin")
SKIP_PARTS = {"node_modules", ".git", "site-packages", "__pycache__", "$recycle.bin", "system volume information", "windowsapps"}
PERSONAL = ("c:/users/admin/downloads", "c:/users/admin/software")
def walk(root, fo, personal, st):
    stack = [root]
    while stack:
        d = stack.pop(); dl = d.replace("\\", "/").lower()
        if dl.startswith(SKIP_SYS): continue
        is_pers = dl.startswith(PERSONAL)
        try: it = os.scandir(d)
        except Exception: st["unreadable_dirs"] += 1; continue
        with it:
            for e in it:
                try:
                    if e.is_symlink(): continue
                    if e.is_dir(follow_symlinks=False):
                        if e.name.lower() in SKIP_PARTS: continue
                        stack.append(e.path)
                    elif e.is_file(follow_symlinks=False):
                        ext = os.path.splitext(e.name)[1].lower()
                        if ext in EXT:
                            sz = e.stat(follow_symlinks=False).st_size
                            if sz >= MIN_BYTES:
                                rec = {"p": e.path.replace("\\", "/"), "s": sz, "x": ext}
                                (personal if is_pers or dl.startswith(PERSONAL) else fo).write(json.dumps(rec) + "\n"); st["files"] += 1; st["bytes"] += sz
                except Exception: st["errors"] += 1
def main():
    st = {"files": 0, "bytes": 0, "unreadable_dirs": 0, "errors": 0}; t0 = time.time()
    with open(OUT, "w") as fo, open(OUT + ".skipped-personal", "w") as pf:
        for root in ["A:/", "B:/", "C:/"]:
            if os.path.exists(root): walk(root, fo, pf, st); print(root, st, round(time.time() - t0), flush=True)
    print("DONE", st)
main()
