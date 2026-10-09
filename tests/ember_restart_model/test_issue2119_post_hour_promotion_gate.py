"""Issue #2119 clause 1: the post-hour promotion gate (production wiring of the scored-pair path) and the dispatch-script lint that requires it.

One test per path of the gate (refuse, no-binding, delegate, passthrough) and per lint outcome; each guard carries a deliberate red (the control shows what
the unguarded shape would have done)."""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import dispatch_tree_check as tree_check  # noqa: E402
import post_hour_promotion_gate as gate  # noqa: E402

SHA = 'e' * 64


class GateFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.custody = self.root / 'measurement-run1'
        self.custody.mkdir()
        self.parent = self.root / 'receipts'
        self.parent.mkdir()
        self.entry = self.root / 'entry.json'
        self.entry.write_text('{}', encoding='utf-8')
        self.calls = []

    def identity(self, **fields):
        path = self.root / 'identity.json'
        path.write_text(json.dumps({'identity': fields}), encoding='utf-8')
        return path

    def run_gate(self, identity, *extra, cli_rc=0, cli_out='{"promotion": "NOT_ATTEMPTED_NO_RULING"}'):
        def fake_cli(argv):
            self.calls.append(list(argv))
            print(cli_out)
            return cli_rc
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gate.main(['--identity', str(identity), '--custody', str(self.custody), '--parent', str(self.parent), *extra], cli_main=fake_cli)
        return code, out.getvalue()

    def receipt(self):
        path = self.custody / gate.RECEIPT_FILENAME
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None


class GateTests(GateFixture):

    def test_continue_training_identity_has_no_promotion_path_and_never_reaches_the_cli_DELIBERATE_RED(self):
        identity = self.identity(training_job_purpose='CONTINUE_TRAINING', run_id='run1')
        code, _ = self.run_gate(identity, '--entry', str(self.entry), '--ruling', 'R1')
        self.assertEqual(code, gate.EXIT_NO_PROMOTION_PATH)
        self.assertEqual(self.calls, [])           # the unguarded shape would have called scored_pair_cli with a ruling
        receipt = self.receipt()
        self.assertEqual(receipt['status'], 'NO_PROMOTION_PATH')
        self.assertEqual(receipt['training_job_purpose'], 'CONTINUE_TRAINING')

    def test_retention_identity_without_the_binding_sha_has_no_promotion_path(self):
        code, _ = self.run_gate(self.identity(training_job_purpose=gate.BOUND_PURPOSE), '--entry', str(self.entry))
        self.assertEqual(code, gate.EXIT_NO_PROMOTION_PATH)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.receipt()['scored_pair_binding_present'])

    def test_a_malformed_binding_sha_has_no_promotion_path(self):
        code, _ = self.run_gate(self.identity(training_job_purpose=gate.BOUND_PURPOSE, scored_pair_binding_sha256='XYZ'), '--entry', str(self.entry))
        self.assertEqual(code, gate.EXIT_NO_PROMOTION_PATH)
        self.assertEqual(self.calls, [])

    def test_bound_identity_delegates_with_exactly_the_given_arguments(self):
        identity = self.identity(training_job_purpose=gate.BOUND_PURPOSE, scored_pair_binding_sha256=SHA, run_id='run1')
        arms = self.root / 'arms.json'
        code, out = self.run_gate(identity, '--entry', str(self.entry), '--arms', str(arms), '--ruling', 'R9')
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, [['--identity', str(identity), '--entry', str(self.entry), '--custody', str(self.custody), '--parent', str(self.parent),
                                       '--arms', str(arms), '--ruling', 'R9']])
        receipt = self.receipt()
        self.assertEqual(receipt['status'], 'DELEGATED')
        self.assertEqual(receipt['scored_pair_cli_exit'], 0)
        self.assertEqual(receipt['ruling'], 'R9')
        self.assertIn('NOT_ATTEMPTED_NO_RULING', out)

    def test_cli_exit_codes_pass_through_and_are_recorded(self):
        identity = self.identity(training_job_purpose=gate.BOUND_PURPOSE, scored_pair_binding_sha256=SHA)
        for rc in (3, 4):
            code, _ = self.run_gate(identity, '--entry', str(self.entry), cli_rc=rc, cli_out='{"status": "REFUSED"}')
            self.assertEqual(code, rc)
            self.assertEqual(self.receipt()['scored_pair_cli_exit'], rc)

    def test_bound_identity_without_an_entry_refuses_before_any_write(self):
        identity = self.identity(training_job_purpose=gate.BOUND_PURPOSE, scored_pair_binding_sha256=SHA)
        code, _ = self.run_gate(identity)
        self.assertEqual(code, gate.EXIT_REFUSED)
        self.assertEqual(self.calls, [])
        self.assertIsNone(self.receipt())

    def test_unreadable_identity_and_missing_custody_refuse_before_any_write(self):
        bad = self.root / 'identity.json'
        bad.write_text('not json', encoding='utf-8')
        code, _ = self.run_gate(bad)
        self.assertEqual(code, gate.EXIT_REFUSED)
        good = self.identity(training_job_purpose='CONTINUE_TRAINING')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gate.main(['--identity', str(good), '--custody', str(self.root / 'absent'), '--parent', str(self.parent)])
        self.assertEqual(code, gate.EXIT_REFUSED)
        self.assertIsNone(self.receipt())

    def test_real_cli_refusal_passes_through_for_a_foreign_entry(self):
        identity = self.identity(training_job_purpose=gate.BOUND_PURPOSE, scored_pair_binding_sha256=SHA, run_id='run1')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gate.main(['--identity', str(identity), '--custody', str(self.custody), '--parent', str(self.parent), '--entry', str(self.root / 'absent.json')])
        self.assertEqual(code, 3)
        self.assertEqual(self.receipt()['scored_pair_cli_exit'], 3)



def bad_score_rows():
    """Scorer-v12 arms.fresh shapes that carry no usable scored rows. Each is refused by name (review finding 1; the first is the reviewer's pinned counterexample)."""
    row = {'loss_sum': 4608.0, 'targets': 1024}
    good = {'episodes': 2, 'total_nll': 9216.0, 'targets': 2048, 'mean_nll': 4.5, 'per_episode': [dict(row), dict(row)]}
    def with_rows(first, **over):
        return dict(good, per_episode=[first, dict(row)], **over)
    return {
        'rows with no scored values': {'episodes': 2, 'mean_nll': 4.5, 'per_episode': [{}, {}]},
        'rows with no scored values and consistent totals': dict(good, per_episode=[{}, {}]),
        'nan loss_sum': with_rows(dict(row, loss_sum=float('nan'))),
        'infinite loss_sum': with_rows(dict(row, loss_sum=float('inf'))),
        'negative loss_sum': with_rows(dict(row, loss_sum=-1.0)),
        'string loss_sum': with_rows(dict(row, loss_sum='4608.0')),
        'target count 0': with_rows(dict(row, targets=0), targets=1024),
        'fractional target count': with_rows(dict(row, targets=1024.5)),
        'boolean target count': with_rows(dict(row, targets=True)),
        'row is not an object': dict(good, per_episode=[4.5, 4.5]),
        'mean disagrees with the rows': dict(good, mean_nll=9.0),
        'total_nll disagrees with the rows': dict(good, total_nll=100.0),
        'arm targets disagree with the rows': dict(good, targets=2049),
        'no total_nll': {key: value for key, value in good.items() if key != 'total_nll'},
        'no arm targets': {key: value for key, value in good.items() if key != 'targets'},
    }


_OMIT = object()          # a score() override that removes the key from the receipt


class CadenceTests(GateFixture):
    """Row 20: the declared cadence (a8ffe5a5). A head advance needs a scorer-v12 receipt for exactly that child, on the frozen plan, whose bytes hash to the cited digest."""
    CHILD = 'c' * 64

    def score(self, **over):
        body = {'schema': gate.CADENCE_SCORE_SCHEMA, 'label': 'H99 child episode NLL v12 template forward',
                'bindings': {'episode_plan_sha256': gate.CADENCE_PLAN_SHA256, 'checkpoint_manifest_sha256': self.CHILD},
                'arms': {'fresh': {'episodes': 2, 'total_nll': 9216.0, 'targets': 2048, 'mean_nll': 4.5, 'per_episode': [{'loss_sum': 4608.0, 'targets': 1024}, {'loss_sum': 4608.0, 'targets': 1024}]}}}
        body.update(over)
        body = {key: value for key, value in body.items() if value is not _OMIT}
        path = self.custody / 'episode-nll.json'
        path.write_text(json.dumps(body, sort_keys=True), encoding='utf-8')
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def advance(self, path, digest, **identity):
        fields = dict(training_job_purpose='CONTINUE_TRAINING', run_id='run1')
        fields.update(identity)
        extra = ['--advance-child', self.CHILD]
        if path is not None:
            extra += ['--score-receipt', str(path)]
        if digest is not None:
            extra += ['--score-receipt-sha256', digest]
        return self.run_gate(self.identity(**fields), *extra)

    def test_a_matching_receipt_passes_the_cadence_and_the_gate_proceeds_to_its_own_path(self):
        path, digest = self.score()
        code, _ = self.advance(path, digest)
        self.assertEqual(code, gate.EXIT_NO_PROMOTION_PATH)            # the cadence passed; this identity still has no promotion path
        cadence = self.receipt()['cadence']
        self.assertEqual((cadence['requested'], cadence['problems'], cadence['score_receipt_sha256']), (True, [], digest))

    def test_a_pass_prints_an_explicit_cadence_verdict_and_a_refusal_never_does_DELIBERATE_RED(self):
        """Row 20: the pass is visible on its own line and in the receipt; it is not inferred from the exit code of whatever status follows it."""
        path, digest = self.score()
        code, out = self.advance(path, digest)
        self.assertEqual(code, gate.EXIT_NO_PROMOTION_PATH)
        passed = [json.loads(line) for line in out.splitlines() if line.startswith('{"') and json.loads(line).get('status') == 'CADENCE_PASSED']
        self.assertEqual(len(passed), 1, out)
        self.assertEqual((passed[0]['advance_child'], passed[0]['score_receipt_sha256'], passed[0]['plan_sha256'], passed[0]['declaration_sha256_enforced']),
                         (self.CHILD, digest, gate.CADENCE_PLAN_SHA256, gate.CADENCE_DECLARATION_SHA256))
        self.assertEqual(self.receipt()['cadence']['verdict'], 'PASS')
        code, out = self.advance(None, None)
        self.assertEqual(code, gate.EXIT_CADENCE_REFUSED)
        self.assertNotIn('CADENCE_PASSED', out)
        self.assertEqual(self.receipt()['cadence']['verdict'], 'REFUSED')

    def test_a_missing_receipt_refuses_the_advance_DELIBERATE_RED(self):
        code, out = self.advance(None, None)
        self.assertEqual(code, gate.EXIT_CADENCE_REFUSED)
        self.assertIn('a missing score receipt means no advance', out)
        self.assertEqual(self.receipt()['status'], 'CADENCE_REFUSED')
        self.assertEqual(self.calls, [])                                # the unguarded shape would have gone on to delegate
        code, _ = self.advance(self.custody / 'absent.json', 'a' * 64)  # a cited path that does not exist is the same refusal
        self.assertEqual(code, gate.EXIT_CADENCE_REFUSED)

    def test_a_wrong_receipt_digest_refuses_the_advance_DELIBERATE_RED(self):
        path, digest = self.score()
        code, out = self.advance(path, '0' * 64)
        self.assertEqual(code, gate.EXIT_CADENCE_REFUSED)
        self.assertIn('do not hash to the cited sha256', out)
        self.assertNotEqual(digest, '0' * 64)

    def test_a_bound_identity_is_never_delegated_when_the_cadence_refuses(self):
        code, _ = self.advance(None, None, training_job_purpose=gate.BOUND_PURPOSE, scored_pair_binding_sha256=SHA)
        self.assertEqual(code, gate.EXIT_CADENCE_REFUSED)
        self.assertEqual(self.calls, [])

    def test_a_receipt_for_another_child_plan_schema_or_scorer_refuses(self):
        cases = {
            'other child': dict(bindings={'episode_plan_sha256': gate.CADENCE_PLAN_SHA256, 'checkpoint_manifest_sha256': 'd' * 64}),
            'other plan': dict(bindings={'episode_plan_sha256': 'f' * 64, 'checkpoint_manifest_sha256': self.CHILD}),
            'other schema': dict(schema='something-else'),
            'other scorer': dict(label='H99 child episode NLL v11 template forward'),
            'no bindings': dict(bindings=None),
        }
        for name, over in cases.items():
            with self.subTest(name):
                path, digest = self.score(**over)
                code, _ = self.advance(path, digest)
                self.assertEqual(code, gate.EXIT_CADENCE_REFUSED)

    def test_a_receipt_with_the_right_header_and_no_scores_refuses_the_advance_DELIBERATE_RED(self):
        fresh = {'episodes': 2, 'mean_nll': 4.5, 'per_episode': [{}, {}]}
        for name, over in {'no arms': dict(arms=_OMIT), 'empty arms': dict(arms={}), 'zero episodes': dict(arms={'fresh': dict(fresh, episodes=0)}),
                           'no mean': dict(arms={'fresh': dict(fresh, mean_nll=None)}), 'rows differ': dict(arms={'fresh': dict(fresh, per_episode=[])})}.items():
            with self.subTest(name):
                path, digest = self.score(**over)
                code, out = self.advance(path, digest)
                self.assertEqual(code, gate.EXIT_CADENCE_REFUSED)
                self.assertIn('carries no scores', out)
                self.assertEqual(self.calls, [])

    def test_a_receipt_whose_rows_carry_no_valid_scored_values_refuses_the_advance_DELIBERATE_RED(self):
        for name, fresh in bad_score_rows().items():
            with self.subTest(name):
                path, digest = self.score(arms={'fresh': fresh})
                code, out = self.advance(path, digest)
                self.assertEqual(code, gate.EXIT_CADENCE_REFUSED)
                self.assertIn('carries no scores', out)
                self.assertEqual(self.calls, [])

    def test_the_declaration_bytes_must_hash_to_the_frozen_declaration(self):
        path, digest = self.score()
        declaration = self.root / 'declaration.md'
        declaration.write_text('not the frozen declaration', encoding='utf-8')
        code, out = self.run_gate(self.identity(training_job_purpose='CONTINUE_TRAINING'), '--advance-child', self.CHILD, '--score-receipt', str(path),
                                  '--score-receipt-sha256', digest, '--cadence-declaration', str(declaration))
        self.assertEqual(code, gate.EXIT_CADENCE_REFUSED)
        self.assertIn('differ from the frozen declaration', out)

    def test_no_advance_child_leaves_the_gate_unchanged_and_records_that_the_cadence_was_not_requested(self):
        code, _ = self.run_gate(self.identity(training_job_purpose='CONTINUE_TRAINING'))
        self.assertEqual(code, gate.EXIT_NO_PROMOTION_PATH)
        self.assertEqual(self.receipt()['cadence'], {'requested': False})

    def test_a_malformed_child_digest_refuses(self):
        self.assertEqual(gate.cadence_problems('XYZ', None, None), ['the child manifest digest to advance to is not a sha256'])


class DispatchLintTests(unittest.TestCase):
    GATE = 'python -B $T/post_hour_promotion_gate.py --identity "$I" --custody "$C" --parent "$P" --advance-child "$CHILD" --score-receipt "$R"'
    HANDLER = 'case $? in 0|5) ;; *) echo "REFUSE rc17: post-hour gate"; exit 17;; esac'
    GOOD = f'#!/usr/bin/env bash\nrun_hour\n{GATE}\n{HANDLER}\npython promote_with_pending_v1.py S\n'

    def test_gate_before_promotion_passes(self):
        self.assertEqual(tree_check.dispatch_script_gate_problems(self.GOOD), [])

    def test_the_one_line_refusal_handler_passes(self):
        text = f'run_hour\n{self.GATE} || {{ echo REFUSE; exit 17; }}\npython promote_with_pending_v1.py S\n'
        self.assertEqual(tree_check.dispatch_script_gate_problems(text), [])

    def test_missing_gate_fails(self):
        self.assertTrue(tree_check.dispatch_script_gate_problems('run_hour\npython promote_with_pending_v1.py S\n'))

    def test_commented_out_gate_fails_DELIBERATE_RED(self):
        text = '# python post_hour_promotion_gate.py --identity i\nrun_hour\n'
        self.assertIn('post_hour_promotion_gate.py', text)            # a plain substring check (the pre-fix shape) would pass this
        self.assertTrue(tree_check.dispatch_script_gate_problems(text))

    def test_promotion_before_the_gate_fails(self):
        text = f'python promote_with_pending_v1.py S\n{self.GATE}\n{self.HANDLER}\n'
        problems = tree_check.dispatch_script_gate_problems(text)
        self.assertEqual(problems, ['line 1 reaches a promotion entry before the gate'])

    def test_direct_scored_pair_cli_before_the_gate_fails(self):
        problems = tree_check.dispatch_script_gate_problems(f'python scored_pair_cli.py --identity i\n{self.GATE}\n{self.HANDLER}\n')
        self.assertEqual(len(problems), 1)

    def test_a_gate_whose_refusal_is_swallowed_fails_DELIBERATE_RED(self):
        for tail in (' || true', ' || :', '; true'):
            text = f'run_hour\n{self.GATE}{tail}\n{self.HANDLER}\npython promote_with_pending_v1.py S\n'
            problems = tree_check.dispatch_script_gate_problems(text)
            self.assertEqual(len(problems), 1, (tail, problems))
            self.assertIn('swallows the gate refusal', problems[0])

    def test_a_gate_with_no_refusal_handler_fails_DELIBERATE_RED(self):
        problems = tree_check.dispatch_script_gate_problems(f'run_hour\n{self.GATE}\npython promote_with_pending_v1.py S\n')
        self.assertEqual(len(problems), 1)
        self.assertIn('no refusal handler', problems[0])

    def test_a_head_moving_script_whose_gate_omits_advance_child_fails_DELIBERATE_RED(self):
        gate = self.GATE.replace(' --advance-child "$CHILD" --score-receipt "$R"', '')
        for mover in ('promote_with_pending_v1.py S', 'advance_selected_continuation_head X'):
            problems = tree_check.dispatch_script_gate_problems(f'run_hour\n{gate}\n{self.HANDLER}\npython {mover}\n')
            self.assertEqual(len(problems), 1, (mover, problems))
            self.assertIn('--advance-child', problems[0])

    def test_a_script_that_never_moves_the_head_needs_no_advance_child(self):
        gate = self.GATE.replace(' --advance-child "$CHILD" --score-receipt "$R"', '')
        self.assertEqual(tree_check.dispatch_script_gate_problems(f'run_hour\n{gate}\n{self.HANDLER}\n'), [])


if __name__ == '__main__':
    unittest.main()
