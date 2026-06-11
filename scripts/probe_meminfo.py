"""probe_meminfo.py — does torch.cuda.mem_get_info report sane free VRAM here?

4 identical r1 crashes raised unsloth's "No or negligible GPU memory" guard,
which fires only when mem_get_info free*0.5 <= 1e-9, i.e. free ~= 0 bytes.
nvidia-smi showed 330MiB used at launch. Hypotheses:
  H-A: WSL2 /dev/dxg driver misreports free=0 -> fused CE can NEVER work here.
  H-B: free is sane idle; step-0 transient reservations zero it out.
Receipt: receipts/probe-meminfo-<ts>.json
"""
import json
import os
import sys
from datetime import datetime, timezone

import torch
from receipt_write import checked_write

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
out = {"ticket": "NC0-r1-diag", "cuda_available": torch.cuda.is_available()}

if torch.cuda.is_available():
    free, total = torch.cuda.mem_get_info(0)
    out["idle"] = {"free_gb": round(free / 2**30, 3),
                   "total_gb": round(total / 2**30, 3)}
    x = torch.empty(256 * 2**20, dtype=torch.float32, device="cuda")  # 1 GiB
    free2, _ = torch.cuda.mem_get_info(0)
    out["after_1gb_alloc"] = {"free_gb": round(free2 / 2**30, 3),
                              "delta_gb": round((free - free2) / 2**30, 3)}
    del x
    out["verdict"] = ("H-A: mem_get_info broken (free~0 idle)"
                      if out["idle"]["free_gb"] < 0.5 else
                      "H-B: mem_get_info sane idle -> step-0 transient")
else:
    out["verdict"] = "NO-CUDA (probe invalid)"

ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
path = f"{NC}/receipts/probe-meminfo-{ts}.json"
checked_write(path, out)
print(json.dumps(out, indent=2))
print("PROBE_MEMINFO_DONE", file=sys.stderr)
