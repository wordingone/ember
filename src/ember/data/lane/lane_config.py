# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Machine configuration for the data lane. Every machine root and every seat id comes from the environment; no tooling file carries a path or a seat name.

  EMBER_LANE_ROOT   runtime data root of the lane (logs, packed, loops, scratch, upq ...); the tooling directory is deployed as <root>/scripts
  EMBER_M_ROOT      parent directory that holds the lane root and the sibling trees the lane reads (custody, receipts, seat state trees)
  EMBER_SEAT_LEAD   seat id of the coordinating role: mailbox recipient and state-directory name
  EMBER_SEAT_TRAIN  seat id of the training role
  EMBER_SEAT_DATA   seat id of the data role (this lane)
  EMBER_CENSUS_SKIP_PREFIXES  ';'-separated lower-case path prefixes the census skips (other seats' trees, caches)

Reading a missing variable raises at first use, so a mis-deployed lane fails loudly instead of writing to a default location.
"""
import os

_ENV = {"LANE_ROOT": "EMBER_LANE_ROOT", "M_ROOT": "EMBER_M_ROOT", "SEAT_LEAD": "EMBER_SEAT_LEAD", "SEAT_TRAIN": "EMBER_SEAT_TRAIN", "SEAT_DATA": "EMBER_SEAT_DATA"}


def __getattr__(name):
    if name in _ENV:
        v = os.environ.get(_ENV[name], "")
        if not v:
            raise RuntimeError("%s is not set (see src/ember/data/lane/README.md)" % _ENV[name])
        return v.replace("\\", "/").rstrip("/") if name.endswith("ROOT") else v
    raise AttributeError(name)
