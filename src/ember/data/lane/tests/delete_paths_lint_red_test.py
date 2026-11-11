# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Class guard for #2454: every lane script that can delete a file is classified, and the verified ones really use verified_remove.py.
A script counts as a deleter when its AST mentions os.remove / os.unlink / shutil.rmtree / os.rmdir / .unlink / .rmtree (a call OR a reference such as `remove=os.remove`).
  VERIFIED     the nine scripts #2454 names: must import verified_remove, must not call os.remove/os.unlink/shutil.rmtree themselves, and must keep module level free of statements that run on import.
  OWN_PROOF    deleters with their own server+hash proof and a red test of their own (named below with the test).
  UNREVIEWED   the frozen baseline of deleters nobody has reviewed yet (many are scratch/temp cleanups). It can only shrink: a script that is not in any set and gains a delete fails this test
               (route it through verified_remove, or review it and add it to a set with the reason), and a baseline entry that no longer deletes anything is reported stale.
Run: python scripts/tests/delete_paths_lint_red_test.py"""
import os, sys, ast, glob
HERE = os.path.dirname(os.path.abspath(__file__)); SC = os.path.dirname(HERE)
ok = True


def check(label, cond, detail=""):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", label, detail)


VERIFIED = ["ckpt_lineage_delete", "drop_execute", "delete_approved_dirs", "_pg_obj_del", "_wiki_del", "_ws_del", "raw_roll", "free_b", "ckpt_backup"]
OWN_PROOF = {"drop_uploaded.py": "st_nlink==1 + server size + LFS sha256 == recomputed sha, receipt before remove (tests/drop_uploaded_red_test.py)",
             "verified_remove.py": "the helper itself (tests/verified_remove_red_test.py)",
             "gh_snapshot_fetch.py": "removes only its own per-repo staging clone: realpath strictly inside the staging tree (StagingEscape otherwise), receipt row fsynced before the remove, repo refetchable from the catalogue commit (tests/gh_snapshot_fetch_red_test.py h1-h7)"}
UNREVIEWED = ['_alarm_redtest.py', '_cap_redtest.py', '_pack_del.py', 'a_relocate.py', 'audit_job.py', 'audit_probe_atrain2.py', 'audit_secrets.py', 'bulk_lane.py', 'caselaw_lane_handoff.py', 'ccby_pack.py', 'ckpt_bound.py',
              'ckpt_restore.py', 'clear_uploaded_shards.py', 'evict_ckpt_list.py', 'fetch_open_model.py', 'fill_nh.py', 'hold_flag.py', 'mls_pack.py', 'net_cap.py', 'pack.py', 'pg_verify_delete.py', 'redact_r1.py',
              'rehydrate_shards.py', 'remedy_hheldout2.py', 'remedy_move.py', 'repack_r1.py', 'repack_r1_all.py', 'reserve_evict.py', 'restore_finish.py', 'scratch_dir.py', 'se_drive.py', 'se_prep.py', 'se_sample.py',
              'secret_scan.py', 'text_lane.py', 'th_bisect.py', 'th_gate.py', 'th_rescan_hf.py', 'upload_worker.py']
DEL_NAMES = {"os.remove", "os.unlink", "shutil.rmtree", "os.rmdir"}


def deleters(path):
    t = ast.parse(open(path, encoding="utf-8").read()); found = set()
    for n in ast.walk(t):
        if isinstance(n, ast.Attribute) and (ast.unparse(n) in DEL_NAMES or n.attr in ("unlink", "rmtree")): found.add(ast.unparse(n))
    return t, found


scan = {os.path.basename(p): deleters(p) for p in sorted(glob.glob(SC + "/*.py"))}
classified = {v + ".py" for v in VERIFIED} | set(OWN_PROOF) | set(UNREVIEWED)
new = sorted(f for f, (t, d) in scan.items() if d and f not in classified)
check("no unclassified deleter: every script that can delete a file is verified, has its own proof, or is on the frozen unreviewed list", not new, ("new deleters: " + str(new)) if new else "")
stale = sorted(f for f in UNREVIEWED if f in scan and not scan[f][1])
check("no stale entry on the unreviewed list (a script there that no longer deletes should be removed from it)", not stale, str(stale) if stale else "")
missing = sorted(f for f in UNREVIEWED if f not in scan)
check("every unreviewed entry still exists as a script (or the list is updated)", not missing, str(missing) if missing else "")
for v in VERIFIED:
    f = v + ".py"
    if f not in scan: check(f"{v}: present", False); continue
    t, d = scan[f]
    imports = any((isinstance(n, ast.Import) and any(a.name == "verified_remove" for a in n.names)) for n in ast.walk(t))
    calls = {ast.unparse(n.func) for n in ast.walk(t) if isinstance(n, ast.Call)} & {"os.remove", "os.unlink", "shutil.rmtree"}
    body_bad = [type(n).__name__ for n in t.body if isinstance(n, (ast.For, ast.While, ast.Try, ast.With)) or (isinstance(n, ast.If) and "__name__" not in ast.unparse(n.test))]
    check(f"{v}: imports verified_remove, makes no direct os.remove/unlink/rmtree call, nothing loops or branches at module level (import != run)", imports and not calls and not body_bad, f"imports={imports} calls={sorted(calls)} top={body_bad}")
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
