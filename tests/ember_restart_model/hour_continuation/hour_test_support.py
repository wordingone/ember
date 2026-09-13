# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Resolve only this checkout's source and existing model fixtures."""
from pathlib import Path
import sys
root = next(parent for parent in Path(__file__).resolve().parents
            if (parent/'src/ember/model/ember_v0_decoder.py').is_file())
source = root/'src/ember/infrastructure/tools/ember-restart-3b'
sys.path[:0] = [str(source), str(root/'src'), str(root/'tests')]
