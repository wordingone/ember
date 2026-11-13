# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""GH Archive hour files -> candidate merged PRs with same-repo closing-keyword issue refs, non-bot, size-capped (no date wall since 2026-11-11, lead 83389: merged_at is recorded as content_date_max).
Usage: gh_discover.py OUT.jsonl RAWDIR  (processes all *.json.gz in RAWDIR). Deterministic; no model."""
import sys, os, gzip, json, re, glob, collections
OUT, RAW = sys.argv[1], sys.argv[2]
CLOSE = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s*:?\s+(?:([\w.\-]+/[\w.\-]+))?#(\d+)\b", re.I)
BOTS = {"dependabot", "renovate", "greenkeeper", "snyk-bot", "codecov", "github-actions", "travis-ci", "coveralls", "imgbot", "allcontributors", "stale", "pyup-bot", "mergify", "whitesource-bolt-for-github", "sonarcloud", "netlify", "vercel", "codecov-io", "houndci-bot", "dependabot-preview"}
def is_bot(u):
    if not u: return True
    lg = (u.get("login") or "").lower()
    return u.get("type") == "Bot" or lg.endswith("[bot]") or lg.endswith("-bot") or lg in BOTS
st = collections.Counter()
with open(OUT, "w") as fo:
    for p in sorted(glob.glob(RAW + "/" + (sys.argv[3] if len(sys.argv) > 3 else "*.json.gz"))):
        with gzip.open(p, "rt", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if '"PullRequestEvent"' not in line: continue
                try: e = json.loads(line)
                except Exception: continue
                if e.get("type") != "PullRequestEvent": continue
                st["pr_events"] += 1
                pl = e["payload"]; pr = pl.get("pull_request") or {}
                if pl.get("action") != "closed" or not pr.get("merged"): continue
                st["merged"] += 1
                if is_bot(pr.get("user")) or is_bot(e.get("actor") and {"login": e["actor"].get("login"), "type": None}): st["bot"] += 1; continue
                repo = e["repo"]["name"]
                txt = (pr.get("title") or "") + "\n" + (pr.get("body") or "")
                iss = sorted({int(n) for r, n in CLOSE.findall(txt) if (not r) or r.lower() == repo.lower()})
                if not iss: st["no_link"] += 1; continue
                if (pr.get("changed_files") or 0) > 50 or (pr.get("additions") or 0) + (pr.get("deletions") or 0) > 5000: st["too_big"] += 1; continue
                st["candidates"] += 1
                fo.write(json.dumps(dict(repo=repo, pr=pr["number"], issues=iss[:3], merged_at=pr["merged_at"], content_date_max=pr["merged_at"], head_sha=(pr.get("head") or {}).get("sha"), file=os.path.basename(p))) + "\n")
print(dict(st))
