#!/usr/bin/env python3
import json
import sys


FEAR_WORDS = (
    "afraid",
    "scared",
    "suspicious",
    "bitten",
    "dog",
    "distraught",
    "insecure",
    "shaky",
    "overwhelmed",
)
JOY_WORDS = (
    "joy",
    "living",
    "energy",
    "thankful",
    "grateful",
    "better",
    "happpy",
    "sincere",
    "content",
)


heldout_path, out_path = sys.argv[1], sys.argv[2]
with open(heldout_path, encoding="utf-8") as f, open(out_path, "w", encoding="utf-8", newline="\n") as out:
    for line in f:
        row = json.loads(line)
        text = row["text"].lower()
        if any(word in text for word in FEAR_WORDS):
            prediction = "fear"
        elif any(word in text for word in JOY_WORDS):
            prediction = "joy"
        else:
            prediction = "anger"
        out.write(json.dumps({"case_id": row["case_id"], "prediction": prediction}, sort_keys=True) + "\n")
