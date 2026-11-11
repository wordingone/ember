# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ESCALATE only on a change (lead 83155): the same known item twice gives one escalation, the repeat goes to a log.

A tick note is split into items on "; ". An item is escalating when it carries the word ESCALATE. Its signature is the item text with digits, times and
whitespace normalised away, so a counter or a clock moving does not make it new, while a different pack name or a different state does.
The state file holds the signatures of the PREVIOUS tick's escalating items: an item seen last tick is a known repeat (its ESCALATE word is replaced by
"known repeat"), an item absent last tick is new again (a state change, or it went away and came back) and escalates.
The "blocked 3 ticks" suffix follows the same rule on the note head (the part before " | ").
"""
import json, os, re, time

_NUM = re.compile(r"\d+")
_WS = re.compile(r"\s+")


def sig(item):
    return _WS.sub(" ", _NUM.sub("#", item.lower())).strip()


def _load(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
        return set(d.get("items", [])), d.get("head")
    except Exception:
        return set(), None


def apply(note, blocked, state_path, log_path):
    """Return (note_out, show_blocked_suffix). Writes the state file and appends the repeats to the log."""
    prev_items, prev_head = _load(state_path)
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
        json.dump({"items": sorted(cur), "head": head, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}, open(tmp, "w", encoding="utf-8")); os.replace(tmp, state_path)
        if repeats:
            with open(log_path, "a", encoding="utf-8") as f: f.write(json.dumps(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S%z"), repeats=repeats)) + "\n")
    except Exception:
        pass
    return "; ".join(out), show_blocked
