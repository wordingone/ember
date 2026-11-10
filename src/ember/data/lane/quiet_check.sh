#!/bin/bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# lead 81897/81907: pure-bash (NO python) check of ALL quiet windows in reserve.json: every pair "<prefix>quiet..._from" / "<prefix>quiet..._until" (e.g. quiet_from/quiet_until,
# probe_quiet_from/probe_quiet_until, quiet2_from/quiet2_until). Prints "QUIET until <t>" (exit 3) when now is inside ANY window, else "OK" (exit 0). The model runs this FIRST and only launches python on OK.
F=${QUIET_FILE:-$EMBER_LANE_ROOT/loops/reserve.json}
now=$(date -u +%s)
for key in $(grep -o '"[A-Za-z0-9_]*quiet[A-Za-z0-9_]*_from"' "$F" 2>/dev/null | tr -d '"'); do
  ukey="${key%_from}_until"
  a=$(grep -o "\"$key\": *\"[^\"]*\"" "$F" | sed 's/.*: *"\(.*\)"/\1/'); b=$(grep -o "\"$ukey\": *\"[^\"]*\"" "$F" | sed 's/.*: *"\(.*\)"/\1/')
  [ -n "$a" ] && [ -n "$b" ] || continue
  ea=$(date -u -d "$a" +%s 2>/dev/null); eb=$(date -u -d "$b" +%s 2>/dev/null)
  if [ -n "$ea" ] && [ -n "$eb" ] && [ "$now" -ge "$ea" ] && [ "$now" -lt "$eb" ]; then echo "QUIET until $b ($key)"; exit 3; fi
done
echo OK; exit 0
