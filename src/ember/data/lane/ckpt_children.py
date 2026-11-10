# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Checkpoint backup (lead 81916): the child dirs to archive. id8 = first 8 hex of sha256(checkpoint-manifest.json)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT, SEAT_TRAIN
CH = {
 "H38": ("8ed2307c", (M_ROOT + "/ember-live-receipts/cia-hour-a1-five-attn-stage-d4-20261106T065417Z/measurement-0dd76650ae8b43a8be5ce845f72eeb49/trained-child"), False),
 "H39": ("d4a908e3", (M_ROOT + "/ember-live-receipts/cia-hour-a1-five-attn-stage-d4-20261107T073017Z/measurement-60bd6b8de01742389ea577ca2ccdbd0a/trained-child"), False),
 "H40": ("006350fd", (M_ROOT + "/ember-live-receipts/cia-hour-a1-five-attn-stage-d4-20261107T105931Z/measurement-a6056215e99b41959dba2bcef76ea30c/trained-child"), True),
 "H41": ("cb516ed9", (M_ROOT + "/ember-live-receipts/cia-hour-a1-five-attn-stage-d4-20261107T165532Z/measurement-8fe5f0ef58e34d68831174450d3f50d7/trained-child"), True),
 "H42": ("d87f4058", (M_ROOT + "/ember-live-receipts/cia-hour-a1-five-attn-stage-d4-20261107T211551Z/measurement-75eb7809865a4a8392ee9aa879923a37/trained-child"), True),
 "H43": ("0622d4c4", (M_ROOT + "/ember-live-receipts/cia-hour-a1-five-attn-stage-d4-20261108T064216Z/measurement-4cd3cb481d2a4ae883d12c032418598c/trained-child"), True),
 "SLEEP": ("09ab7273", (M_ROOT + "/avir/" + SEAT_TRAIN + "/state/sleep1-20261108/sleep1-fit-20261108T192045Z/measurement-sleep1/trained-child"), True),
}   # (id8, dir, refuted -> delete local after HF verify). H40-H42 path typo guard: assert exists below.
import json as _j, os as _o
if _o.path.exists((LANE_ROOT + "/logs/ckpt-old.json")):      # older children (lead 81919): upload + HF-verify only; refuted=False -> this script never deletes them
    for _r in _j.load(open((LANE_ROOT + "/logs/ckpt-old.json"))): CH[_r["name"]] = (_r["id8"], _r["dir"], False)
