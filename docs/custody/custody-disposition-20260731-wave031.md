# C-CUSTODY Wave 31 historical residue disposition

<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

This note disposes only the nine named historical citations below. It neither restores nor
reconstructs bytes, grants capability credit, nor turns non-canonical evidence into public-master
evidence. The scan was performed against exact public base
`52d6d49037719e26b0268865037d295171f9a589` using all locally reachable Git refs.

## Exact cross-lineage bytes barred from public master

Each row has an exact historical Git object, but the bytes contain private host-path material
forbidden by the current repository content rail. The correct action is to preserve the immutable
source commit and byte digest, not to copy those bytes onto public master.

| ref | source commit | exact byte SHA-256 | disposition |
|---|---|---|---|
| `receipts/ember-c-scale/w1-collapse-control-20260704T144548Z.json` | `33df343e14c2a19a572b21dac9aa8cc69482d86e` | `80806b2b77ef09f37b5ef86299449ece1b5012caaf7020e34a5de36b66cff4b2` | `CROSS_LINEAGE_CONTENT_RAIL_BARRED` |
| `receipts/ember-preloop-resident-gate/avir-cli-full-parity-harness-gate-20260704T055811Z.json` | `13c39f7a587792ce9a70998984e3d46e4177769d` | `7302e7f3ef819a49713ada49de695c38f29b2a541dd1ba4e1db7c90d3c729184` | `CROSS_LINEAGE_CONTENT_RAIL_BARRED` |
| `receipts/ember-preloop-resident-gate/real-avir-uiux-ax-observation-20260704T055355Z.json` | `13c39f7a587792ce9a70998984e3d46e4177769d` | `7fe8a40fc0945a1d16444557203e821ca72659eabfad35de49820b62969db629` | `CROSS_LINEAGE_CONTENT_RAIL_BARRED` |
| `receipts/shatter-verdict-bf16ns5-20260623T132000Z.json` | `6c9b3d74c35b010ea69516d8240de9c634b613a4` | `fa5a9e63d35c3170f79dcb6b8faca854e9ad15baeabafbc8de00223a61e47123` | `CROSS_LINEAGE_CONTENT_RAIL_BARRED` |
| `receipts/shatter-verdict-canonical-20260623.json` | `6c9b3d74c35b010ea69516d8240de9c634b613a4` | `d7ffa53f7d6bf3bdb30b1ec47da635b059c90cff3586705c0182d2a4e149a4b9` | `CROSS_LINEAGE_CONTENT_RAIL_BARRED` |

## Claimed identities with no reachable Git object

Every reachable ref was searched by exact path. These four identities never appear as Git tree
entries. The expected hashes are retained from their historical citers; they do not prove that the
bytes were ever published.

| ref | expected SHA-256 | disposition |
|---|---|---|
| `receipts/ember-c-scale/w2-heldout-decontam-20260707T055843Z.json` | `24e471f072d07d32bb3e012c695e9219ea35de0a0eafa1ce1d9a2c442660bbb3` | `DECLARED_HASH_ZERO_GIT_TRACE` |
| `receipts/ember-preloop-resident-gate/reference-cli-full-parity-harness-gate-20260622T152000Z-real-reference-observed.json` | `330c51d9d32934e7c6216f05540c9dbfbdfa6c7ccd1385c2fe8dd707a42d10ff` | `DECLARED_HASH_ZERO_GIT_TRACE` |
| `receipts/ember-preloop-resident-gate/reference-cli-full-parity-harness-gate-20260622T154500Z-real-reference-observation-blocked.json` | `34cd8547c77ccca33cd8b9aa0a3452923a751734e39ba2e0759746b3afd71bc2` | `DECLARED_HASH_ZERO_GIT_TRACE` |
| `receipts/ember-resident-training-gate/resident-training-gate-20260622T152500Z-real-reference-observed.json` | `f6992b3ae157f0e698eefd4740805cd5815ac4627da6775986c1183eb228c8a2` | `DECLARED_HASH_ZERO_GIT_TRACE` |

## Claim boundary

These dispositions resolve repository custody accounting only. They do not validate the historical
claims, satisfy the missing experiments, close their governing issues, or authorize deletion of
any reachable ref. Exact cross-lineage bytes remain reconstructible by the recorded commit/path;
zero-trace rows remain explicitly unreconstructible.
