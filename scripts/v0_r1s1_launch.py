"""v0-r1s1 launch wrapper — frozen dispatch parameters for segment v0-r1s1.

Daemon-spawned (no CLI args). Sets EMBER_GATE_AUTHORIZED and delegates to
timeshare_pretrain.py --live with the frozen v0-r1s1 envelope.

Dispatch receipt: receipts/v0-live-<ts>.json (written by timeshare_pretrain).
"""
import os
import sys

os.environ["EMBER_GATE_AUTHORIZED"] = "1"

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR    = os.path.dirname(SCRIPTS_DIR)

SHARD_DIR  = "/mnt/b/M/avir/eli/state/ember-eng/shards-v0"
RUN_DIR    = "/mnt/b/M/avir/eli/state/ember-eng/runs/v0-r1s1"
STEPS      = 1702547      # floor(6,973,632,300 content_tokens / (batch=4 * seq=1024))
TOTAL_STEPS = 1702547
CKPT_EVERY  = 25000       # ~91 min per interval at ~4.57 steps/s (c03-qat paced)
SEGMENT_ID  = "v0-r1s1"

sys.path.insert(0, SCRIPTS_DIR)
import timeshare_pretrain  # noqa: E402

argv = [
    "--live",
    "--shard-dir",       SHARD_DIR,
    "--run-dir",         RUN_DIR,
    "--steps",           str(STEPS),
    "--total-steps",     str(TOTAL_STEPS),
    "--checkpoint-every", str(CKPT_EVERY),
    "--segment-id",      SEGMENT_ID,
]
timeshare_pretrain.main(argv)
