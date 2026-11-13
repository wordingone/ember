# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ESCALATE only on a change (lead 83155): the same known item twice gives one escalation, the repeat goes to a log.

A tick note is split into items on "; ". An item is escalating when it carries the word ESCALATE. Its signature is the item text with digits, times and
whitespace normalised away, so a counter or a clock moving does not make it new, while a different pack name or a different state does.
The state file remembers each escalating signature with the time it was last seen (lead 83299: the old previous-tick-only memory re-escalated an item that
dropped out of one tick and came back): an item seen within SEEN_TTL_H hours is a known repeat (its ESCALATE word is replaced by "known repeat"); a signature
never seen, or not seen for SEEN_TTL_H hours, escalates. A changed state or pack name is a different signature, so it still escalates at once.
The "blocked 3 ticks" suffix follows the same rule on the note head (the part before " | ").
"""
import json, os, re, time

SEEN_TTL_H = 24
_NUM = re.compile(r"\d+")
_WS = re.compile(r"\s+")


def sig(item):
    return _WS.sub(" ", _NUM.sub("#", item.lower())).strip()


def _load(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
        seen = d.get("seen")
        if not isinstance(seen, dict): seen = {i: d.get("ts", "") for i in d.get("items", [])}      # old state file: last tick's items
        return seen, d.get("head")
    except Exception:
        return {}, None


def _fresh(ts, now):
    try: return now - time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")) < SEEN_TTL_H * 3600
    except Exception: return False


def apply(note, blocked, state_path, log_path):
    """Return (note_out, show_blocked_suffix). Writes the state file and appends the repeats to the log."""
    prev_seen, prev_head = _load(state_path)
    now = time.time(); stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    prev_items = {k for k, v in prev_seen.items() if _fresh(v, now)}
    items = note.split("; ")
    out, cur, repeats = [], set(), []
    for it in items:
        if "ESCALATE" not in it:
            out.append(it); continue
        s = sig(it); cur.add(s)
        if s in prev_items:
            repeats.append(it); out.append(it.replace("ESCALATE", "known repeat"))
        else:
            out.append(it)
    head = sig(note.split(" | ")[0]) if blocked >= 3 else None
    show_blocked = blocked >= 3 and head != prev_head
    if blocked >= 3 and not show_blocked: repeats.append("blocked 3 ticks: " + note.split(" | ")[0][:200])
    try:
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        tmp = state_path + ".tmp"
        new_seen = {k: v for k, v in prev_seen.items() if _fresh(v, now)}; new_seen.update({k: stamp for k in cur})
        json.dump({"items": sorted(cur), "seen": new_seen, "head": head, "ts": stamp}, open(tmp, "w", encoding="utf-8")); os.replace(tmp, state_path)
        if repeats:
            with open(log_path, "a", encoding="utf-8") as f: f.write(json.dumps(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S%z"), repeats=repeats)) + "\n")
    except Exception:
        pass
    return "; ".join(out), show_blocked
