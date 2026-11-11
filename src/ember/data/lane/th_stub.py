# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Test stub for the TruffleHog binary, injected through TH_BIN (offline red tests only). make_launcher(dir) -> a .cmd that runs this file with the same arguments.
Behaviour by env TH_STUB_MODE: clean (rc 0, no output) | rc2 (exit 2) | broken (rc 0, a stdout line that starts with { but is not JSON) | sleep (TH_STUB_SLEEP seconds, then clean) |
flakeN, e.g. flake3 (exit 1 on the first N invocations, then clean) | foreign (rc 0, one valid finding whose file is not one of the targets) |
vanish (rc 0, empty stdout; a part vanished after the start: the last target is deleted, stderr carries the error line and a "finished scanning" line with bytes short of the targets; lead 83073) |
vanish_err (only the stderr error line: files intact, bytes right) | vanish_gone (only the last target deleted: stderr silent, bytes right) | vanish_bytes (files intact, no error line, bytes short).
Every mode except rc2 ends with the "finished scanning" stderr line the real binary writes (bytes = the summed target sizes, as measured on TruffleHog 3.99.8: real bytes are >= that sum). Every invocation appends "start <epoch> <ntargets>" and "end <epoch>" to TH_STUB_LOG (one line each)."""
import os, sys, time, json, glob


def read_lines(log):
    """All events of all invocations (each invocation writes its OWN file <log>.<pid>: parallel appends to one file lost lines on Windows)."""
    out = []
    for p in sorted(glob.glob(log + ".*")):
        try: out += open(p).read().split(chr(10))
        except OSError: pass
    return [l for l in out if l]


def clear(log):
    for p in glob.glob(log + ".*"):
        try: os.remove(p)
        except OSError: pass


def make_launcher(d):
    cmd = os.path.join(d, "th_stub.cmd")
    with open(cmd, "w") as f:
        f.write('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, os.path.abspath(__file__)))
    return cmd


if __name__ == "__main__":
    mode = os.environ.get("TH_STUB_MODE", "clean"); log = os.environ.get("TH_STUB_LOG")
    targets = [a for a in sys.argv[1:] if not a.startswith("--") and a != "filesystem"]

    def L(s):      # own file per invocation: no shared-file append race
        if log:
            with open("%s.%d" % (log, os.getpid()), "a") as f: f.write(s + chr(10))

    n_prev = sum(1 for l in read_lines(log) if l.startswith("start")) if log else 0
    L("start %.3f %d" % (time.time(), len(targets)))
    rc = 0
    total = sum(os.path.getsize(t) for t in targets if os.path.isfile(t)); fin_bytes = total
    ERR = {"level": "error", "logger": "trufflehog", "msg": "encountered errors during scan", "errors": ["GetFileAttributesEx %s: The system cannot find the file specified." % (targets[-1] if targets else "?")]}
    if mode in ("vanish", "vanish_err"): print(json.dumps(ERR), file=sys.stderr)
    if mode in ("vanish", "vanish_gone") and targets:
        try: os.remove(targets[-1])
        except OSError: pass
    if mode in ("vanish", "vanish_bytes"): fin_bytes = total // 2
    if mode == "rc2": rc = 2
    elif mode == "broken": print('{"DetectorName": "Fake", "Raw": "x"')
    elif mode == "sleep": time.sleep(float(os.environ.get("TH_STUB_SLEEP", "2")))
    elif mode.startswith("flake"): rc = 1 if n_prev < int(mode[5:]) else 0
    elif mode == "foreign": print(json.dumps({"DetectorName": "Fake", "Raw": "x", "SourceMetadata": {"Data": {"Filesystem": {"file": "Z:/nowhere/other.txt"}}}}))
    if mode != "rc2": print(json.dumps({"level": "info-0", "logger": "trufflehog", "msg": "finished scanning", "chunks": len(targets), "bytes": fin_bytes}), file=sys.stderr)
    L("end %.3f" % time.time())
    sys.exit(rc)
