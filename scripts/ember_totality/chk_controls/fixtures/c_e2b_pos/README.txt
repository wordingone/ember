LANE-14 CHK CONTROL FIXTURE (docs/spec/conditions-v1.md S4.2 C-E2B;
docs/goalforge-debate-ledger.md row R8) -- synthetic, far-future-dated
control fixture, NOT a real receipt.

Deviation from the write_json()/SYNTHETIC_MARKER convention: test_c_e2b.py
hard-rejects any candidate receipt carrying `_synthetic_control_fixture`
before it reaches the CHK check, identically to test_c_scale.py. The one
file per fixture root the probe must actually EVALUATE --
e2b-paired-surpass-*.json -- is written marker-free via
write_json_no_marker(). The referenced protocol_frozen_ref support artifact
(e2b-protocol-frozen-*.json) still carries the marker via write_json() --
it is only resolved by path/existence + a timestamp regex over its own
filename (never content-inspected), and it sorts alphabetically AFTER the
paired-surpass receipt within the same directory, so the probe's glob loop
evaluates and emits/exits on the real target before ever reaching the
marked support file. This isolation note stands in for the marker on the
file that cannot carry it.
