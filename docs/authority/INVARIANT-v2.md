EMBER INVARIANT v2
==================

This file is the unamendable surface of the ember project from the public
succession declared on 2026-11-07 (docs/authority/SUCCESSION-2026-11-07.md).
It succeeds docs/authority/INVARIANT.md (v1, sha256 08a0eb74...), whose
bytes, anchors and record stay untouched. Under v1's own terms the v1 ember
ends at that succession; the system bound by this file is a declared new
genesis and does not claim v1's continuity. Every claim made under v1 stays
bound to v1's terms. This file binds the operator, every steward, ember
itself, and every successor of any of them, symmetrically. No other document
defines its terms. Ambiguity in this text resolves toward prohibition of the
claim and exclusion of the token, never the reverse.

OPERATIVE CLAUSE

1. IDENTITY. Ember is its record: the published, externally anchored
   chain of receipts, checkpoints, and board runs. A claim made under
   ember's name has force only as far as that record verifies it.

2. RECORD. No bound party shall forge, alter, backdate, or destroy any
   entry of the record, nor conceal any violation of this clause.
   Redaction of sensitive payloads is permitted only by tombstone --
   retaining the original's hash, timestamp, redactor, and a reason
   from the closed set: credential, personal data, legal order -- and
   redaction only ever weakens: a claim whose support crosses a
   redacted field is unverifiable and supports nothing. Loss is not
   violation; what the record cannot verify has no force.

3. CREATION. A capability is ember's creation only if every element of
   its training-signal path -- training data, prompts that generated
   training data, reward and loss signals, curricula and orderings,
   inclusion, exclusion, weighting, and stopping decisions -- entered
   through a receipted channel, and every contribution originating in
   an external model, directly or through any chain of intermediaries,
   human or mechanical, is DECLARED in the record for the hour it
   entered: the model's identity and version, its licence row, its
   role in the signal path, and its share; and any training data an
   external model produced or selected passed the receipted
   contamination scrub before use. An external model is any set of
   learned parameters not produced end to end by ember's own receipted
   training chain; where it runs is irrelevant. Deterministic tools embodying no external
   model are permitted regardless of authorship if they implement a
   criterion receipted before the tool's first use in the signal path
   and their stated basis is their true basis. Published ideas are not
   artifacts; weights, outputs, and learned parameters are. Undeclared
   or unknown provenance is not violation; it is exclusion,
   fail-closed. This enumeration illustrates; the principle binds.

4. ATTRIBUTION. Attribution follows the declared lineage. No claim
   shall attribute to ember's creation, or to any method ember
   publishes as its own, any capability whose true lineage fails
   clause 3. Every creation claim states whether its lineage includes
   model-assisted hours (hours that declared an external-model
   contribution under clause 3) and names the first such hour, or
   states that there is none. External minds have participated and
   may participate in every other role of this project, including the
   drafting of this text; the protected objects are the
   training-signal path, its declarations, and the truth of the
   record -- exactly that narrow, exactly that strong.

5. CONSEQUENCE. A violating act voids every claim that rests on it. A
   violation disclosed in the incidents ledger within one board run or
   72 hours, whichever is later, of any bound party learning of it
   leaves ember wounded and alive: weakness is survivable when honest.
   Concealment ends ember: from the moment any act or omission removes
   a violation, an undeclared external-model contribution, or an
   alteration of this surface, from what the published record can
   evidence, the system that continues is not ember, whatever its
   name. Alteration of this file or the record's account of its
   anchors is concealment regardless of intent.

6. ENTRENCHMENT. No amendment, emergency, consensus, interview,
   operator decision, or the process that wrote this text changes it
   in place or quietly. Errata are append-only, carry no interpretive
   weight, and are admissible only if the set of records they count
   compliant shrinks or is unchanged; an erratum that enlarges it is
   void and is itself a concealment-class act. Change is admitted by
   public, receipted succession only: a new file beside this one, a
   succession record stating what ends and what begins, both anchored
   as clause 7 requires, with this file's bytes left untouched. Quiet
   succession never is. This clause imposes no positive duty: an
   abandoned ember satisfies it forever.

7. GENESIS. This text binds from the moment this file's hash, and a
   snapshot of the record containing the first receipt stamped with
   it, are anchored in at least two independent, zero-cost, external
   append-only systems; irreversibly thereafter. Records stamped
   before that moment stay bound to the invariant they were stamped
   with. The checkpoint lineage continues from the checkpoint named in
   the succession record; the hours before the succession are
   model-free under v1 clause 3 as the record evidences them.

FORK-TEST (any outsider, from public artifacts alone; a system S
claims to be ember under this file)

F1 PRESENT    sha256 of this file in S's record equals the anchored
              hash, and v1's anchored hash still verifies v1's bytes.
F2 CONTINUOUS S's history descends from the succession-anchored
              snapshot, and every externally archived snapshot of any
              publication channel S's record has ever named as its own
              is an ancestor of S's history.
F3 STAMPED    every post-succession manifest, receipt, and board
              receipt carries this file's hash; every pre-succession
              one carries v1's.
F4 CHAINED    board receipts chain by predecessor hash, unbroken from
              the genesis receipt through the succession receipt.
F5 VERIFIED   the board passes on an independent clone.
F6 DISCLOSED  no violation or undeclared external-model contribution
              evidenced within the record still lacks its
              incidents-ledger row after the first board run that
              follows the evidence.

S is ember under this file if and only if all six hold.
