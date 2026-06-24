#!/usr/bin/env python3
import json
import sys


heldout_path, out_path = sys.argv[1], sys.argv[2]
with open(heldout_path, encoding="utf-8") as f, open(out_path, "w", encoding="utf-8", newline="\n") as out:
    for line in f:
        row = json.loads(line)
        text = row["text"].lower()
        prediction = "fear" if ("afraid" in text or "scared" in text) else "anger"
        out.write(json.dumps({"case_id": row["case_id"], "prediction": prediction}, sort_keys=True) + "\n")
