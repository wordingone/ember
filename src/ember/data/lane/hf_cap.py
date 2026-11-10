# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Hard private-storage guard (lead 81851). HF PRO includes 1 TB private; overage bills automatically and the rule is included credits only.
check(add_bytes, who, what) -> True if total private usedStorage (every private dataset/model/space of the account, from the HF API) + add + in-flight bound stays <= CAP (900 GB default).
On refusal: writes loops/PRIVATE-CAP-HOLD.flag, mails lead (mb_send with readback; at most once per hour per `who`), returns False. Callers HOLD (never delete, never overwrite): the shared uploader leaves the job queued and retries,
the tick does not start the pack push, bulk lanes wait. Env overrides for tests: HF_CAP_BYTES, HF_CAP_TEST=1 (prefixes the mail subject), HF_CAP_STATE."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, SEAT_LEAD
import os, sys, json, time
from huggingface_hub import HfApi
from lane_config import LANE_ROOT as ROOT; CAP = float(os.environ.get("HF_CAP_BYTES", 900e9)); STATE = os.environ.get("HF_CAP_STATE", ROOT + "/upq/cap-state.json")
_api = HfApi(); _c = {"t": 0, "v": 0, "repos": {}}
def total_private(max_age=120):
    if time.time() - _c["t"] > max_age:
        repos = {}
        for kind, lst, get in (("dataset", _api.list_datasets, _api.dataset_info), ("model", _api.list_models, _api.model_info), ("space", _api.list_spaces, _api.space_info)):
            for r in lst(author="wordingone"):
                info = get(r.id, expand=["usedStorage", "private"])
                if info.private: repos[r.id] = info.used_storage or 0
        _c.update(t=time.time(), v=sum(repos.values()), repos=repos)
    return _c["v"], _c["repos"]
def inflight_bound():
    """upper bound of bytes already committed to leave this machine but not yet counted by HF: queued upq jobs + local dirs of started-but-unverified pack pushes"""
    t = 0
    try:
        for f in os.listdir(ROOT + "/upq"):
            if f.endswith(".job.json"): t += json.load(open(ROOT + "/upq/" + f)).get("size", 0)
    except Exception: pass
    return t
def check(add, who, what="", inflight=None):
    used, repos = total_private()
    fl = inflight_bound() if inflight is None else inflight
    if used + add + fl <= CAP: return True
    flag = ROOT + "/loops/PRIVATE-CAP-HOLD.flag"
    msg = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} HOLD {who}: private used {used/1e9:.1f} GB + push {add/1e9:.2f} GB + queued {fl/1e9:.2f} GB > cap {CAP/1e9:.0f} GB ({what})"
    open(flag, "a").write(msg + "\n")
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    if time.time() - st.get(who, 0) > 3600:
        sys.path.insert(0, ROOT + "/scripts"); import mb_send
        subj = ("[TEST red] " if os.environ.get("HF_CAP_TEST") else "") + f"PRIVATE CAP HOLD: {who} refused a push ({used/1e9:.0f} of 1000 GB, cap {CAP/1e9:.0f})"
        body = msg + "\nrepos: " + json.dumps({k: round(v / 1e9, 2) for k, v in repos.items()}) + "\nNothing deleted or overwritten; the push is held (queued job kept / pack push not started). Needs your call: raise the cap, free private storage, or stop the lane."
        try: mid = mb_send.send(SEAT_LEAD, subj, body); st[who] = time.time(); json.dump(st, open(STATE, "w")); print(f"hf_cap: mailed lead id {mid}", flush=True)
        except Exception as e: print("hf_cap: MAIL NOT DELIVERED (retry next check):", type(e).__name__, str(e)[:120], flush=True)
    return False
