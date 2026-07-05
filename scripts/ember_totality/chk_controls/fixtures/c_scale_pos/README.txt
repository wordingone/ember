LANE-14 CHK CONTROL FIXTURE (docs/spec/conditions-v1.md S4.2 C-SCALE;
docs/goalforge-debate-ledger.md row R8) -- synthetic, far-future-dated
control fixture, NOT a real receipt.

Deviation from the write_json()/SYNTHETIC_MARKER convention used by the
other builders in this file: test_c_scale.py hard-rejects any candidate
receipt carrying `_synthetic_control_fixture` before it ever reaches the
CHK check (`failures.append(f"{name}: synthetic control fixture, never
evidence")`). So the one file per fixture root that the probe must actually
EVALUATE (accepted for POS / evaluated-and-rejected-for-the-sharp-reason
for NEG) -- scale-credibility-*.json -- is written marker-free via a local
write_json_no_marker() helper (plain json.dump). Every other file in this
fixture (the W2 free_cognitive_mode_transition_receipt support artifact)
still carries the marker via write_json(), since it is only ever resolved
by path/existence (resolve_in_tree), never itself glob-matched or content-
inspected by the probe. This isolation note stands in for the marker on the
one file that cannot carry it: this fixture root must never be treated as
real evidence if it leaks outside chk_controls/fixtures/.
