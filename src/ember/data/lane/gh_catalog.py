# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Stage 1 catalog of MIT-licensed GitHub repos for training (lead 82422). CATALOG ONLY: GitHub GraphQL metadata, no clone, no download of repo content.
Usage: python gh_catalog.py crawl [--max-seconds N]   resumable; appends to catalog/raw/results.jsonl, progress in catalog/state.json
       python gh_catalog.py build                     assemble catalog/gh-mit-candidates.jsonl, gh-residual.jsonl, gh-catalog-summary.json
Seeds live in catalog/gh-seeds.json (topics per domain, phrase queries, orgs, users); edit the file to grow it and re-run crawl (finished seeds are skipped).
Licence: the repo-level SPDX id as the API reports it. Only "MIT" is a candidate; null / NOASSERTION / OTHER go to the residual; every other id is only counted.
A repo marked MIT can vendor code under other licences: the per-file check is a Stage 2 gate before any byte is admitted."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time, subprocess, re, datetime, collections, glob
from lane_config import LANE_ROOT as BASE; CAT = BASE + "/catalog"; RAW = CAT + "/raw"; SEEDS = CAT + "/gh-seeds.json"; STATE = CAT + "/state.json"; RES = RAW + "/results.jsonl"; LOG = BASE + "/logs/gh-catalog.log"
os.makedirs(RAW, exist_ok=True)
FRAG = """fragment R on Repository { nameWithOwner url description isFork isArchived isTemplate stargazerCount forkCount pushedAt createdAt diskUsage
  licenseInfo { spdxId } primaryLanguage { name } repositoryTopics(first: 20) { nodes { topic { name } } }
  defaultBranchRef { name target { ... on Commit { oid committedDate } } }
  root: object(expression: "HEAD:") { ... on Tree { entries { name type } } }
  wf: object(expression: "HEAD:.github/workflows") { ... on Tree { entries { name } } } }"""
Q_SEARCH = FRAG + """ query($q: String!, $after: String) { rateLimit { cost remaining resetAt }
  search(query: $q, type: REPOSITORY, first: 50, after: $after) { repositoryCount pageInfo { hasNextPage endCursor } nodes { ...R } } }"""
Q_OWNER = FRAG + """ query($login: String!, $after: String) { rateLimit { cost remaining resetAt }
  repositoryOwner(login: $login) { login repositories(first: 50, after: $after, privacy: PUBLIC, isFork: false, orderBy: {field: STARGAZERS, direction: DESC}) { totalCount pageInfo { hasNextPage endCursor } nodes { ...R } } } }"""


def log(m):
    s = time.strftime("%Y-%m-%d %H:%M:%S") + " " + m
    print(s, flush=True)
    open(LOG, "a", encoding="utf-8").write(s + "\n")


def gql(query, **vars):
    """-> (data, rate) ; retries on secondary-limit / 5xx / network errors; sleeps to the reset time when the primary budget is nearly gone"""
    args = ["gh", "api", "graphql", "-f", "query=" + query]
    for k, v in vars.items():
        if v is not None: args += ["-f", f"{k}={v}"]
    for attempt in range(25):
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = p.stdout.strip()
        try: j = json.loads(out) if out else {}
        except Exception: j = {}
        err = (p.stderr or "") + " " + json.dumps(j.get("errors", ""))
        if p.returncode == 0 and "data" in j and j["data"] is not None:
            rl = j["data"].get("rateLimit") or {}
            if rl and rl.get("remaining", 9999) < 60:
                t = max(5, (datetime.datetime.fromisoformat(rl["resetAt"].replace("Z", "+00:00")) - datetime.datetime.now(datetime.timezone.utc)).total_seconds() + 5)
                log(f"primary budget low ({rl['remaining']}); sleeping {int(t)}s"); time.sleep(t)
            return j["data"], rl
        if "NOT_FOUND" in err or "Could not resolve" in err: return None, None
        wait = 70 if ("secondary" in err.lower() or "abuse" in err.lower() or "rate limit" in err.lower()) else min(90, 10 * (attempt + 1))
        log(f"gql retry {attempt + 1} wait {wait}s: {err[:160]}"); time.sleep(wait)
    raise RuntimeError("gql failed after retries")


def slim(n):
    if not n or not n.get("nameWithOwner"): return None
    tree = ((n.get("root") or {}).get("entries")) or []
    wf = ((n.get("wf") or {}).get("entries")) or []
    br = n.get("defaultBranchRef") or {}; tg = br.get("target") or {}
    return {"full_name": n["nameWithOwner"], "url": n["url"], "description": (n.get("description") or "")[:240], "licence": (n.get("licenseInfo") or {}).get("spdxId"),
            "sha": tg.get("oid"), "branch": br.get("name"), "committed": tg.get("committedDate"), "stars": n["stargazerCount"], "forks": n["forkCount"], "pushed_at": n["pushedAt"],
            "created_at": n["createdAt"], "lang": (n.get("primaryLanguage") or {}).get("name"), "size_kb": n["diskUsage"], "fork": n["isFork"], "archived": n["isArchived"],
            "template": n["isTemplate"], "topics": [t["topic"]["name"] for t in (n.get("repositoryTopics") or {}).get("nodes", [])],
            "root": sorted(e["name"] for e in tree), "root_types": {e["name"]: e["type"] for e in tree}, "workflows": sorted(e["name"] for e in wf)}


def emit(seed, nodes):
    n = 0
    with open(RES, "a", encoding="utf-8") as f:
        for x in nodes:
            r = slim(x)
            if r: f.write(json.dumps({"seed": seed, "repo": r}) + "\n"); n += 1
    return n


def search_range(seed, base, lo, hi, order, depth=0):
    """crawl `base` restricted to stars lo..hi (hi None = open); splits the range while GitHub reports more than 1000 results (its hard cap per query)"""
    rng = f"stars:>={lo}" if hi is None else f"stars:{lo}..{hi}"
    q = f"{base} {rng} {order}"
    data, _ = gql(Q_SEARCH, q=q); time.sleep(1.1)
    s = data["search"]; cnt = s["repositoryCount"]
    if cnt > 1000 and (hi is None or hi > lo):
        if hi is None: top = max(x["stargazerCount"] for x in s["nodes"]) if s["nodes"] else lo * 4; top = max(top, lo * 2)
        else: top = hi
        mid = (lo + top) // 2 if hi is not None else max(lo + 1, int((lo * top) ** 0.5))
        if mid <= lo: mid = lo + 1
        log(f"  split {q[:100]} count {cnt} at {mid}")
        a = search_range(seed, base, mid, hi, order, depth + 1)
        b = search_range(seed, base, lo, mid - 1, order, depth + 1)
        return a + b
    got = emit(seed, s["nodes"]); after = s["pageInfo"]["endCursor"]; more = s["pageInfo"]["hasNextPage"]
    while more and got < 1000:
        data, _ = gql(Q_SEARCH, q=q, after=after); time.sleep(1.1)
        s = data["search"]; got += emit(seed, s["nodes"]); more = s["pageInfo"]["hasNextPage"]; after = s["pageInfo"]["endCursor"]
    if cnt > 1000: log(f"  CAPPED (single star value or equal ranges, {cnt} found, 1000 kept): {q[:120]}")
    return got


def owner_crawl(seed, login, min_stars, max_pages):
    n = 0; after = None
    for _ in range(max_pages):
        data, _ = gql(Q_OWNER, login=login, after=after); time.sleep(1.1)
        if not data or not data.get("repositoryOwner"): log(f"  seed-not-found {login}"); return -1
        rp = data["repositoryOwner"]["repositories"]; nodes = rp["nodes"]
        keep = [x for x in nodes if x["stargazerCount"] >= min_stars]
        n += emit(seed, keep)
        if len(keep) < len(nodes) or not rp["pageInfo"]["hasNextPage"]: break
        after = rp["pageInfo"]["endCursor"]
    return n


def crawl(max_seconds):
    sd = json.load(open(SEEDS, encoding="utf-8"))
    st = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {"done": {}}
    t0 = time.time(); fl = sd["star_floor"]; rfl = sd["recent_floor_stars"]; since = (datetime.date.today() - datetime.timedelta(days=sd["recent_days"])).isoformat()
    jobs = []
    for dom, tops in sd["topics"].items():
        for t in tops:
            jobs.append((f"topic:{t}", dom, lambda s, t=t: search_range(s, f"topic:{t} license:mit fork:false archived:false", fl, None, "sort:stars-desc")))
            jobs.append((f"topic-recent:{t}", dom, lambda s, t=t: search_range(s, f"topic:{t} license:mit fork:false archived:false pushed:>={since}", rfl, fl - 1, "sort:updated-desc")))
    for dom, phrases in sd["phrases"].items():
        for ph in phrases:
            jobs.append((f"phrase:{ph}", dom, lambda s, ph=ph: search_range(s, f'"{ph}" in:name,description,topics license:mit fork:false archived:false', fl, None, "sort:stars-desc")))
    for o in sd["orgs"]: jobs.append((f"org:{o}", None, lambda s, o=o: owner_crawl(s, o, sd["org_min_stars"], sd["org_max_pages"])))
    for u in sd["users"]: jobs.append((f"user:{u}", None, lambda s, u=u: owner_crawl(s, u, sd["org_min_stars"], sd["org_max_pages"])))
    seen = set(); jobs = [j for j in jobs if not (j[0] in seen or seen.add(j[0]))]
    todo = [j for j in jobs if j[0] not in st["done"]]
    log(f"crawl start: {len(jobs)} seeds, {len(todo)} to do")
    for seed, dom, fn in todo:
        if max_seconds and time.time() - t0 > max_seconds: log("max-seconds reached; stopping (resumable)"); break
        n = fn(seed); st["done"][seed] = {"n": n, "domain_seed": dom, "ts": int(time.time())}
        json.dump(st, open(STATE, "w", encoding="utf-8"), indent=0)
        log(f"seed {seed}: {n}")
    log("crawl pass finished: " + str(len([j for j in jobs if j[0] in st['done']])) + "/" + str(len(jobs)) + " seeds done")


DOM_RULES = collections.OrderedDict([
    ("agents", r"agent|agentic|autogen|mcp\b|model[- ]context[- ]protocol|tool[- ]use|function[- ]call|langgraph|crewai|swarm|autonomous"),
    ("llm", r"\bllms?\b|large[- ]language|language[- ]model|\bgpt|llama|transformer|\brag\b|retrieval[- ]augmented|chatbot|prompt|fine-?tun|rlhf|instruction[- ]tun|tokeniz|\bnlp\b|text[- ]generation|qwen|mistral|gemma|\blora\b"),
    ("vision", r"computer[- ]vision|\bvision\b|image|video|object[- ]detection|segmentation|\bocr\b|diffusion|nerf|gaussian[- ]splat|opencv|yolo|point[- ]cloud|\bslam\b|depth[- ]estimation|pose[- ]estimation|diffusers|\bvit\b|\bclip\b"),
    ("training-infra", r"distributed|mlops|cuda|triton|inference|serving|quantiz|deepspeed|flash[- ]attention|kernel|compiler|\bonnx\b|tensorrt|\bgpu|megatron|\bfsdp|parallelism|model[- ]compression|pruning"),
    ("eval", r"benchmark|evaluation|\beval\b|leaderboard|harness"),
    ("data-tooling", r"dataset|data[- ]pipeline|data[- ]processing|dedup|annotation|labeling|\betl\b|data[- ]loader|data[- ]engineering|web[- ]scrap|crawler"),
    ("ml-framework", r"machine[- ]learning|deep[- ]learning|pytorch|tensorflow|\bjax\b|keras|scikit|sklearn|neural[- ]net|autograd|xgboost|lightgbm|gradient[- ]boost|reinforcement[- ]learning|automl|\bml\b"),
])
PRIORITY = ["agents", "llm", "vision", "training-infra", "eval", "data-tooling", "ml-framework"]
AWESOME = re.compile(r"awesome|cheat-?sheet|interview|roadmap|curated|^list|-list$|dump|leak|papers?-with|collection of|resources?$|tutorial-?s?$|course|bootcamp|notes$", re.I)
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "testing", "unittests", "unit_tests", "t"}
TEST_FILES = {"pytest.ini", "tox.ini", "conftest.py", "jest.config.js", "jest.config.ts", "vitest.config.ts", "noxfile.py", "phpunit.xml", "karma.conf.js"}
CI_MARKS = {".travis.yml", ".circleci", "azure-pipelines.yml", ".gitlab-ci.yml", "Jenkinsfile", ".buildkite", "appveyor.yml", ".drone.yml", "cloudbuild.yaml"}


def classify(r, seed_doms):
    txt = {"t": " ".join(r["topics"]).lower(), "d": (r["description"] + " " + r["full_name"].split("/")[1]).lower()}
    sc = {}
    for dom, rx in DOM_RULES.items():
        a = len(set(re.findall(rx, txt["t"]))); b = len(set(re.findall(rx, txt["d"])))
        if a or b: sc[dom] = 2 * a + b
    if sc:
        best = max(sc.values()); tied = [d for d in PRIORITY if sc.get(d) == best]
        pick = next((d for d in tied if d in seed_doms), tied[0])
        return pick, "keyword", sorted(sc, key=lambda d: -sc[d])
    if seed_doms:
        return sorted(seed_doms)[0], "seed", sorted(seed_doms)
    return "unclassified", "none", []


def held_repos():
    p = CAT + "/held-github-repos.json"
    return set(json.load(open(p, encoding="utf-8"))) if os.path.exists(p) else None


def build():
    sd = json.load(open(SEEDS, encoding="utf-8")); st = json.load(open(STATE, encoding="utf-8")); dom_of = {k: v["domain_seed"] for k, v in st["done"].items()}
    rows = {}
    for l in open(RES, encoding="utf-8"):
        d = json.loads(l); r = d["repo"]; k = r["full_name"].lower()
        e = rows.setdefault(k, {"repo": r, "seeds": []})
        if d["seed"] not in e["seeds"]: e["seeds"].append(d["seed"])
    held = held_repos(); cutoff = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    cand, resid, lic_count = [], [], collections.Counter()
    for k, e in rows.items():
        r = e["repo"]; lic_count[str(r["licence"])] += 1
        if r["licence"] != "MIT":
            if r["licence"] in (None, "NOASSERTION", "OTHER"): resid.append({"full_name": r["full_name"], "url": r["url"], "licence": r["licence"], "stars": r["stars"], "reason": "licence_unclassified", "seeds": e["seeds"]})
            continue
        seed_doms = {dom_of.get(s) for s in e["seeds"] if dom_of.get(s)}
        dom, basis, allp = classify(r, seed_doms)
        root = set(r["root"])
        has_tests = bool(root & TEST_DIRS or root & TEST_FILES)
        has_ci = bool(r["workflows"] or root & CI_MARKS)
        cand.append({"full_name": r["full_name"], "url": r["url"], "licence_spdx": r["licence"], "default_branch": r["branch"], "commit_sha": r["sha"], "stars": r["stars"], "pushed_at": r["pushed_at"],
                     "language": r["lang"], "size_kb": r["size_kb"], "domain": dom, "domain_basis": basis, "domain_candidates": allp, "seed": e["seeds"],
                     "signals": {"stars": r["stars"], "has_tests_root": has_tests, "has_ci": has_ci, "last_commit": r["committed"], "recent_commit_365d": bool(r["committed"] and r["committed"][:10] >= cutoff),
                                 "not_fork": not r["fork"], "not_archived": not r["archived"], "not_template": not r["template"],
                                 "awesome_or_dump_flag": bool(AWESOME.search(r["full_name"].split("/")[1]) or any(AWESOME.search(t) for t in r["topics"]) or (r["lang"] in (None, "Markdown") and r["size_kb"] < 5000))},
                     "topics": r["topics"], "description": r["description"], "overlap_held_issues_prs": (k in held) if held is not None else None})
    cand.sort(key=lambda x: -x["stars"])
    with open(CAT + "/gh-mit-candidates.jsonl", "w", encoding="utf-8") as f:
        for c in cand: f.write(json.dumps(c) + "\n")
    with open(CAT + "/gh-residual.jsonl", "w", encoding="utf-8") as f:
        for c in resid: f.write(json.dumps(c) + "\n")
    bydom = collections.defaultdict(lambda: {"repos": 0, "size_kb": 0, "clean_signal_repos": 0, "clean_signal_kb": 0})
    for c in cand:
        b = bydom[c["domain"]]; b["repos"] += 1; b["size_kb"] += c["size_kb"] or 0
        s = c["signals"]
        if s["has_tests_root"] and s["has_ci"] and s["recent_commit_365d"] and s["not_fork"] and s["not_archived"] and not s["awesome_or_dump_flag"]: b["clean_signal_repos"] += 1; b["clean_signal_kb"] += c["size_kb"] or 0
    summ = {"built": time.strftime("%Y-%m-%d %H:%M:%S"), "candidates": len(cand), "seeds_done": len(st["done"]), "unique_repos_seen": len(rows), "licence_counts_seen": dict(lic_count.most_common(25)),
            "residual_licence_unclassified": len(resid), "residual_domain_unclassified": sum(1 for c in cand if c["domain"] == "unclassified"),
            "by_domain": {d: {**v, "size_gib_estimate": round(v["size_kb"] / 1048576, 3), "clean_signal_gib_estimate": round(v["clean_signal_kb"] / 1048576, 3)} for d, v in sorted(bydom.items())},
            "total_size_gib_estimate": round(sum(c["size_kb"] or 0 for c in cand) / 1048576, 3), "size_note": "GitHub diskUsage (KB) of the whole repo incl. .git history: an upper bound on source bytes, not a post-filter count",
            "overlap_held_github_archive": (sum(1 for c in cand if c["overlap_held_issues_prs"]) if held is not None else "held-set not built"),
            "overlap_note": "owner/name match against the GitHub issue/PR text we hold (github_archive finals); the Stack-Edu code rows carry no repo identity, so overlap with them cannot be computed"}
    json.dump(summ, open(CAT + "/gh-catalog-summary.json", "w", encoding="utf-8"), indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "crawl":
        ms = int(sys.argv[sys.argv.index("--max-seconds") + 1]) if "--max-seconds" in sys.argv else 0
        crawl(ms)
    elif cmd == "build": build()
    else: print(__doc__)
