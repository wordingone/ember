# Public history rewrite, 2026-11-21

On 2026-11-21 the public history of `wordingone/ember` was rewritten. This page records what
changed and what a holder of an older clone has to do. It is a custody record, not a
specification of current behavior.

## What changed

- The lab daemon source was removed from every commit. That covers the top-level runtime
  directory and the nested runtime directory under the domains tree. The removal from the
  current tree landed earlier in the C22 change (#2493); the rewrite also removes the source from
  all earlier commits.
- The session-link trailer lines (lines pointing at an assistant session page) were removed from
  commit messages.
- Because a commit id is a hash of its content, parents and message, every commit id changed.
- Files in the current tree that cited an old commit id were updated to cite the new id, and the
  content hashes pinned over those files were re-sealed. That change is one commit placed directly on
  the rewritten `master`.

## Old-to-new commit ids

The map is committed at
[`manifests/ember-01-custody/commit-rewrite-map-v1.json`](../../manifests/ember-01-custody/commit-rewrite-map-v1.json)
(schema `ember-commit-rewrite-map-v1`).

It is a partial map. It holds 38 old/new pairs, and only the implementation commits that the
public issue census cites through recorded issue comments. It is not a map of every commit. Issue
and pull-request comments on GitHub that quote an older id are unchanged and still show the old id.
To resolve an old id that is not in the file, search the rewritten history by commit subject
and author date.

## Where the lab source lives

The `ember-lab` daemon source lives in the private repository `wordingone/ember-lab`. Public
`ember` carries no lab source; the lab is installed from the released build, and the certified
launch binds to the installed release manifest (see the C22 changes #2493 and #2494).

## If you have an older clone

Your clone still holds the old history, and a fetch or pull will not reconcile it with the
rewritten one. Re-clone, or re-point the existing clone:

```text
git fetch origin
git checkout master
git reset --hard origin/master
```

The last command discards local commits on `master` that are not in the new history. Move any
work on branches or forks onto the new history first, for example with
`git rebase --onto origin/master <old-base-commit> <your-branch>`, where the old base commit is the
last old-history commit your branch builds on. Do not merge old and new histories together: that
re-introduces the removed source and the old commit ids.
