# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""THE one funnel for every HF write that carries local file content (lead 82104: no exceptions). upload_file / create_commit wrappers refuse (upload_refuse) any local path on the refuse-list BEFORE any network call, then delegate to the HfApi object.
Scripts must call hf_push.upload_file(api, ...) / hf_push.create_commit(api, ...) instead of api.upload_file / api.create_commit; spawned CLIs (`hf upload`) call hf_push.check_path(local) first. scripts/tests/upload_refuse_red_test.py lints the tree for raw calls."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys
pass
import upload_refuse


def check_path(p):
    if isinstance(p, (str, os.PathLike)): upload_refuse.check(os.fspath(p))


def upload_file(api, **kw):
    check_path(kw.get("path_or_fileobj")); return api.upload_file(**kw)


def create_commit(api, **kw):
    for op in kw.get("operations") or []:
        check_path(getattr(op, "path_or_fileobj", None))
    return api.create_commit(**kw)
