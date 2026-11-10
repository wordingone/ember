# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_TRAIN_REPO, LANE_ROOT
import os, sys, json, time, subprocess, hashlib, shutil
from lane_config import LANE_ROOT as R; Q = R + "/logs/cap-redtest-upq"; shutil.rmtree(Q, ignore_errors=True); os.makedirs(Q)
data = b"x" * 4096; open(Q + "/t1.dat", "wb").write(data)
json.dump(dict(repo=("wordingone/" + HF_TRAIN_REPO), rp="redtest/cap-red-never-uploaded.bin", size=len(data), sha=hashlib.sha256(data).hexdigest(), lane="redtest", meta={}, rcpt=Q + "/rcpt.jsonl"), open(Q + "/t1.job.json", "w"))
env = dict(os.environ, UPQ_DIR=Q, HF_CAP_BYTES=str(100e9), HF_CAP_TEST="1", HF_CAP_STATE=Q + "/cap-state.json")
p = subprocess.Popen([sys.executable, R + "/scripts/upload_worker.py"], env=env, stdout=open(R + "/logs/cap-redtest.log", "w"), stderr=subprocess.STDOUT)
time.sleep(75); p.kill(); p.wait()
print(open(R + "/logs/cap-redtest.log").read()); print("job still queued:", os.path.exists(Q + "/t1.job.json"), "dat kept:", os.path.exists(Q + "/t1.dat"), "failed/:", os.listdir(Q + "/failed"), "state:", open(Q + "/cap-state.json").read() if os.path.exists(Q + "/cap-state.json") else None)
print(open(R + "/loops/PRIVATE-CAP-HOLD.flag").read())
