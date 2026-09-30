# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tail-cure fixtures (mail 40920/40938/40951/40957; REDO per mail 41024/41025).

One validation operation per top-level publish/admit/restore. Authored as text during R3's window; run only after
WINDOW_CLOSED. Scaffolding is borrowed from test_issue2163_cia_transaction.py WITHOUT inheriting its test_ methods.

Boundary for F5 (stated, one only): option (a). A visit table measures ONE validation operation, namely
`artifacts._cia_validated_checkpoint(tip_root, tip_receipt)` wrapped in `counter.cia_validation_operation()`, on a
homogeneous current-source chain whose tip has d ancestors (d+1 published nodes). It does NOT include a publication, the
undigested parent snapshot in the write path, or the quarantine admission; those are out of scope for this table.
Frozen predictions (written before any run, state/tailcure/visit-scaling-predictions.md): snapshot_reopened = d,
snapshot_calls = 2d-1, validated_full = d. A mismatch is reported as measured; the prediction is never relabelled.

Every fixture that needs the historic counter FAILS (not skips) when the sha-verified counter-history copy is absent."""
import hashlib
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_issue2163_cia_transaction as _scaffold_source
from test_issue2163_cia_transaction import artifacts, counter

HISTORIC = '7d46fc9db80c30427ade481cda5feefa473869a0bfbe12c5aa068a7426176e47'
HISTORY_FILE = Path(counter.__file__).parent / 'counter-history' / ('parameter_counter-%s.py' % HISTORIC)
CURRENT_SHA = hashlib.sha256(Path(counter.__file__).read_bytes()).hexdigest()
EXECUTED = []


class _Scaffold:
    """Only the fixture plumbing of TransactionTests; no test_ method is copied."""
    setUp = _scaffold_source.TransactionTests.setUp
    verifier = _scaffold_source.TransactionTests.verifier
    publish = _scaffold_source.TransactionTests.publish


del _scaffold_source


class ValidationOperationTests(_Scaffold, unittest.TestCase):
    def setUp(self):
        _Scaffold.setUp(self)
        EXECUTED.append(self.id())

    # ---- chain building ----
    def extend(self, name):
        parent_root = self.root
        self.root = parent_root.parent / name
        parameter = self.parameters['embedding.weight']
        parameter.grad = torch.ones_like(parameter)
        self.optimizer.step()
        self.optimizer.zero_grad(set_to_none=True)
        cursor = dict(self.kwargs['data_cursor'])
        cursor['global_step'] = int(cursor['global_step']) + 1
        self.kwargs['data_cursor'] = cursor
        self.kwargs['cia_parent_checkpoint'] = parent_root
        return self.root, self.publish()

    def chain(self, nodes):
        """`nodes` published nodes: zero-step genesis then descendants; self.root is the tip. Returns [(root, receipt)]."""
        out = [(self.root, self.publish())]
        for i in range(1, nodes):
            out.append(self.extend('n%d' % i))
        return out

    def require_historic(self):
        if not HISTORY_FILE.is_file():
            self.fail('MISSING COVERAGE: counter-history copy of 7d46fc9d is absent at %s' % HISTORY_FILE)
        self.assertEqual(hashlib.sha256(HISTORY_FILE.read_bytes()).hexdigest(), HISTORIC)
        return counter._counter_for(HISTORIC)

    def verify_with(self, module):
        """Make the persisted counter receipt of the next publication come from `module`'s counter."""
        def verifier(candidate, receipt):
            result = module.execute_counter(model_config=self.config_path,
                                            checkpoint_manifest=candidate / 'checkpoint-manifest.json', active_expert='all')
            (candidate / 'parameter-counter-receipt.json').write_text(json.dumps(result), encoding='utf-8')
            return result
        self.kwargs['pre_publish_verifier'] = verifier

    def counts(self, operation):
        v = operation.visits
        return (v['snapshot_reopened'], v['snapshot_calls'], v['validated_full'])

    # ---- F5: visit table, boundary (a): one validation operation on the tip ----
    def test_f5_visit_count_table_by_depth_homogeneous_current_source(self):
        table = {}
        for d in (1, 2, 3, 4):
            _Scaffold.setUp(self)  # fresh temp tree per depth
            nodes = self.chain(d + 1)
            tip_root, tip_receipt = nodes[-1]
            with counter.cia_validation_operation() as operation:
                artifacts._cia_validated_checkpoint(tip_root, tip_receipt)
            table[d] = self.counts(operation)
        Path(os.environ.get('TAILCURE_TABLE', 'visit-table.json')).write_text(json.dumps(
            {str(k): {'snapshot_reopened': v[0], 'snapshot_calls': v[1], 'validated_full': v[2]} for k, v in table.items()},
            indent=1), encoding='utf-8')
        for d, (reopened, calls, full) in table.items():
            self.assertEqual((reopened, calls, full), (d, 2 * d - 1, d), 'depth %d, boundary (a)' % d)

    # ---- F1: identical bytes and refusals versus uncached ----
    def test_f1_operation_result_equals_uncached_result(self):
        nodes = self.chain(3)
        tip_root, tip_receipt = nodes[-1]
        with counter.cia_validation_operation():
            cached = artifacts._cia_validated_checkpoint(tip_root, tip_receipt)
        with patch.object(counter, '_CIA_OPERATION') as off:
            off.get.return_value = None
            uncached = artifacts._cia_validated_checkpoint_impl(tip_root, tip_receipt)
        self.assertEqual(repr(cached), repr(uncached))

    def test_f1_refusal_text_identical_cached_and_uncached(self):
        nodes = self.chain(3)
        target = next((nodes[0][0] / 'objects').iterdir())
        target.write_bytes(target.read_bytes() + b'x')
        tip_root, tip_receipt = nodes[-1]
        with self.assertRaises(ValueError) as with_op:
            with counter.cia_validation_operation():
                artifacts._cia_validated_checkpoint(tip_root, tip_receipt)
        with patch.object(counter, '_CIA_OPERATION') as off:
            off.get.return_value = None
            with self.assertRaises(ValueError) as without_op:
                artifacts._cia_validated_checkpoint_impl(tip_root, tip_receipt)
        self.assertEqual(str(with_op.exception), str(without_op.exception))

    # ---- F2: deliberate red: G mutated/deleted, P unchanged, in a SEPARATE operation, must refuse ----
    def test_f2_mutated_ancestor_refused_in_a_later_operation(self):
        nodes = self.chain(3)
        p_root, p_receipt = nodes[-1]
        with counter.cia_validation_operation():
            artifacts._cia_validated_checkpoint(p_root, p_receipt)  # operation 1 validates P and G
        g = next((nodes[1][0] / 'objects').iterdir())
        g.write_bytes(g.read_bytes() + b'x')  # G changes, P is untouched
        with counter.cia_validation_operation():
            with self.assertRaises(ValueError):
                artifacts._cia_validated_checkpoint(p_root, p_receipt)  # operation 2 must re-read G

    def test_f2_deleted_ancestor_refused_in_a_later_operation(self):
        nodes = self.chain(3)
        p_root, p_receipt = nodes[-1]
        with counter.cia_validation_operation():
            artifacts._cia_validated_checkpoint(p_root, p_receipt)
        (nodes[1][0] / 'checkpoint-manifest.json').unlink()
        with counter.cia_validation_operation():
            with self.assertRaises(Exception):
                artifacts._cia_validated_checkpoint(p_root, p_receipt)

    # ---- F3: identity / cap / profile misses cannot hit the same entry ----
    def test_f3_changed_cap_or_digest_misses_the_snapshot_entry(self):
        nodes = self.chain(1)  # ONE zero-step parent: no ancestor reopen is counted (mail 41029)
        root = nodes[-1][0]
        digest = hashlib.sha256((root / 'checkpoint-manifest.json').read_bytes()).hexdigest()
        with counter.cia_validation_operation() as operation:
            counter._cia_parent_snapshot(root, max_restore_payload_bytes=1 << 30, expected_digest=digest)
            self.assertEqual(operation.visits['snapshot_reopened'], 1)
            before = operation.visits['snapshot_reopened']
            with self.assertRaises(ValueError):
                counter._cia_parent_snapshot(root, max_restore_payload_bytes=1, expected_digest=digest)
            with self.assertRaises(ValueError):
                counter._cia_parent_snapshot(root, max_restore_payload_bytes=1 << 30, expected_digest='0' * 64)
            self.assertEqual(operation.visits['snapshot_reopened'], before + 2)

    def test_f3_undigested_call_is_never_cached(self):
        root = self.chain(1)[-1][0]  # zero-step parent: prediction reopened == 2 for two undigested calls
        with counter.cia_validation_operation() as operation:
            for _ in range(2):
                counter._cia_parent_snapshot(root, max_restore_payload_bytes=1 << 30)
            self.assertEqual(operation.visits['snapshot_reopened'], 2)

    def test_f3_other_source_profile_key_never_shares_an_entry(self):
        root = self.chain(1)[-1][0]  # zero-step parent: prediction reopened == 2 (two source profiles, one node)
        digest = hashlib.sha256((root / 'checkpoint-manifest.json').read_bytes()).hexdigest()
        other = counter._cia_operation_snapshot(counter._cia_parent_snapshot_reopened, 'f' * 64)
        with counter.cia_validation_operation() as operation:
            counter._cia_parent_snapshot(root, max_restore_payload_bytes=1 << 30, expected_digest=digest)
            other(root, max_restore_payload_bytes=1 << 30, expected_digest=digest)
            self.assertEqual(operation.visits['snapshot_reopened'], 2)

    # ---- F4: failure leaves nothing reusable ----
    def test_f4_failed_operation_leaves_nothing_for_the_next(self):
        nodes = self.chain(2)
        with self.assertRaises(RuntimeError):
            with counter.cia_validation_operation():
                artifacts._cia_validated_checkpoint(*nodes[-1])
                raise RuntimeError('boom')
        self.assertIsNone(counter._CIA_OPERATION.get())
        with counter.cia_validation_operation() as fresh:
            self.assertEqual((fresh.snapshots, fresh.validated), ({}, set()))

    def test_f4_failed_validation_records_no_entry(self):
        nodes = self.chain(3)
        target = next((nodes[0][0] / 'objects').iterdir())
        target.write_bytes(target.read_bytes() + b'x')
        with counter.cia_validation_operation() as operation:
            with self.assertRaises(ValueError):
                artifacts._cia_validated_checkpoint(*nodes[-1])
            self.assertEqual(operation.validated, set())

    # ---- F6: REAL mixed-profile chain: ancestors published with the historic counter, child with the current one ----
    def test_f6_mixed_profile_chain_records_both_profiles_visited(self):
        historic = self.require_historic()
        self.assertNotEqual(historic.__name__, counter.__name__)
        self.verify_with(historic)
        old_root, _ = self.publish(), None  # genesis, historic counter receipt
        old_root = self.root
        self.extend('h1')  # second historic-counter ancestor
        self.kwargs['pre_publish_verifier'] = self.verifier  # the child uses the current counter
        tip_root, tip_receipt = self.extend('cur1')  # the REAL publication receipt; never a hand-built one
        receipts = [json.loads((r / 'parameter-counter-receipt.json').read_bytes())['counter_sha256']
                    for r in (old_root, old_root.parent / 'h1', tip_root)]
        self.assertEqual(receipts, [HISTORIC, HISTORIC, CURRENT_SHA], 'persisted receipts must bind TWO profiles')
        with counter.cia_validation_operation() as operation:
            artifacts._cia_validated_checkpoint(tip_root, tip_receipt)
            # NO extra snapshot call here: the operation is measured exactly as the validation left it (mail 41047).
            # Profiles are read from the EXISTING snapshot keys: ('snapshot', path, expected_digest, bound, source_sha256).
            # G = old_root (genesis) is the ancestor inspected: its existing keys must carry BOTH profiles.
            g_profiles = {key[4] for key in operation.snapshots if key[1] == str(old_root)}
            self.assertEqual(g_profiles, {HISTORIC, CURRENT_SHA}, 'G must own entries under both profiles')
            profiles = {key[4] for key in operation.snapshots}
        reopened, calls, full = self.counts(operation)
        self.assertLessEqual(reopened, 2 * 2 - 1)  # frozen: raw reopens <= 2d-1 (d=2 -> <= 3)
        self.assertEqual(full, 2)  # profiles are recorded separately, not merged
        # A SEPARATE operation (own counts), after the declared measurement: same ancestor h1 under both profiles.
        h1 = old_root.parent / 'h1'
        h1_digest = hashlib.sha256((h1 / 'checkpoint-manifest.json').read_bytes()).hexdigest()
        with counter.cia_validation_operation() as extra:
            counter._cia_parent_snapshot(h1, max_restore_payload_bytes=1 << 30, expected_digest=h1_digest)
            historic._cia_parent_snapshot(h1, max_restore_payload_bytes=1 << 30, expected_digest=h1_digest)
            self.assertEqual({key[4] for key in extra.snapshots if key[1] == str(h1)}, {HISTORIC, CURRENT_SHA})
        Path(os.environ.get('TAILCURE_MIXED', 'mixed-visits.json')).write_text(json.dumps(
            {'profiles_in_snapshot_keys': sorted(profiles), 'reopened': reopened, 'calls': calls, 'validated_full': full}, indent=1))

    # ---- F7: REDO. EMBER_CIA_PARENT_MEMO=1, two operations on the same P, G changed between them ----
    def test_f7_historic_wrapper_with_memo_env_rereads_and_refuses_in_operation_two(self):
        module = self.require_historic()
        self.assertTrue(hasattr(module, '_cia_parent_snapshot_reopened'))
        nodes = self.chain(3)
        root = nodes[-1][0]
        digest = hashlib.sha256((root / 'checkpoint-manifest.json').read_bytes()).hexdigest()
        with patch.dict(os.environ, {'EMBER_CIA_PARENT_MEMO': '1'}):
            with counter.cia_validation_operation():
                module._cia_parent_snapshot(root, max_restore_payload_bytes=1 << 30, expected_digest=digest)  # the WRAPPER
            g = next((nodes[1][0] / 'objects').iterdir())
            g.write_bytes(g.read_bytes() + b'x')  # G changes, P unchanged
            with counter.cia_validation_operation() as operation2:
                with self.assertRaises(ValueError):
                    module._cia_parent_snapshot(root, max_restore_payload_bytes=1 << 30, expected_digest=digest)
                self.assertGreaterEqual(operation2.visits['snapshot_reopened'], 1)  # re-read, not memo-served


def load_tests(loader, tests, pattern):
    """Only the fixtures named here run; no inherited test_ method can slip in."""
    suite = unittest.TestSuite()
    for name in sorted(n for n in dir(ValidationOperationTests) if n.startswith('test_f')):
        suite.addTest(ValidationOperationTests(name))
    return suite


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=2)
    Path(os.environ.get('TAILCURE_EXECUTED', 'executed-tests.json')).write_text(json.dumps(sorted(set(EXECUTED)), indent=1))
    sys.exit(0 if result.result.wasSuccessful() else 1)
