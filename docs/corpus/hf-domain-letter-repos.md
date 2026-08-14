# HF corpus publication: one repo per charter domain letter

Convention for publishing acquired corpus rows to the Hugging Face Hub, per the
research lead's ruling of 2026-08-14, governing issue #1720.

## The convention

```
wordingone/ember-corpus-<letter>-<domain-shortname>
  README.md              # per-source license table (see below)
  raw/<source-slug>/     # one subdirectory per acquired row
```

- The **per-domain repo is the auditable unit**, not the row. 44 rows must not
  become 44 repos.
- **Private by default.** A repo goes public only when *every* row inside it has
  verified redistribution rights.

Repo ids are derived mechanically from `wave_manifest.CHARTER_DOMAINS`, which is
already the charter's letter -> shortname authority; they are not a second
hand-maintained list. Slug rule: lowercase, `/` and space -> `-`, drop other
non-alphanumerics.

| Letter | `CHARTER_DOMAINS` shortname | Repo id |
|---|---|---|
| A | Math | `wordingone/ember-corpus-a-math` |
| B | Stats/Inference | `wordingone/ember-corpus-b-stats-inference` |
| C | Physics/Dynamics | `wordingone/ember-corpus-c-physics-dynamics` |
| D | CS/Systems | `wordingone/ember-corpus-d-cs-systems` |
| E | ML/AI | `wordingone/ember-corpus-e-ml-ai` |
| F | Training-infra/CUDA/HW | `wordingone/ember-corpus-f-training-infra-cuda-hw` |
| G | Logic/Proof | `wordingone/ember-corpus-g-logic-proof` |
| H | SWE | `wordingone/ember-corpus-h-swe` |
| I | Data/Eval/Decon | `wordingone/ember-corpus-i-data-eval-decon` |
| J | Sci-method/Lab-ops | `wordingone/ember-corpus-j-sci-method-lab-ops` |
| K | Application worlds | `wordingone/ember-corpus-k-application-worlds` |

The derived name for A reproduces the ruling's own worked example
(`ember-corpus-a-math`), which is why the derivation is preferred over a fresh
list. The `baseline` pseudo-domain in `CHARTER_DOMAINS` is not a charter letter
and gets no repo.

## Existing hub state — this is not greenfield

One repo exists under the account today: **`wordingone/ember-custody`**, and it
is **public**. It is the mirror-only custody-inventory sync from issue #1308
(`scripts/hf_custody/`, `docs/custody/hf-sync.md`) — a different surface with a
different purpose. It is **not** renamed, folded in, or otherwise touched by
this convention. No `ember-corpus-*` repo exists yet.

`hf_fetch.py` is a **download** connector (hub -> local) and is not the
publication path; the only upload code in the repo is `scripts/hf_custody/sync.py`.
Naming/layout logic therefore belongs on the publication side, not in
`hf_fetch.py`.

## Row placement for the currently landed rows

Source of truth: the acquisition lane's dated resolution map
(`_resolution-map-20260814.json`, schema `acq-lead-resolution-map-v1`) in the
out-of-tree corpus data root, which records 13 LANDED rows. That tree is
already filed by charter letter (`text-lab/<LETTER>/<row>/`), so placement is a
direct lift.

| Row | Letter | Destination |
|---|---|---|
| openstax-math | A | `ember-corpus-a-math` : `raw/openstax-math/` |
| stackexchange-math | A | `ember-corpus-a-math` : `raw/stackexchange-math/` |
| metamath-set-mm | B | `ember-corpus-b-stats-inference` : `raw/metamath-set-mm/` |
| stackexchange-stats | B | `ember-corpus-b-stats-inference` : `raw/stackexchange-stats/` |
| stackexchange-physics | C | `ember-corpus-c-physics-dynamics` : `raw/stackexchange-physics/` |
| stackexchange-cs | D | `ember-corpus-d-cs-systems` : `raw/stackexchange-cs/` |
| stackexchange-ai | E | `ember-corpus-e-ml-ai` : `raw/stackexchange-ai/` |
| llvm-docs | F | `ember-corpus-f-training-infra-cuda-hw` : `raw/llvm-docs/` |
| lean-mathlib-docs | G | `ember-corpus-g-logic-proof` : `raw/lean-mathlib-docs/` |
| python-language-docs | H | `ember-corpus-h-swe` : `raw/python-language-docs/` |
| rust-reference-docs | H | `ember-corpus-h-swe` : `raw/rust-reference-docs/` |
| ros-docs | K | `ember-corpus-k-application-worlds` : `raw/ros-docs/` |
| stackexchange-robotics | K | `ember-corpus-k-application-worlds` : `raw/stackexchange-robotics/` |

StackExchange does **not** map to a single letter: the six fetched sites land in
six different domain repos (A, B, C, D, E, K), one row each. There is no
"StackExchange repo" under this convention, by design — the repo is the domain,
the row is the site.

Placement follows the resolution map's recorded `domain` field, including one
assignment that looks doubtful and is deliberately **not** silently changed
here: `metamath-set-mm` (a CC0 formal-proof corpus) is recorded as **B**
Stats/Inference `train-0`, where **G** Logic/Proof is its natural home. G
currently holds only `train-1` (lean-mathlib-docs), so moving it would fill G's
`train-0` and reopen B's. Flagged for the research lead; the map stays
authoritative until reruled.

## README license table (required in every repo)

Each repo's `README.md` carries one row per `raw/` subdirectory:

| column | source |
|---|---|
| `source` | row slug (the `raw/<slug>/` directory name) |
| `license` | the row's resolved license, as evidenced |
| `license_evidence` | the external artifact the license was read from |
| `admissible` | whether the license is in the training-admission allow-list |
| `sha256` | row content hash from its connector receipt |

Licenses are read from the source itself (GitHub license API, OpenStax CMS
`license_url`, HF card frontmatter), never from the `wave_manifest` table's own
assertion — `BulkVein.build_argv` already refuses self-referential evidence.

## Publication gate: private until every row is redistributable

The public/private decision is per repo and is **not** satisfied today. Nine of
the thirteen landed rows carry a license outside
`tools/ember-restart-3b/text_lab_corpus.py`'s `LICENSES` allow-list
(`CC0-1.0`, `CC-BY-4.0`, `MIT`, `Apache-2.0`, `BSD-3-Clause`, `PDDL-1.0`):

- `CC-BY-SA-4.0` — the six StackExchange rows (share-alike, not in the list)
- `Python-2.0` — python-language-docs
- `Apache-2.0-WITH-LLVM-exception` — llvm-docs
- `MIT-OR-Apache-2.0` — rust-reference-docs

The last two are SPDX *expressions* rather than bare identifiers and may be
admissible once normalized; the first two are genuine policy questions. Either
way the allow-list is the admission authority, so **every domain repo starts
private** and none flips public until its rows clear that gate. See #1720's
license-mismatch follow-up for the mechanical check.
