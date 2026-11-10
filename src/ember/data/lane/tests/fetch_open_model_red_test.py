# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green test for fetch_open_model.classify: weights/config/tokenizer/LICENSE/README are fetched; pickle, bin, py, gguf, nested files and unknown extensions are refused; .gitattributes skipped.
Run: python scripts/tests/fetch_open_model_red_test.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fetch_open_model as F
ok = True


def chk(n, c):
    global ok
    ok = ok and bool(c); print(("PASS " if c else "FAIL ") + n)


for fn in ["model.safetensors-00001-of-00001.safetensors", "model.safetensors.index.json", "config.json", "tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt", "LICENSE", "README.md", "preprocessor_config.json"]:
    chk("GREEN fetch " + fn, F.classify(fn) == "fetch")
chk("GREEN .gitattributes skipped", F.classify(".gitattributes") == "skip")
for fn in ["pytorch_model.bin", "model.pt", "weights.pth", "data.pkl", "modeling_qwen.py", "model.gguf", "model.ckpt", "x.safetensors.py", "sub/model.safetensors", "install.sh", "weights.npz", "mystery.dat", "tokenizer.model"]:
    chk("RED refuse " + fn, F.classify(fn) == "refuse")
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
