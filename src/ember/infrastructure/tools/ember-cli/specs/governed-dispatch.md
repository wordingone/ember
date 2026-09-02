<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

# Governed manifest dispatch

Status: CURRENT

Consumer: `tools/ember-cli/src/services/governed-dispatch.ts`

`ember dispatch-governed --manifest <absolute-path>` is a noninteractive
operator transport into the existing Ember Lab named-pipe authority. It does
not launch a process itself. The transport accepts only the closed
`governed_vertical` workload profile and the exact `gpu-q2-actual-update`
resource lease, binds the compiled CLI source identity, and sends the original
UTF-8 manifest bytes with their SHA-256 through `dispatch_manifest`.

Ember Lab remains the sole lease, admission, launcher, and preflight-receipt
authority. A returned receipt is accepted only when its lexical and canonical
paths are equal, it is strictly inside the manifest custody root, and its raw
SHA-256 matches the daemon response. Junctions, reparse aliases, cross-drive
paths, cross-UNC paths, malformed manifests, and nonpositive PIDs fail closed.

This transport grants no execution, model-update, or scientific-result credit.
