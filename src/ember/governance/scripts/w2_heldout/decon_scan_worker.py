# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""decon_scan_worker.py -- Torch-free contamination scanner (memmap-based).

Zero torch/heavy imports. Pure numpy + rolling hash.
Uses memmap(mode='r') instead of np.fromfile to avoid full-array allocation.
Identical algorithm and return dict structure as contamination_recheck.

Suitable for multiprocessing workers (no CUDA DLL loads).
"""
import os
import numpy as np

# Constants (same as w1_collapse_control_run.py)
CONTAMINATION_WINDOW_TOKENS = 13
CONTAMINATION_ROLL_BASE = 256


def contamination_scan_memmap(eval_rows: list[list[int]],
                               shard_dir: str,
                               *,
                               window: int = CONTAMINATION_WINDOW_TOKENS,
                               roll_base: int = CONTAMINATION_ROLL_BASE,
                               corpus_verification_receipt: str = "receipts/corpus-verification-20260704T095213Z.json") -> dict:
    """Contamination scan using memmap instead of np.fromfile.

    Identical to contamination_recheck in logic; uses read-only memmap
    for lazy page-in instead of materializing full shards in RAM.

    Returns:
        dict with keys: method, corpus_verification_open_item_ref, shards_scanned,
        windows_hashed, confirmed_matches, hash_collisions_ruled_out, verdict.
        (NO 'wall_s' key -- computed by caller if needed)
    """
    mod = 1 << 64

    def _needle_hash(ids) -> int:
        h = 0
        b = 1
        for v in ids:
            h = (h + int(v) * b) % mod
            b = (b * roll_base) % mod
        return h

    def _sliding_windows(ids, w):
        n = len(ids)
        return [tuple(int(x) for x in ids[i:i + w]) for i in range(n - w + 1)] if n >= w else []

    # Build needle (evaluation batch) hash set
    needle_windows = []
    for row in eval_rows:
        needle_windows.extend(_sliding_windows(list(row), window))
    needle_hash_to_windows: dict[int, list[tuple]] = {}
    for w in needle_windows:
        needle_hash_to_windows.setdefault(_needle_hash(w), []).append(w)
    needle_hash_set = set(needle_hash_to_windows.keys())

    shard_paths = sorted(p for p in os.listdir(shard_dir) if p.endswith(".bin"))
    if not shard_paths:
        raise SystemExit(f"W1_LIVE_CONTAMINATION_NO_SHARDS: {shard_dir!r}")

    def _rolling_hashes(arr_u16):
        """Compute rolling hashes for all windows in arr."""
        n = arr_u16.shape[0]
        if n < window:
            return np.array([], dtype=np.uint64), 0
        arr64 = arr_u16.astype(np.uint64)
        n_out = n - window + 1
        h = np.zeros(n_out, dtype=np.uint64)
        power = np.uint64(1)
        rb = np.uint64(roll_base)
        with np.errstate(over="ignore"):
            for k in range(window):
                h += arr64[k:k + n_out] * power
                power = power * rb
        return h, n_out

    confirmed_matches: list[dict] = []
    candidate_collisions = 0
    total_windows_hashed = 0
    prev_tail = None
    prev_name = None
    needle_arr = (np.fromiter(needle_hash_set, dtype=np.uint64, count=len(needle_hash_set))
                  if needle_hash_set else np.array([], dtype=np.uint64))

    for name in shard_paths:
        # Use memmap(mode='r') instead of np.fromfile -- pages lazily
        shard_path = os.path.join(shard_dir, name)
        arr = np.memmap(shard_path, dtype="<u2", mode='r')
        n = arr.shape[0]

        hashes, n_out = _rolling_hashes(arr)
        total_windows_hashed += n_out
        if n_out and needle_hash_set:
            hit_idx = np.where(np.isin(hashes, needle_arr))[0]
            for i in hit_idx:
                i = int(i)
                candidate = tuple(int(x) for x in arr[i:i + window])
                hh = _needle_hash(candidate)
                if hh in needle_hash_to_windows and candidate in needle_hash_to_windows[hh]:
                    confirmed_matches.append({"shard": name, "offset": i,
                                               "window": list(candidate)})
                else:
                    candidate_collisions += 1

        if prev_tail is not None and n >= (window - 1) and needle_hash_set:
            join = np.concatenate([prev_tail, arr[:window - 1]])
            join_hashes, join_n = _rolling_hashes(join)
            total_windows_hashed += join_n
            if join_n:
                jhit = np.where(np.isin(join_hashes, needle_arr))[0]
                for i in jhit:
                    i = int(i)
                    candidate = tuple(int(x) for x in join[i:i + window])
                    hh = _needle_hash(candidate)
                    if hh in needle_hash_to_windows and candidate in needle_hash_to_windows[hh]:
                        confirmed_matches.append({
                            "boundary": f"{prev_name}|{name}",
                            "offset_in_join": i, "window": list(candidate)})

        prev_tail = arr[-(window - 1):].copy() if n >= (window - 1) else prev_tail
        prev_name = name
        # Explicitly delete memmap to release paging
        del arr

    return {
        "method": "13-token polynomial rolling hash (uint64 mod 2**64), hash "
                  "hits re-verified by exact elementwise comparison, "
                  "shard-to-shard boundary windows checked -- same convention "
                  "as scratch/corpus-wire/contamination_check.py",
        "corpus_verification_open_item_ref": corpus_verification_receipt,
        "shards_scanned": len(shard_paths),
        "windows_hashed": total_windows_hashed,
        "confirmed_matches": confirmed_matches,
        "hash_collisions_ruled_out": candidate_collisions,
        "verdict": "CLEAN" if not confirmed_matches else "CONTAMINATED",
    }


if __name__ == "__main__":
    import sys
    print("decon_scan_worker: torch-free contamination scanner (use via import)")
    sys.exit(0)
