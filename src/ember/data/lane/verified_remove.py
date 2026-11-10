# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Verified / ruled delete paths shared by the NINE named lane deleters (#2454, review of #2452): ckpt_lineage_delete (probe_apply drives it), ckpt_backup, drop_execute, free_b, raw_roll, _pg_obj_del, _wiki_del, _ws_del and delete_approved_dirs.
It is NOT the one code path for every lane delete. Six removers stay outside it and still rest on their own server-copy check: drop_uploaded, clear_uploaded_shards, pg_verify_delete, _pack_del, reserve_evict, evict_ckpt_list (open items on #2454).
Two named paths, never mixed:
  remove_verified(path, repo, hf_path, ...)   the file has a SERVER copy. In this call, in this order: path contained in an allowed root (no link/junction on the way), regular file with
                                              st_nlink == 1, the server entry READ BACK NOW (no cache) with size AND an LFS sha256 (a missing entry, a missing LFS sha or an unreadable server keeps the file;
                                              there is no size-only fallback), the local sha256 recomputed NOW and the file unchanged while it was hashed, then the receipt row written + fsynced, then
                                              (size, mtime_ns, inode) compared once more against the first stat, then the remove.
  remove_dup(path, other, ...)                the file has a LOCAL duplicate outside the delete set: both sha256 recomputed now, same size, other is a different file, receipt first, the same final stat compare.
  remove_ruled(row, ...) / ruled_manifest()   NO copy exists (regenerable or derived data deleted under a lead ruling). NOT a verification: nothing is compared to any copy. It rests on (1) a ruling id that is a mail id ('lead 82451'),
                                              (2) a PIN: the plan sha256 (plan_sha: sorted path|size|mtime_ns|inode of the files found) that the lead saw in the dry run and ruled on, handed back as --manifest-sha256; a plan that differs
                                              refuses everything before any file is hashed or any manifest row is written; a caller whose pin is another artefact (ckpt_lineage_delete --expect-dirs) names it in `pinned_by`,
                                              (3) the manifest (path, size, sha256, mtime_ns, inode, pin) written + fsynced for ALL files before the first remove, (4) a re-check at each remove that the file is the one in the manifest. A row without a pin is refused (UNPINNED).
Every function returns dict(ok, why, bytes) and returns a named refusal instead of raising (a locked or vanished file while hashing is `hash failed: <ExceptionName>` / `stat failed after hashing: <ExceptionName>`); dry=True runs every check and stops
before the receipt and the remove; a refusal leaves the file in place. `remove` and `reader` are injectable so the reds run on a fake server in a tmp tree. The one raise: ruled_manifest raises ValueError for a missing or malformed ruling id (a programming error).
Receipt rows record what was actually compared (server size, server sha256, local sha256), not a fixed sentence."""
import os, sys, json, time, stat, hashlib, re

REPARSE = 0x400          # FILE_ATTRIBUTE_REPARSE_POINT: a junction or symlink on Windows


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(16 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _norm(p):
    return os.path.normcase(os.path.abspath(p)).replace("\\", "/").rstrip("/")


def _real(p):
    return os.path.normcase(os.path.realpath(p)).replace("\\", "/").rstrip("/")


def _is_link(p):
    try:
        st = os.lstat(p)
    except OSError:
        return False
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & REPARSE)


def contained(path, roots):
    """-> (root or None, why). The path is inside one of `roots` both as written and after resolving links, and no component from that root down to the file is a link or junction."""
    n = _norm(path); r = _real(path)
    for root in roots:
        rn = _norm(root); rr = _real(root)
        if not (n == rn or n.startswith(rn + "/")):
            continue
        if not (r == rr or r.startswith(rr + "/")):
            return None, "resolves outside the root (link or junction)"
        cur = os.path.abspath(root)
        for part in os.path.relpath(os.path.abspath(path), cur).replace("\\", "/").split("/"):
            cur = os.path.join(cur, part)
            if _is_link(cur):
                return None, "a link or junction on the path (" + part + ")"
        return root, ""
    return None, "outside every allowed root"


def _receipt(receipt, row):
    """Append + flush + fsync. Raises on any failure (the caller keeps the file)."""
    os.makedirs(os.path.dirname(os.path.abspath(receipt)), exist_ok=True)
    with open(receipt, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _refuse(why, size=0):
    return dict(ok=False, why=why, bytes=0, size=size)


def _pre(path, roots, require_nlink):
    root, why = contained(path, roots)
    if root is None:
        return None, _refuse(why)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None, _refuse("already gone")
    except OSError as e:
        return None, _refuse("stat failed: " + type(e).__name__)
    if not stat.S_ISREG(st.st_mode):
        return None, _refuse("not a regular file")
    if require_nlink and st.st_nlink != require_nlink:
        return None, _refuse("nlink %d != %d (another name exists: the catalog union or a kept child)" % (st.st_nlink, require_nlink), st.st_size)
    return st, None


def _hash_stable(path, st0):
    """-> (sha256, None) when the file hashed and is unchanged (size, mtime_ns) afterwards, else (None, named reason). Never raises (#2459 F4: a locked or vanished file is a refusal)."""
    try:
        sha = sha256_file(path)
    except Exception as e:
        return None, "hash failed: " + type(e).__name__
    try:
        st1 = os.lstat(path)
    except Exception as e:
        return None, "stat failed after hashing: " + type(e).__name__
    if (st1.st_size, st1.st_mtime_ns) != (st0.st_size, st0.st_mtime_ns):
        return None, "file changed while hashing"
    return sha, None


def _same(path, st0):
    """True when the file now has the (size, mtime_ns, inode) it had at the first stat. Any error is False."""
    try:
        st = os.lstat(path)
    except Exception:
        return False
    return (st.st_size, st.st_mtime_ns, st.st_ino) == (st0.st_size, st0.st_mtime_ns, st0.st_ino)


def _remove_checked(path, st0, remove, receipt, kind):
    """The last step of every path: compare the file with the first stat once more (the receipt fsync sits between the hash and here), then remove (#2459 F3)."""
    if not _same(path, st0):
        try:
            _receipt(receipt, dict(ts=now(), kind=kind + "-aborted", path=path.replace("\\", "/"), why="file changed after verification (size/mtime_ns/inode) before the remove; kept"))
        except Exception:
            pass
        return _refuse("file changed after verification (size/mtime_ns/inode), kept", st0.st_size)
    return _do_remove(path, st0.st_size, remove)


_RULING = re.compile(r"^(?:[A-Za-z]+ )?\d{5}\b")


def ruling_ok(r):
    """A ruling id is a mail id, optionally prefixed by the ruler: 'lead 82451', '82499', 'lead 82379 (ack of 82377)'. Free text such as 'x' is not one (#2459 F1)."""
    return bool(r) and bool(_RULING.match(str(r).strip()))


def plan_sha(paths):
    """The pin of a no-copy delete: sha256 of the sorted lines path|size|mtime_ns|inode (lstat; a path that cannot be stat'ed contributes path|MISSING|<ExceptionName>). The dry run prints it, the lead rules on it,
    --manifest-sha256 hands it back, and ruled_manifest refuses when the files found now give another value."""
    lines = []
    for p in paths:
        q = str(p).replace("\\", "/")
        try:
            st = os.lstat(p)
            lines.append("%s|%d|%d|%d" % (q, st.st_size, st.st_mtime_ns, st.st_ino))
        except Exception as e:
            lines.append("%s|MISSING|%s" % (q, type(e).__name__))
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


def pins_from_argv(argv):
    """--manifest-sha256 SHA (one plan) and/or --manifest-sha256 NAME=SHA (one per job) -> {'' or NAME: sha lowercase}."""
    out = {}
    for i, a in enumerate(argv):
        if a == "--manifest-sha256" and i + 1 < len(argv):
            k, eq, v = argv[i + 1].partition("=")
            if eq:
                out[k] = v.strip().lower()
            else:
                out[""] = argv[i + 1].strip().lower()
    return out


def hub_reader(repo_type="dataset"):
    """-> reader(repo, hf_path) that asks the server NOW (no cache). Returns None when the path is absent, (size, lfs_sha256 or None) when present; raises ServerUnreadable when the server cannot be read."""
    from huggingface_hub import HfApi
    api = HfApi()

    def read(repo, hf_path):
        try:
            got = api.get_paths_info(repo, [hf_path], repo_type=repo_type, expand=True)
        except Exception as e:
            if e.__class__.__name__ in ("EntryNotFoundError", "RepositoryNotFoundError", "RevisionNotFoundError"):
                return None
            raise ServerUnreadable(type(e).__name__ + ": " + str(e)[:120])
        got = [g for g in got if g.__class__.__name__ == "RepoFile" or hasattr(g, "size")]
        if not got:
            return None
        g = got[0]; l = getattr(g, "lfs", None)
        sha = (l.get("sha256") if isinstance(l, dict) else getattr(l, "sha256", None)) if l else None
        return (g.size, sha)
    return read


class ServerUnreadable(Exception):
    pass


def remove_verified(path, repo, hf_path, *, roots, receipt, authority, reader=None, remove=os.remove, require_nlink=1, extra=None, dry=False):
    """The file has a server copy. See the module docstring for the order. Returns dict(ok, why, bytes)."""
    st, bad = _pre(path, roots, require_nlink)
    if bad:
        return bad
    reader = reader or hub_reader()
    try:
        srv = reader(repo, hf_path)
    except ServerUnreadable as e:
        return _refuse("server unreadable: " + str(e), st.st_size)
    if not srv:
        return _refuse("no server entry for %s:%s" % (repo, hf_path), st.st_size)
    ssize, ssha = srv
    if not ssha:
        return _refuse("server entry has no LFS sha256 (a size-only comparison is refused)", st.st_size)
    if ssize != st.st_size:
        return _refuse("server size %s != local size %s" % (ssize, st.st_size), st.st_size)
    lsha, why = _hash_stable(path, st)
    if lsha is None:
        return _refuse(why, st.st_size)
    if lsha != ssha:
        return _refuse("sha256 mismatch: local %s != server %s" % (lsha[:12], ssha[:12]), st.st_size)
    row = dict(ts=now(), kind="server-verified", path=path.replace("\\", "/"), size=st.st_size, local_sha256=lsha, server_repo=repo, server_path=hf_path, server_size=ssize, server_sha256=ssha,
               compared="server size+LFS sha256 read back now == local size+sha256 recomputed now", authority=authority, **(extra or {}))
    if dry:
        return dict(ok=True, why="verified (dry run: nothing written, nothing removed)", bytes=st.st_size, size=st.st_size, dry=True)
    try:
        _receipt(receipt, row)
    except Exception as e:
        return _refuse("receipt write failed (" + type(e).__name__ + "), file kept", st.st_size)
    return _remove_checked(path, st, remove, receipt, "server-verified")


def remove_dup(path, other, *, roots, other_roots, receipt, authority, remove=os.remove, require_nlink=1, extra=None, dry=False):
    """The file has a local duplicate `other` that stays. Both hashed now; other must be a different file inside other_roots."""
    st, bad = _pre(path, roots, require_nlink)
    if bad:
        return bad
    oroot, why = contained(other, other_roots)
    if oroot is None:
        return _refuse("duplicate " + why, st.st_size)
    try:
        so = os.lstat(other)
    except OSError:
        return _refuse("duplicate missing", st.st_size)
    if not stat.S_ISREG(so.st_mode) or (so.st_ino and so.st_ino == st.st_ino and so.st_dev == st.st_dev) or _real(other) == _real(path):
        return _refuse("duplicate is the same file or not a regular file", st.st_size)
    if so.st_size != st.st_size:
        return _refuse("duplicate size %s != %s" % (so.st_size, st.st_size), st.st_size)
    a, wa = _hash_stable(path, st); b, wb = _hash_stable(other, so)
    if a is None or b is None:
        return _refuse(wa or wb, st.st_size)
    if a != b:
        return _refuse("sha256 mismatch against the duplicate", st.st_size)
    row = dict(ts=now(), kind="local-duplicate", path=path.replace("\\", "/"), size=st.st_size, local_sha256=a, duplicate=other.replace("\\", "/"), duplicate_sha256=b,
               compared="both sha256 recomputed now, same size, different file", authority=authority, **(extra or {}))
    if dry:
        return dict(ok=True, why="verified (dry run: nothing written, nothing removed)", bytes=st.st_size, size=st.st_size, dry=True)
    try:
        _receipt(receipt, row)
    except Exception as e:
        return _refuse("receipt write failed (" + type(e).__name__ + "), file kept", st.st_size)
    return _remove_checked(path, st, remove, receipt, "local-duplicate")


def ruled_manifest(paths, manifest, *, ruling, note, roots, require_nlink=0, pin=None, pinned_by=None):
    """NO-COPY path, step 1: check the ruling id and the PIN, then hash every path and write ALL rows (fsynced) before anything is removed. -> (rows, refused[(path, why)]).
    pin = the plan sha256 the lead ruled on (plan_sha of `paths`): the files found now must give exactly that value, before hashing and again after it; otherwise nothing is hashed or written (PIN_MISMATCH).
    pinned_by = a short name of ANOTHER pin the caller already enforced (ckpt_lineage_delete: 'expect-dirs sha256 ...'); recorded in every row. One of the two is required (NO_PIN)."""
    if not ruling_ok(ruling):
        raise ValueError("a no-copy delete needs a ruling id that is a mail id, e.g. 'lead 82451'")
    if not pin and not pinned_by:
        return [], [("*", "NO_PIN: a no-copy delete needs --manifest-sha256 (the plan sha256 the dry run prints) or a named pin; nothing hashed, nothing written")]
    plan = None
    if pin:
        plan = plan_sha(paths); want = str(pin).strip().lower()
        if plan != want:
            return [], [("*", "PIN_MISMATCH: the files found now give plan %s, the ruled plan is %s; nothing hashed, nothing written, nothing removed" % (plan[:16], want[:16]))]
    rows, refused = [], []
    for p in paths:
        st, bad = _pre(p, roots, require_nlink)
        if bad:
            refused.append((p, bad["why"])); continue
        sha, why = _hash_stable(p, st)
        if sha is None:
            refused.append((p, why)); continue
        rows.append(dict(ts=now(), kind="ruled-no-copy", path=p.replace("\\", "/"), size=st.st_size, sha256=sha, mtime_ns=st.st_mtime_ns, ino=st.st_ino, nlink=st.st_nlink, ruling=str(ruling), note=note, plan_sha256=plan, pinned_by=pinned_by))
    if pin and plan_sha(paths) != plan:
        return [], [("*", "PIN_MISMATCH: the files changed while they were hashed; nothing written, nothing removed")]
    os.makedirs(os.path.dirname(os.path.abspath(manifest)), exist_ok=True)
    with open(manifest, "a", encoding="utf-8") as f:
        f.write("".join(json.dumps(r) + "\n" for r in rows))
        f.flush()
        os.fsync(f.fileno())
    return rows, refused


def remove_ruled(row, *, roots, receipt, remove=os.remove, require_nlink=0, dry=False):
    """NO-COPY path, step 2: the file must still be the one the manifest row describes (size, mtime_ns, inode), under the same ruling and the same pin; receipt row first. Not server-verified and never labelled so."""
    if row.get("kind") != "ruled-no-copy" or not ruling_ok(row.get("ruling")) or not row.get("sha256"):
        return _refuse("not a ruled-no-copy manifest row")
    if not (row.get("plan_sha256") or row.get("pinned_by")):
        return _refuse("UNPINNED: the manifest row carries no plan sha256 and no named pin")
    p = row["path"]
    st, bad = _pre(p, roots, require_nlink)
    if bad:
        return bad
    if (st.st_size, st.st_mtime_ns) != (row["size"], row["mtime_ns"]) or (row.get("ino") and st.st_ino != row["ino"]):
        return _refuse("file is not the one in the manifest (size/mtime/inode changed since it was written)", st.st_size)
    rr = dict(ts=now(), kind="ruled-no-copy-remove", path=p, size=st.st_size, sha256=row["sha256"], ruling=row["ruling"], note=row.get("note"), plan_sha256=row.get("plan_sha256"), pinned_by=row.get("pinned_by"),
              compared="stat triple equals the manifest row; no server or local copy was compared (ruled regenerable/derived data: a ruling, not a verification)")
    if dry:
        return dict(ok=True, why="matches the manifest row (dry run: nothing written, nothing removed)", bytes=st.st_size, size=st.st_size, dry=True)
    try:
        _receipt(receipt, rr)
    except Exception as e:
        return _refuse("receipt write failed (" + type(e).__name__ + "), file kept", st.st_size)
    return _remove_checked(p, st, remove, receipt, "ruled-no-copy-remove")


def _do_remove(path, size, remove):
    try:
        remove(path)
    except FileNotFoundError:
        return dict(ok=True, why="already gone", bytes=0, size=size)
    except OSError as e:
        return _refuse("remove failed: " + type(e).__name__, size)
    if os.path.lexists(path):
        return _refuse("still present after remove", size)
    return dict(ok=True, why="removed", bytes=size, size=size)
