# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The learning-rate-only transition after a parent restore (#2119): CPU checks, no training claim.

Required reds (ruling 74088): (a) a constructor-time learning-rate change refuses at identity validation; (b) after the
transition every param-group learning rate reads the target and the Adam step counts equal the parent's; (c) the child
manifest lineage records the transition and re-derives only from the exact learning-rate difference.
"""
import copy
import importlib.util
import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path[:0] = [str(TOOLS), str(ROOT / 'src'), str(ROOT)]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = load(TOOLS / 'cia_step_runner.py', 'lr_transition_runner')
hour = load(TOOLS / 'cia_hour.py', 'lr_transition_hour')
import checkpoint_artifacts as artifacts
import parameter_counter as counter
from ember.model.ember_v0_decoder import CIADecoder

FROM, TO = 0.001, 0.0001
TRANSITION = {'kind': counter.CIA_LR_TRANSITION_KIND, 'from_lr': FROM, 'to_lr': TO}   # the identity declaration
PARENT_SHA = 'a' * 64
APPLY = dict(parent_manifest_sha256=PARENT_SHA, transition_step=0)
RECORD = dict(TRANSITION, parent_manifest_sha256=PARENT_SHA, transition_step=0)         # the lineage record
CHAIN = {'root': 'B:/parent', 'manifest_sha256': 'a' * 64}


HOUR = {'schema': 'governed-hour-v1', 'arm': 'treatment', 'minimum_wall_seconds': 3600, 'minimum_measured_steps': 1024}


def hour_identity(**extra):
    identity = {'hour': dict(HOUR), 'optimizer': runner.expected_optimizer({'hour': dict(HOUR)}),
                'parent_checkpoint': dict(CHAIN)}
    identity.update(extra)
    return identity


class ConstructorTimeChangeRefusesTests(unittest.TestCase):
    """(a) The optimizer is always constructed from the one fixed definition; the change is the declared transition."""

    def test_constructor_time_lr_change_refuses_at_identity_validation(self):
        for transition in (None, dict(TRANSITION)):
            identity = hour_identity(**({'optimizer_transition': transition} if transition else {}))
            identity['optimizer'] = dict(identity['optimizer'], lr=TO)
            with self.subTest(transition=bool(transition)), self.assertRaisesRegex(ValueError, 'fixed optimizer definition differs'):
                runner.check_fixed_optimizer(identity)

    def test_declared_transition_with_the_fixed_constructor_definition_is_admitted(self):
        runner.check_fixed_optimizer(hour_identity(optimizer_transition=dict(TRANSITION)))
        runner.check_fixed_optimizer(hour_identity())

    def test_transition_shape_is_closed(self):
        bad = [dict(TRANSITION, to_lr=0.0003), dict(TRANSITION, to_lr=1), dict(TRANSITION, from_lr=0.002),
               dict(TRANSITION, kind='other'), {**TRANSITION, 'extra': 1},
               {key: value for key, value in TRANSITION.items() if key != 'to_lr'}, 'text', None]
        for value in bad:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'pinned learning-rate-only'):
                runner.check_fixed_optimizer(hour_identity(optimizer_transition=value))

    def test_transition_needs_a_chained_parent(self):
        identity = hour_identity(optimizer_transition=dict(TRANSITION))
        del identity['parent_checkpoint']
        with self.assertRaisesRegex(ValueError, 'pinned learning-rate-only'):
            runner.check_fixed_optimizer(identity)


class FixtureModel:
    """A CIA decoder with injected Adam state on a few parameters (meta storage; no 3B allocation)."""

    def __init__(self, lr=FROM, steps=(7.0, 7.0, 3.0)):
        self.model = CIADecoder()
        self.parameters = self.model.parameter_inventory()
        self.optimizer = torch.optim.AdamW(list(self.parameters.values()), lr=lr, foreach=False)
        for (name, parameter), step in zip(list(self.parameters.items())[:len(steps)], steps):
            self.optimizer.state[parameter] = {'step': torch.tensor(step),
                'exp_avg': torch.zeros_like(parameter), 'exp_avg_sq': torch.zeros_like(parameter)}


class TransitionAppliesOnlyTheLearningRateTests(unittest.TestCase):
    """(b) Param-group learning rate reads the target; the Adam step counts and moment tensors equal the parent's."""

    def test_every_group_reads_the_target_and_step_counts_are_the_parents(self):
        fixture = FixtureModel()
        before = {name: float(fixture.optimizer.state[p]['step']) for name, p in fixture.parameters.items()
                  if p in fixture.optimizer.state}
        tensors = {id(p): (id(f['exp_avg']), f['exp_avg']._version) for p, f in fixture.optimizer.state.items()}
        result = artifacts.apply_cia_lr_transition(fixture.model, fixture.optimizer, from_lr=FROM, to_lr=TO, **APPLY)
        self.assertEqual(fixture.optimizer.defaults['lr'], TO)
        self.assertTrue(fixture.optimizer.param_groups and all(group['lr'] == TO for group in fixture.optimizer.param_groups))
        after = {name: float(fixture.optimizer.state[p]['step']) for name, p in fixture.parameters.items()
                 if p in fixture.optimizer.state}
        self.assertEqual(before, after)
        self.assertEqual({id(p): (id(f['exp_avg']), f['exp_avg']._version) for p, f in fixture.optimizer.state.items()}, tensors)
        self.assertEqual(result['transition'], RECORD)
        self.assertEqual(result['parameters_with_state'], 3)
        self.assertEqual((result['step_counter_min'], result['step_counter_max']), (3.0, 7.0))
        self.assertNotEqual(result['identity_before_sha256'], result['identity_after_sha256'])

    def test_identity_after_differs_from_before_in_learning_rate_fields_only(self):
        fixture = FixtureModel()
        before = artifacts.cia_optimizer_identity(fixture.model, fixture.optimizer)
        artifacts.apply_cia_lr_transition(fixture.model, fixture.optimizer, from_lr=FROM, to_lr=TO, **APPLY)
        after = artifacts.cia_optimizer_identity(fixture.model, fixture.optimizer)
        self.assertEqual(after, counter._cia_optimizer_identity_at_lr(before, TO))
        self.assertNotEqual(after, before)

    def test_restored_lr_other_than_from_lr_refuses_without_changing_anything(self):
        fixture = FixtureModel(lr=0.01)
        with self.assertRaisesRegex(ValueError, 'from_lr differs'):
            artifacts.apply_cia_lr_transition(fixture.model, fixture.optimizer, from_lr=FROM, to_lr=TO, **APPLY)
        self.assertEqual(fixture.optimizer.defaults['lr'], 0.01)
        self.assertTrue(all(group['lr'] == 0.01 for group in fixture.optimizer.param_groups))

    def test_scheduler_style_initial_lr_refuses(self):
        fixture = FixtureModel()
        fixture.optimizer.param_groups[0]['initial_lr'] = FROM
        with self.assertRaises(ValueError):
            artifacts.apply_cia_lr_transition(fixture.model, fixture.optimizer, from_lr=FROM, to_lr=TO, **APPLY)

    def test_a_non_decoder_or_bad_transition_refuses(self):
        fixture = FixtureModel()
        for to_lr in (FROM, 0.0, 1.5):
            with self.subTest(to_lr=to_lr), self.assertRaises(ValueError):
                artifacts.apply_cia_lr_transition(fixture.model, fixture.optimizer, from_lr=FROM, to_lr=to_lr, **APPLY)
        with self.assertRaises(ValueError):
            artifacts.apply_cia_lr_transition(object(), fixture.optimizer, from_lr=FROM, to_lr=TO, **APPLY)


class ChildManifestRecordsTheTransitionTests(unittest.TestCase):
    """(c) The first-descendant lineage records the transition; the optimizer identity may differ only by that lr."""

    def arguments(self, transition=True):
        parent_fixture = FixtureModel(lr=FROM)
        child_fixture = FixtureModel(lr=TO)
        parent_identity = artifacts.cia_optimizer_identity(parent_fixture.model, parent_fixture.optimizer)
        child_identity = artifacts.cia_optimizer_identity(child_fixture.model, child_fixture.optimizer)
        parent = dict(data_cursor=dict(global_step=0, tokens_seen=0), expert_genesis_sha256={},
                      checkpoint_manifest_sha256='a' * 64, _parent_counter_receipt_sha256='b' * 64,
                      optimizer_identity=parent_identity,
                      placement={'dense': {'requires_grad': True}})
        child = copy.deepcopy(parent)
        child['data_cursor'] = dict(global_step=3, tokens_seen=12)
        child['optimizer_identity'] = child_identity
        if transition:
            child['lineage'] = dict(optimizer_transition=dict(RECORD))
        before = dict(parameters=dict(dense='a'), optimizer={}, elements=dict(dense=1))
        after = dict(parameters=dict(dense='d'), optimizer=dict(dense=dict(step=3)), elements=dict(dense=1))
        return [Path('fixture'), parent, before, child, after]

    def test_recorded_transition_admits_the_lr_only_difference_and_is_returned(self):
        lineage = counter._cia_derive_first_lineage(*self.arguments())
        self.assertEqual(lineage['optimizer_transition'], RECORD)
        self.assertEqual(lineage['schema_version'], 'ember-cia-first-descendant-v3')

    def test_the_same_difference_without_a_recorded_transition_refuses(self):
        with self.assertRaisesRegex(ValueError, 'optimizer_identity differ'):
            counter._cia_derive_first_lineage(*self.arguments(transition=False))

    def test_writer_passed_transition_matches_the_recorded_form(self):
        args = self.arguments(transition=False)
        lineage = counter._cia_derive_first_lineage(*args, optimizer_transition=dict(RECORD))
        self.assertEqual(lineage['optimizer_transition'], RECORD)

    def test_a_transition_with_any_other_identity_difference_refuses(self):
        for mutate in ('eps', 'betas', 'weight_decay', 'amsgrad', 'default_eps'):
            args = self.arguments()
            groups = args[3]['optimizer_identity']['param_groups']
            if mutate == 'default_eps':
                args[3]['optimizer_identity']['defaults']['eps'] = 1e-7
            else:
                groups[0]['hyperparameters'][mutate] = {'eps': 1e-7, 'betas': [0.8, 0.99], 'weight_decay': 0.2, 'amsgrad': True}[mutate]
            with self.subTest(mutate=mutate), self.assertRaisesRegex(ValueError, 'differs from the parent and child'):
                counter._cia_derive_first_lineage(*args)

    def test_a_transition_naming_the_wrong_rates_refuses(self):
        for bad in (dict(RECORD, to_lr=0.0003), dict(RECORD, from_lr=0.002), dict(RECORD, extra=1)):
            args = self.arguments()
            args[3]['lineage'] = dict(optimizer_transition=bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                counter._cia_derive_first_lineage(*args)

    def test_a_record_naming_another_parent_or_step_refuses(self):
        for bad in (dict(RECORD, parent_manifest_sha256='b' * 64), dict(RECORD, transition_step=1),
                    dict(RECORD, transition_step=-1), dict(RECORD, parent_manifest_sha256='A' * 64)):
            args = self.arguments()
            args[3]['lineage'] = dict(optimizer_transition=bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                counter._cia_derive_first_lineage(*args)

    def test_a_group_left_at_the_old_rate_refuses(self):
        args = self.arguments()
        args[3]['optimizer_identity']['defaults']['lr'] = FROM
        with self.assertRaisesRegex(ValueError, 'differs from the parent and child'):
            counter._cia_derive_first_lineage(*args)

    def test_a_non_descendant_publication_cannot_carry_a_transition(self):
        fixture = FixtureModel()
        with self.assertRaisesRegex(ValueError, 'actual parent transition'):
            artifacts.write_checkpoint_artifacts(fixture.model, fixture.optimizer, Path('target/never-written'),
                launch_seed=1, rng_state={}, data_cursor=dict(global_step=0, tokens_seen=0),
                model_config_sha256='a' * 64, contract_sha256='b' * 64, expert_genesis_sha256={},
                cia_optimizer_transition=dict(RECORD), max_serialized_bytes=1, max_transient_scratch_bytes=1,
                pre_publish_verifier=lambda candidate, receipt: {})

    def test_uniform_lineage_without_a_transition_is_unchanged(self):
        args = self.arguments(transition=False)
        args[3]['optimizer_identity'] = copy.deepcopy(args[1]['optimizer_identity'])
        lineage = counter._cia_derive_first_lineage(*args)
        self.assertNotIn('optimizer_transition', lineage)
        self.assertEqual(lineage['schema_version'], 'ember-cia-first-descendant-v1')


class VerifyTailPinTests(unittest.TestCase):
    """A tail of a lost hour that changed the learning rate carries the same declared change in its pin."""
    LOST = 'b' * 32
    HOUR = {'schema': 'governed-hour-v1', 'arm': 'control', 'minimum_wall_seconds': 3600, 'minimum_measured_steps': 1024}

    def tail_identity(self, **pin_extra):
        pin = {'lost_custody': 'B:/x/measurement-' + self.LOST, 'lost_run_id': self.LOST,
               'witness_sha256': 'c' * 64, 'child_manifest_sha256': 'd' * 64}
        pin.update(pin_extra)
        return {'run_id': 'e' * 32, 'hour': dict(self.HOUR), 'training_job_purpose': 'DIAGNOSTIC',
                'optimizer': runner.expected_optimizer({'hour': dict(self.HOUR)}),
                'geometry': dict(documents_per_step=4, sequence_length=1024, warm_steps=1, measured_steps=2), 'verify_tail': pin}

    def test_pin_admits_only_the_pinned_declaration(self):
        self.assertTrue(runner.verify_tail_mode(self.tail_identity()))
        self.assertTrue(runner.verify_tail_mode(self.tail_identity(optimizer_transition=dict(TRANSITION))))
        for bad in (dict(TRANSITION, to_lr=0.0003), dict(RECORD), {**TRANSITION, 'extra': 1}, 'text', None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                runner.verify_tail_mode(self.tail_identity(optimizer_transition=bad))

    def run_tail(self, *, recorded, declared):
        fixture = FixtureModel()
        child = {'checkpoint_manifest_sha256': 'd' * 64, 'data_cursor': {'global_step': 9},
                 **({'lineage': {'optimizer_transition': recorded}} if recorded else {})}
        witness = {'child_manifest_sha256': 'd' * 64, 'data_cursor': child['data_cursor'],
                   'terminal_state': {'data_cursor': child['data_cursor']}}
        identity = self.tail_identity(**({'optimizer_transition': declared} if declared else {}))
        calls = []
        with tempfile.TemporaryDirectory() as lost,                 patch.object(hour, 'read_terminal_witness', return_value=(witness, 'c' * 64)),                 patch.object(artifacts, 'published_checkpoint_receipt', return_value=child),                 patch.object(hour, 'verify_checkpoint_restore',
                             side_effect=lambda *a, **k: calls.append(a[2].defaults['lr'])):
            result = hour.verify_tail(runner, fixture.model, fixture.optimizer, {}, identity, lost)
        return result, calls, fixture

    def test_declared_transition_is_applied_before_the_child_restore(self):
        result, calls, fixture = self.run_tail(recorded=dict(RECORD), declared=dict(TRANSITION))
        self.assertEqual(calls, [TO])
        self.assertEqual(fixture.optimizer.defaults['lr'], TO)
        self.assertEqual(result['status'], 'RESTORE_VERIFIED_FROM_WITNESS')

    def test_no_transition_anywhere_leaves_the_constructed_rate(self):
        result, calls, fixture = self.run_tail(recorded=None, declared=None)
        self.assertEqual(calls, [FROM])

    def test_recorded_and_pinned_transitions_must_agree(self):
        for recorded, declared in ((dict(RECORD), None), (None, dict(TRANSITION)),
                                   (dict(RECORD, to_lr=0.0003), dict(TRANSITION))):
            with self.subTest(recorded=recorded, declared=declared), self.assertRaisesRegex(ValueError, 'recorded optimizer transition'):
                self.run_tail(recorded=recorded, declared=declared)


class RunHourOrderTests(unittest.TestCase):
    """The change comes after the exact parent restore and before graph capture binds the optimizer."""

    def test_transition_is_applied_between_restore_and_capture_and_published_with_the_child(self):
        source = inspect.getsource(hour.run_hour)
        order = [source.index(text) for text in (
            'artifacts.load_checkpoint_artifacts(model, optimizer, parent_root, parent',
            "chained hour data cursor differs from its parent checkpoint cursor",
            'artifacts.apply_cia_lr_transition(', "'lr-transition.json'", 'bind_hour_capture(runner, model')]
        self.assertEqual(order, sorted(order))
        self.assertTrue("optimizer_transition=dict(applied_transition['transition']) if transition is not None else None" in source)

    def test_publish_forwards_the_transition_to_the_writer(self):
        self.assertIn('cia_optimizer_transition=optimizer_transition', inspect.getsource(hour.checkpoint_publisher))


if __name__ == '__main__':
    unittest.main()
