# WSL 9P Filesystem Tax — Measurement Plan & Probe Design

## Executive Summary

Recent generation runs show unaccounted wall-clock overhead above reported `gen_secs`. This probe measures the 9P filesystem penalty on `/mnt/b` (Windows-mounted) vs. ext4 on `/tmp` (native WSL2 scratch).

## Measured Unaccounted Time

Recent receipt analysis (B:/M/avir/leo/state/nc-ladder/receipts/):

| Receipt | Timestamp | gen_secs | Wall time | Unaccounted |
|---------|-----------|----------|-----------|-------------|
| w1-floor-g1-base-20260610T215814Z.json | 21:58:14 | 141.3s | ~420s (est. from mtime) | ~279s / 66% |
| w1-floor-g1-a-20260610T220325Z.json | 22:03:25 | 107.5s | ~322s (est.) | ~215s / 67% |
| w1-floor-g1-control-20260610T220712Z.json | 22:07:12 | 136.1s | ~458s (est.) | ~322s / 70% |
| w1-floor-g1-mtp-20260610T221956Z.json | 22:19:56 | 117.3s | ~538s (est.) | ~421s / 78% |

Sources: receipt JSONs carry `gen_secs` field; wall times inferred from mtime deltas across runs + samples.jsonl write completion.

**UNVERIFIED:** Exact wall-time bounds — receipts do not log start/end absolute times, only `gen_secs`. Overhead could include:
- Dataset loading / adapter I/O from `/mnt/b`
- Tokenization on Windows-mounted paths
- Model weight disk hits (if not preloaded)
- Housekeeping (logging, sample JSON serialization)
- 9P latency on each file operation

## Measurement Plan

### Design
A deterministic micro-benchmark that isolates filesystem tax by timing:
1. **Sequential read/write** of 10 MB, 100 MB files (realistic batch sizes)
2. **Random I/O** patterns (16 KB seek + read, repeated 1000× on a 1 GB file)
3. **Parallel ops** (2 threads reading / writing concurrently)

Each test runs on:
- `/mnt/b` (9P, Windows-mounted)
- `/tmp` (ext4, native WSL2)

Output: JSON receipt (YYYY-MM-DDTHH:MM:SSZ timestamp, all timings in ms, error on any OS error).

### Rationale
- **Sequential:** models load weights and datasets linearly (adapter weights, validation splits)
- **Random I/O:** tokenizer caches, sampler lookups during generation
- **Parallel:** concurrent model I/O under batch processing
- **10/100 MB / 1 GB sizes:** span realistic dataset chunks (validation split ~10-100 MB, full model weights 1-4 GB)

### Success Criterion
9P penalty > 20% on ≥2 op types → investigate pooling I/O or pre-staging datasets to `/tmp` before inference.

## Bench Script — `wsl9p_probe.py`

```python
#!/usr/bin/env python3
"""
WSL 9P filesystem tax micro-benchmark.

Measures sequential + random I/O on /mnt/b (9P) vs /tmp (ext4).
Emits receipt JSON to stdout.

Usage:
  python3 wsl9p_probe.py [--output /path/to/receipt.json]

Dependencies: stdlib only (os, sys, time, json, random, threading).
"""

import os
import sys
import json
import time
import random
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path


def now_iso():
    """Return current UTC timestamp as ISO 8601."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_sequential_write(path, size_bytes, name):
    """
    Write `size_bytes` sequentially to `path`.
    Return (elapsed_ms, error_str or None).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        start = time.perf_counter()
        with open(path, "wb") as f:
            chunk_size = 65536  # 64 KB chunks
            remaining = size_bytes
            while remaining > 0:
                to_write = min(chunk_size, remaining)
                f.write(os.urandom(to_write))
                remaining -= to_write
        elapsed_ms = (time.perf_counter() - start) * 1000
        return elapsed_ms, None
    except Exception as e:
        return None, str(e)
    finally:
        if path.exists():
            path.unlink()


def run_sequential_read(path, size_bytes, name):
    """
    Write `size_bytes` to `path`, then read it sequentially.
    Return (elapsed_ms, error_str or None) for read only.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # Write setup
        with open(path, "wb") as f:
            chunk_size = 65536
            remaining = size_bytes
            while remaining > 0:
                to_write = min(chunk_size, remaining)
                f.write(os.urandom(to_write))
                remaining -= to_write
        
        # Timed read
        start = time.perf_counter()
        with open(path, "rb") as f:
            while f.read(65536):
                pass
        elapsed_ms = (time.perf_counter() - start) * 1000
        return elapsed_ms, None
    except Exception as e:
        return None, str(e)
    finally:
        if path.exists():
            path.unlink()


def run_random_io(path, file_size_bytes, num_seeks=1000):
    """
    Create `file_size_bytes` file, then perform `num_seeks` random 16 KB reads.
    Return (elapsed_ms, error_str or None) for reads only.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # Setup: create file
        with open(path, "wb") as f:
            chunk_size = 65536
            remaining = file_size_bytes
            while remaining > 0:
                to_write = min(chunk_size, remaining)
                f.write(os.urandom(to_write))
                remaining -= to_write
        
        # Timed random reads
        read_size = 16384  # 16 KB
        start = time.perf_counter()
        with open(path, "rb") as f:
            for _ in range(num_seeks):
                offset = random.randint(0, max(0, file_size_bytes - read_size))
                f.seek(offset)
                _ = f.read(read_size)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return elapsed_ms, None
    except Exception as e:
        return None, str(e)
    finally:
        if path.exists():
            path.unlink()


def run_parallel_io(path, size_bytes, num_threads=2):
    """
    Write `size_bytes` file, then have `num_threads` read it concurrently.
    Return (elapsed_ms, error_str or None) for parallel reads only.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # Setup
        with open(path, "wb") as f:
            chunk_size = 65536
            remaining = size_bytes
            while remaining > 0:
                to_write = min(chunk_size, remaining)
                f.write(os.urandom(to_write))
                remaining -= to_write
        
        # Parallel reads
        results = []
        
        def reader():
            try:
                with open(path, "rb") as f:
                    while f.read(65536):
                        pass
                results.append(True)
            except Exception:
                results.append(False)
        
        start = time.perf_counter()
        threads = [threading.Thread(target=reader) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        if not all(results):
            return None, "Thread read failed"
        return elapsed_ms, None
    except Exception as e:
        return None, str(e)
    finally:
        if path.exists():
            path.unlink()


def main():
    output_path = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]
    
    receipt = {
        "timestamp": now_iso(),
        "hostname": os.uname().nodename,
        "platform": sys.platform,
        "results": {}
    }
    
    # Define test matrix: (size_bytes, op_type, function)
    tests = [
        (10 * 1024 * 1024, "seq_write_10m", 
         lambda p: run_sequential_write(p, 10 * 1024 * 1024, "seq_write_10m")),
        (100 * 1024 * 1024, "seq_write_100m",
         lambda p: run_sequential_write(p, 100 * 1024 * 1024, "seq_write_100m")),
        (10 * 1024 * 1024, "seq_read_10m",
         lambda p: run_sequential_read(p, 10 * 1024 * 1024, "seq_read_10m")),
        (100 * 1024 * 1024, "seq_read_100m",
         lambda p: run_sequential_read(p, 100 * 1024 * 1024, "seq_read_100m")),
        (1024 * 1024 * 1024, "random_io_1gb",
         lambda p: run_random_io(p, 1024 * 1024 * 1024, 1000)),
        (10 * 1024 * 1024, "parallel_read_10m",
         lambda p: run_parallel_io(p, 10 * 1024 * 1024, 2)),
    ]
    
    # Run on both /tmp (ext4) and /mnt/b (9P)
    for fs_root in ["/tmp", "/mnt/b"]:
        if not Path(fs_root).exists():
            receipt["results"][fs_root] = {"error": f"{fs_root} not mounted"}
            continue
        
        fs_results = {}
        for size, op_name, test_fn in tests:
            test_dir = Path(fs_root) / "wsl9p_probe" / op_name
            test_dir.mkdir(parents=True, exist_ok=True)
            test_file = test_dir / "testfile"
            
            elapsed_ms, error = test_fn(str(test_file))
            
            if error:
                fs_results[op_name] = {"error": error}
            else:
                fs_results[op_name] = {"elapsed_ms": round(elapsed_ms, 1)}
            
            # Cleanup
            try:
                if test_dir.exists():
                    import shutil
                    shutil.rmtree(test_dir)
            except:
                pass
        
        receipt["results"][fs_root] = fs_results
    
    # Compute penalty (9P overhead vs ext4)
    if "/tmp" in receipt["results"] and "/mnt/b" in receipt["results"]:
        tmp_res = receipt["results"]["/tmp"]
        b_res = receipt["results"]["/mnt/b"]
        
        penalties = {}
        for op in tmp_res:
            if op in b_res and "elapsed_ms" in tmp_res[op] and "elapsed_ms" in b_res[op]:
                tmp_t = tmp_res[op]["elapsed_ms"]
                b_t = b_res[op]["elapsed_ms"]
                if tmp_t > 0:
                    penalty_pct = ((b_t - tmp_t) / tmp_t) * 100
                    penalties[op] = round(penalty_pct, 1)
        
        receipt["penalties_pct"] = penalties
    
    # Output
    output_json = json.dumps(receipt, indent=2)
    
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            f.write(output_json)
        print(f"Receipt written to {output_path}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
```

## Execution & Integration

### Train-Daemon Eval Script
The bench script can be invoked by the train-daemon as an eval step:

```bash
python3 /path/to/wsl9p_probe.py --output /mnt/b/M/avir/leo/state/nc-ladder/receipts/wsl9p-probe-$(date +%Y%m%dT%H%M%SZ).json
```

Receipt structure:
```json
{
  "timestamp": "2026-06-10T15:30:00Z",
  "hostname": "...",
  "platform": "linux",
  "results": {
    "/tmp": {
      "seq_write_10m": {"elapsed_ms": 245.3},
      "seq_read_10m": {"elapsed_ms": 198.1},
      "random_io_1gb": {"elapsed_ms": 2847.5},
      "parallel_read_10m": {"elapsed_ms": 315.2}
    },
    "/mnt/b": {
      "seq_write_10m": {"elapsed_ms": 612.7},
      "seq_read_10m": {"elapsed_ms": 892.1},
      "random_io_1gb": {"elapsed_ms": 8234.1},
      "parallel_read_10m": {"elapsed_ms": 1204.5}
    }
  },
  "penalties_pct": {
    "seq_write_10m": 149.8,
    "seq_read_10m": 350.1,
    "random_io_1gb": 189.3,
    "parallel_read_10m": 281.9
  }
}
```

## Open Questions

1. **Exact wall-time bounds:** Receipt JSONs do not capture absolute start/end times — only `gen_secs` (model generation time). Can we add `start_ts` / `end_ts` to eval receipts to measure total overhead more precisely?
2. **Dataset location:** Are adapters and validation splits loaded from `/mnt/b` during generation, or pre-staged to GPU VRAM? If pre-loaded to `/tmp` before a run, the 9P tax would be invisible.
3. **Batch vs. single:** Is the 66-78% unaccounted overhead proportional to batch size, or fixed per-run housekeeping?
4. **Model prefetching:** Does Qwen2.5-Coder load full weights to `/tmp` at startup, or stream from `/mnt/b`? Streaming would amplify 9P penalty.

## Next Steps (if penalty > 20%)

- Profile a live eval run with `strace -e open,openat,read,write,seek` to identify hot paths
- Test pre-staging adapters + dataset to `/tmp` before generation
- Consider ramdisk (`tmpfs`) for volatile intermediate files during sampling

---

**Draft authored:** 2026-06-10  
**Receipt source:** B:/M/avir/leo/state/nc-ladder/receipts/ w1-floor-g1-*.json  
**Status:** Draft for gate review and lead rewrite
