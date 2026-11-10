# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Assemble issue->PR->commits->review->CI chain docs for candidates via READ-ONLY gh api calls (<=~3600 req/h).
Usage: gh_assemble.py CANDS.jsonl OUT.jsonl.zst [TARGET_CHAINS] [STATS.json]
Rules: repo SPDX in MIT/Apache-2.0/BSD-2/BSD-3; every API-sourced text item must have updated_at <= WALL (no post-wall edits);
bots removed; any element after WALL -> chain dropped; PII regex mask; usernames -> username_i. No model anywhere."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import M_ROOT
import sys, os, json, re, time, subprocess, collections
from tokenizers import Tokenizer
CANDS, OUT = sys.argv[1], sys.argv[2]
TARGET = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
STATS = sys.argv[4] if len(sys.argv) > 4 else OUT + ".stats.json"
WALL = "2022-10-31T23:59:59Z"
OK_LIC = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"}
tk = Tokenizer.from_file((M_ROOT + "/custody-tokenizer-2c557/tokenizer-2c557.json"))
BOTS = {"dependabot", "renovate", "greenkeeper", "snyk-bot", "codecov", "github-actions", "travis-ci", "coveralls", "imgbot", "allcontributors", "stale", "pyup-bot", "mergify", "whitesource-bolt-for-github", "sonarcloud", "netlify", "vercel", "codecov-io", "houndci-bot", "dependabot-preview"}
def is_bot(u):
    if not u: return True
    lg = (u.get("login") or "").lower()
    return u.get("type") == "Bot" or lg.endswith("[bot]") or lg.endswith("-bot") or lg in BOTS
EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+"); IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
KEY = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9\-]{10,})\b")
def mask(t): return KEY.sub("<KEY>", IP.sub("<IP>", EMAIL.sub("<EMAIL>", t or "")))
calls = [0]; t_last = [0.0]
def gh(path, accept=None, paginate=False):
    dt = time.time() - t_last[0]
    if dt < 1.0: time.sleep(1.0 - dt)
    t_last[0] = time.time(); calls[0] += 1
    cmd = ["gh", "api"] + (["-H", "Accept: " + accept] if accept else []) + (["--paginate", "--jq", ".[]"] if paginate else []) + [path]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if r.returncode != 0: return None
    if accept: return r.stdout
    out = r.stdout
    try:
        if paginate: return [json.loads(l) for l in out.splitlines() if l.strip()]
        return json.loads(out)
    except Exception: return None
lic_cache = {}
def lic(repo):
    if repo not in lic_cache:
        d = gh(f"repos/{repo}")
        lic_cache[repo] = ((d or {}).get("license") or {}).get("spdx_id") if d else None
    return lic_cache[repo]
class Names:
    def __init__(s): s.m = {}
    def __call__(s, login):
        if login not in s.m: s.m[login] = f"username_{len(s.m)}"
        return s.m[login]
def clean_ok(items):
    return all((x.get("updated_at") or x.get("created_at") or "") <= WALL for x in items)
def chain(c, st):
    repo, prn, issues = c["repo"], c["pr"], c["issues"]
    L = lic(repo)
    if L not in OK_LIC: st["drop_license"] += 1; return None
    pr = gh(f"repos/{repo}/pulls/{prn}")
    if not pr or (pr.get("updated_at") or "z") > WALL: st["drop_pr_updated_post_wall"] += 1; return None
    if is_bot(pr.get("user")): st["drop_bot_pr"] += 1; return None
    iss = None
    for n in issues:
        d = gh(f"repos/{repo}/issues/{n}")
        if d and "pull_request" not in d and not is_bot(d.get("user")) and (d.get("updated_at") or "z") <= WALL: iss = d; break
    if not iss: st["drop_no_valid_issue"] += 1; return None
    icom = gh(f"repos/{repo}/issues/{iss['number']}/comments?per_page=100", paginate=True) or []
    pcom = gh(f"repos/{repo}/issues/{prn}/comments?per_page=100", paginate=True) or []
    rcom = gh(f"repos/{repo}/pulls/{prn}/comments?per_page=100", paginate=True) or []
    revs = gh(f"repos/{repo}/pulls/{prn}/reviews?per_page=100", paginate=True) or []
    cms = gh(f"repos/{repo}/pulls/{prn}/commits?per_page=100", paginate=True) or []
    diff = gh(f"repos/{repo}/pulls/{prn}", accept="application/vnd.github.diff") or ""
    sha = (pr.get("head") or {}).get("sha")
    cr = gh(f"repos/{repo}/commits/{sha}/check-runs?per_page=100") if sha else None
    sts = gh(f"repos/{repo}/commits/{sha}/status") if sha else None
    merged = pr.get("merged_at") or ""
    icom = [x for x in icom if not is_bot(x.get("user")) and x["created_at"] <= merged]
    pcom = [x for x in pcom if not is_bot(x.get("user")) and x["created_at"] <= merged]
    rcom = [x for x in rcom if not is_bot(x.get("user")) and x["created_at"] <= merged]
    revs = [x for x in revs if not is_bot(x.get("user")) and (x.get("body") or "").strip() and (x.get("submitted_at") or "") <= merged]
    if not clean_ok(icom + pcom + rcom + [dict(updated_at=r.get("submitted_at")) for r in revs]): st["drop_comment_post_wall"] += 1; return None
    if any((x.get("commit", {}).get("author", {}).get("date") or "z") > WALL for x in cms): st["drop_commit_post_wall"] += 1; return None
    nm = Names(); ev = []
    ev.append((iss["created_at"], f"=== ISSUE #{iss['number']}  opened {iss['created_at']} by {nm(iss['user']['login'])}\nTITLE: {mask(iss['title'])}\n{mask(iss.get('body'))}"))
    for x in icom: ev.append((x["created_at"], f"--- COMMENT {x['created_at']} {nm(x['user']['login'])}\n{mask(x['body'])}"))
    ev.append((pr["created_at"], f"=== PULL REQUEST #{prn}  opened {pr['created_at']} by {nm(pr['user']['login'])}  base={pr['base']['ref']}\nTITLE: {mask(pr['title'])}\n{mask(pr.get('body'))}"))
    for x in cms:
        d = x["commit"]["author"]["date"]; lg = (x.get("author") or {}).get("login") or "unknown"
        ev.append((d, f"--- COMMIT {x['sha'][:7]} {d} {nm(lg)}\n{mask(x['commit']['message'])}"))
    for x in pcom: ev.append((x["created_at"], f"--- PR COMMENT {x['created_at']} {nm(x['user']['login'])}\n{mask(x['body'])}"))
    for x in rcom: ev.append((x["created_at"], f"--- REVIEW COMMENT {x['created_at']} {nm(x['user']['login'])}  path={x.get('path')} line={x.get('line') or x.get('original_line')}\n{mask(x.get('diff_hunk'))}\n{mask(x['body'])}"))
    for x in revs: ev.append((x["submitted_at"], f"--- REVIEW {x['submitted_at']} {nm(x['user']['login'])} state={x['state']}\n{mask(x['body'])}"))
    ci = []
    for r in (cr or {}).get("check_runs", []) or []:
        ci.append(f"--- CI check-run \"{r.get('name')}\" status={r.get('status')} conclusion={r.get('conclusion')} head={(sha or '')[:7]} completed={r.get('completed_at')}")
    for s in (sts or {}).get("statuses", []) or []:
        ci.append(f"--- CI status \"{s.get('context')}\" state={s.get('state')} head={(sha or '')[:7]} updated={s.get('updated_at')}")
    ev.sort(key=lambda t: t[0])
    dtxt = mask(diff)
    if len(dtxt) > 200000: dtxt = dtxt[:200000] + f"\n[diff truncated: {len(diff) - 200000} bytes]"
    body = [e[1] for e in ev]
    body.append("--- UNIFIED DIFF (PR head vs base)\n" + dtxt)
    body += ci
    body.append(f"--- PULL REQUEST #{prn} merged {merged} by {nm((pr.get('merged_by') or pr['user'])['login'])}")
    if iss.get("closed_at"): body.append(f"--- ISSUE #{iss['number']} closed {iss['closed_at']}")
    head = f"REPO {repo}  LICENSE_NOW {L}  LICENSE_CAVEAT license-now-not-license-at-item-date  PRIVATE-TWIN-ONLY\n"
    text = head + "\n".join(body)
    return dict(id=f"gh-{repo.replace('/', '_')}-pr{prn}", repo=repo, license_now=L, pr=prn, issue=iss["number"], merged_at=merged, created_at=iss["created_at"],
                n_events=len(ev), n_ci=len(ci), text=text, tokens=len(tk.encode(text).ids), origin="born-digital (GitHub, GH Archive discovery + API assembly)")
def main():
    cands = [json.loads(l) for l in open(CANDS)]
    st = collections.Counter(); kept = 0; toks = 0; t0 = time.time()
    seen = set(); done_p = OUT + ".tried"
    if os.path.exists(done_p):
        for l in open(done_p):
            r, n = l.strip().rsplit("#", 1); seen.add((r, int(n)))
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            kept += 1; toks += json.loads(l)["tokens"]
    st["resumed_tried"] = len(seen)
    with open(OUT, "a", encoding="utf-8") as fo, open(done_p, "a") as ft:
        for c in cands:
            if kept >= TARGET: break
            key = (c["repo"], c["pr"])
            if key in seen: continue
            seen.add(key); st["tried"] += 1
            try: d = chain(c, st)
            except Exception as e: st["error"] += 1; continue
            ft.write(f"{key[0]}#{key[1]}" + chr(10)); ft.flush()
            if d:
                kept += 1; toks += d["tokens"]; fo.write(json.dumps(d, ensure_ascii=False) + chr(10)); fo.flush()
            if st["tried"] % 25 == 0:
                st.update(kept=kept, tokens=toks, api_calls=calls[0], secs=round(time.time() - t0)); json.dump(dict(st), open(STATS, "w")); print(dict(st), flush=True)
    st.update(kept=kept, tokens=toks, api_calls=calls[0], secs=round(time.time() - t0)); json.dump(dict(st), open(STATS, "w")); print("FINAL", dict(st), flush=True)
main()
