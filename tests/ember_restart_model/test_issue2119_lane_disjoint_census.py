"""Lane-disjoint exemption in both resource censuses (#2119 H43, lane isolation). Reds: a lane-pinned 2 GiB python passes;
the same process at 0xFFFF, as a GPU holder, or as a training command is counted; an unreadable affinity is counted."""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str((ROOT / rel).parent))
    spec.loader.exec_module(module)
    return module


launch = load('cia_conformance_launch_lane', 'src/ember/governance/scripts/cia_conformance_launch.py')
runner = load('cia_step_runner_lane', 'src/ember/infrastructure/tools/ember-restart-3b/cia_step_runner.py')

OWNER = {'ProcessId': 2, 'ParentProcessId': 1, 'Name': 'python.exe', 'CommandLine': 'python owner.py', 'PageFileUsage': 10, 'HasExited': False}


def lane(affinity=0xFF0000, command='"python.exe" scripts/imgtext_manifest.py coco'):
    return {'ProcessId': 9, 'ParentProcessId': 5, 'Name': 'python.exe', 'CommandLine': command,
            'PageFileUsage': 2 * 1024 ** 2, 'HasExited': False, 'Affinity': affinity}


def both(rows, gpu):
    out = []
    for call in (lambda: launch.reject_resource_conflicts(rows, 2, gpu), lambda: runner.reject_unowned_model_processes(rows, gpu, 2)):
        try:
            call()
            out.append('pass')
        except ValueError:
            out.append('counted')
    return out


class LaneDisjoint(unittest.TestCase):
    def test_lane_pinned_2gib_python_passes(self):
        self.assertEqual(both([OWNER, lane()], set()), ['pass', 'pass'])

    def test_same_process_on_trainer_ccd_is_counted(self):
        self.assertEqual(both([OWNER, lane(0xFFFF)], set()), ['counted', 'counted'])
        self.assertEqual(both([OWNER, lane(0xFF00FF)], set()), ['counted', 'counted'])

    def test_same_process_as_gpu_holder_is_counted(self):
        self.assertEqual(both([OWNER, lane()], {9}), ['counted', 'counted'])

    def test_training_command_is_counted(self):
        self.assertEqual(both([OWNER, lane(command='"python.exe" train.py --x')], set()), ['counted', 'counted'])

    def test_unreadable_affinity_is_counted(self):
        self.assertEqual(both([OWNER, lane(None)], set()), ['counted', 'counted'])


if __name__ == '__main__':
    unittest.main()
