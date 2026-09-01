<!--
goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
issue: #898 packet-2 J
-->

# Installed cockpit-footprint soak design

## Outcome

Close packet J with a fresh, installed, two-hour-or-longer cockpit soak on the
exact current-master `ember.exe` and Ember Lab installation. The cockpit stays
on its existing cockpit-contract launcher. A separate v5, no-training governed
probe job keeps the merged VRAM and disk walls live without moving cockpit
absorption out of packet G.

## Authority boundaries

- Ember Lab remains the sole database writer. A new read-only JSON-RPC method
  returns one transactionally consistent wall-observation snapshot plus daemon
  source and executable hashes; the soak never opens SQLite directly.
- The process census records exact observed identity and classification facts;
  it never grants process-control authority. Foreign identities are receipted
  and never acted upon.
- Raw poll rows append below an absent durable output root. Finalization writes
  a self-hashed sealed summary without replacing either raw or final bytes.
- Caller-authored or fixture rows can prove validation and negative behavior,
  but cannot claim the installed soak executed.

## Poll and receipt shape

Each poll batch binds its timestamp and provider, candidate/admitted
cardinality, class cardinality, ownership-basis overlaps, and rows containing
PID, process start token, provider, class, commit bytes, parent PID, process
name, and ownership basis. The wall snapshot advances explicit VRAM and disk
sequence cursors and binds every returned row to the daemon source/executable
identity.

The sealed receipt binds the installed source and both executable hashes, raw
ledger hash, exact cockpit identity, sidecar job/manifest identity, duration,
cadence, four negative-harness outcomes, receipt-before-restart proof, wall
provider-unavailable debounce dispositions, and disk measurement durations
against the 250 ms cap.

After a 60 second settle, memory samples are divided into five-minute OLS
windows using the shared `linearFit` implementation. The receipt reports the
early-window calibration distribution and the complete final-hour slope band;
it does not copy a historical threshold. Independent review adjudicates the
measured plateau from those bound values.

## Test-first delivery

1. RED: require an identity-rich process poll batch and a read-only wall RPC.
2. RED: require create-new raw custody, monotone polling/cursors, closed schema,
   self-hash verification, OLS window accounting, and the four named negatives.
3. GREEN focused tests, full TypeScript/Rust gates, exact-head review, merge,
   and post-merge CI.
4. The integrator seat builds/installs the exact merged candidate, performs the orphan and
   headroom/overlap gates, launches the cockpit and sidecar, and runs the
   durable soak for at least two hours. The installed receipt then receives an
   independent evidence verdict; source tests alone do not close J.
