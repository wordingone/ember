# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Archived-ancestor attestation (lead ruling 82046 (c)) for the CIA chain reopen.

An ancestor at depth >= 2 whose bytes are not held is accepted by content address: manifest-sha chain, a custody record
(server LFS sha256 + size per manifest-declared file), the persisted receipt sha, the counter-history lookup. Depth 0 and 1
stay byte-verified. Conditions under test (82046): (1) every use carries ancestors_attested_by_custody / bytes_reverified
false; (2) refusal on manifest-sha mismatch, server sha mismatch, missing custody record, receipt/counter lookup mismatch,
and an equivalence red (attested and byte paths reach the same verdict on a locally held chain); (3) off unless a custody
directory is named. Fixtures are borrowed from test_issue2163_cia_validation_operation.py (publish a chain, validate its tip).

Custody records are built here from the LOCAL bytes of the published chain, standing in for the server listing; the real
records come from scripts/build_ancestor_custody_v1.py against the HF API."""
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_issue2163_cia_validation_operation import ValidationOperationTests as _Chain  # noqa: E402
from test_issue2163_cia_transaction import artifacts, counter  # noqa: E402

ARCHIVED = ('optimizer-state.pt',)


def git_blob_sha1(data):
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


class AncestorCustodyTests(_Chain):
    """Inherits the chain fixtures; the inherited test_ methods are masked so only the tests below run here."""

    def setUp(self):
        super().setUp()
        self.custody = Path(tempfile.mkdtemp(prefix='custody-'))
        self.addCleanup(shutil.rmtree, self.custody, True)

    # ---- helpers -------------------------------------------------------------------------------------------------
    def record_for(self, root):
        """What the server listing would hold for this published node (built from its held bytes)."""
        raw = (root / 'checkpoint-manifest.json').read_bytes()
        manifest = json.loads(raw)
        sha = hashlib.sha256(raw).hexdigest()
        declared = counter._cia_manifest_declared(root, manifest)
        declared['checkpoint-manifest.json'] = (len(raw), sha)
        files = {}
        for relative, (nbytes, digest) in declared.items():
            small = relative == 'checkpoint-manifest.json' or relative.startswith('expert-index-')
            blob = raw if relative == 'checkpoint-manifest.json' else (root / relative).read_bytes()
            files[relative] = {'server_bytes': nbytes, 'server_lfs_sha256': None if small else digest,
                               'server_blob_id': git_blob_sha1(blob) if small else 'blob-' + digest[:8],
                               'declared_bytes': nbytes, 'declared_sha256': digest}
        return sha, {'schema_version': counter.CUSTODY_SCHEMA, 'manifest_sha256': sha, 'repo_id': 'test/repo',
                     'repo_type': 'dataset', 'server_step_dir': 'checkpoints/test/' + sha[:12], 'files': files}

    def stored(self, nodes, index):
        """(sha, record) as written before the archive step, read back from the custody directory."""
        sha = hashlib.sha256((nodes[index][0] / 'checkpoint-manifest.json').read_bytes()).hexdigest()
        return sha, json.loads((self.custody / ('%s.json' % sha)).read_text(encoding='utf-8'))

    def write_custody(self, nodes, indexes):
        for index in indexes:
            sha, record = self.record_for(nodes[index][0])
            (self.custody / ('%s.json' % sha)).write_text(json.dumps(record, indent=1), encoding='utf-8')

    def archive(self, root):
        """Drop what the real ancestors lost: the per-generation optimizer state."""
        for name in ARCHIVED:
            (root / name).unlink()

    def validate_tip(self, nodes, *, custody=True, force=False, min_depth=None):
        tip_root, tip_receipt = nodes[-1]
        old = counter.ATTEST_MIN_DEPTH
        if min_depth is not None: counter.ATTEST_MIN_DEPTH = min_depth
        try:
            with counter.cia_validation_operation(self.custody if custody else None, _attest_closed_roots=force) as operation:
                result = artifacts._cia_validated_checkpoint(tip_root, tip_receipt)
            return result, operation
        finally:
            counter.ATTEST_MIN_DEPTH = old

    # ---- conditions ----------------------------------------------------------------------------------------------
    def test_equivalence_attested_and_byte_paths_agree_on_a_held_chain(self):
        nodes = self.chain(5)                       # n0 genesis .. n4 tip; n3 is depth 0, n2 depth 1, n1 depth 2, n0 depth 3
        self.write_custody(nodes, range(5))
        byte_result, byte_op = self.validate_tip(nodes, custody=False)
        attested_result, attested_op = self.validate_tip(nodes, custody=True, force=True)
        self.assertEqual(repr(byte_result), repr(attested_result))
        self.assertEqual(sorted(attested_op.attested), [2, 3])
        self.assertEqual(byte_op.attested, {})
        self.assertLess(attested_op.visits['snapshot_reopened'], byte_op.visits['snapshot_reopened'] + 1)

    def test_disclosure_line_and_use_receipt(self):
        nodes = self.chain(5)
        self.write_custody(nodes, range(5))
        _, operation = self.validate_tip(nodes, force=True)
        disclosure = counter.cia_attestation_disclosure(operation)
        self.assertEqual(disclosure['ancestors_attested_by_custody'], [2, 3])
        self.assertIs(disclosure['bytes_reverified'], False)
        rows = [json.loads(line) for line in (self.custody / 'attestation-uses.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertTrue(rows)
        for row in rows:
            self.assertIs(row['bytes_reverified'], False)
            self.assertTrue(row['ancestors_attested_by_custody'])
        self.assertIsNone(counter.cia_attestation_disclosure(self.validate_tip(nodes, custody=False)[1]))

    def test_off_unless_a_custody_directory_is_named(self):
        nodes = self.chain(5)
        self.write_custody(nodes, range(5))
        self.archive(nodes[1][0])
        with self.assertRaises(ValueError) as refused:
            self.validate_tip(nodes, custody=False)
        self.assertIn('closure', str(refused.exception))

    def test_held_roots_take_the_byte_path_even_with_a_custody_record(self):
        nodes = self.chain(5)
        self.write_custody(nodes, range(5))
        _, operation = self.validate_tip(nodes, custody=True, force=False)
        self.assertEqual(operation.attested, {})

    def test_archived_ancestor_is_accepted_by_content_address(self):
        nodes = self.chain(5)
        self.write_custody(nodes, range(5))
        self.archive(nodes[1][0])                    # depth 2: bytes not held
        self.archive(nodes[0][0])                    # depth 3
        result, operation = self.validate_tip(nodes)
        self.assertEqual(sorted(operation.attested), [2, 3])
        self.assertIsNotNone(result)

    def test_depth_zero_and_one_are_never_attested(self):
        nodes = self.chain(5)
        self.write_custody(nodes, range(5))
        self.archive(nodes[3][0])                    # depth 0
        with self.assertRaises(ValueError) as refused:
            self.validate_tip(nodes)
        self.assertIn('closure', str(refused.exception))

    # ---- refusals ------------------------------------------------------------------------------------------------
    def archived_chain(self):
        nodes = self.chain(5)
        self.write_custody(nodes, range(5))
        self.archive(nodes[1][0])
        self.archive(nodes[0][0])
        return nodes

    def test_red_manifest_sha_mismatch_refused(self):
        nodes = self.archived_chain()
        manifest = nodes[1][0] / 'checkpoint-manifest.json'
        manifest.write_bytes(manifest.read_bytes() + b'\n')
        with self.assertRaises(ValueError) as refused:
            self.validate_tip(nodes)
        self.assertIn('digest', str(refused.exception))

    def test_red_server_sha_mismatch_refused(self):
        nodes = self.archived_chain()
        sha, record = self.stored(nodes, 1)
        target = next(name for name in record['files'] if name.startswith('objects/'))
        record['files'][target]['server_lfs_sha256'] = '0' * 64
        (self.custody / ('%s.json' % sha)).write_text(json.dumps(record), encoding='utf-8')
        with self.assertRaises(ValueError) as refused:
            self.validate_tip(nodes)
        self.assertIn('LFS sha256', str(refused.exception))

    def test_red_server_size_mismatch_refused(self):
        nodes = self.archived_chain()
        sha, record = self.stored(nodes, 0)
        record['files']['optimizer-state.pt']['server_bytes'] += 1
        (self.custody / ('%s.json' % sha)).write_text(json.dumps(record), encoding='utf-8')
        with self.assertRaises(ValueError) as refused:
            self.validate_tip(nodes)
        self.assertIn('size', str(refused.exception))

    def test_red_record_missing_a_declared_file_refused(self):
        nodes = self.archived_chain()
        sha, record = self.stored(nodes, 1)
        record['files'].pop('replay-state.pt')
        (self.custody / ('%s.json' % sha)).write_text(json.dumps(record), encoding='utf-8')
        with self.assertRaises(ValueError) as refused:
            self.validate_tip(nodes)
        self.assertIn('file set', str(refused.exception))

    def test_red_missing_custody_record_falls_to_the_byte_path_and_refuses(self):
        nodes = self.archived_chain()
        sha, _ = self.stored(nodes, 1)
        (self.custody / ('%s.json' % sha)).unlink()
        with self.assertRaises(ValueError) as refused:
            self.validate_tip(nodes)
        self.assertIn('closure', str(refused.exception))

    def test_red_missing_record_for_a_deeper_link_refused(self):
        nodes = self.archived_chain()
        sha, _ = self.stored(nodes, 0)
        (self.custody / ('%s.json' % sha)).unlink()
        with self.assertRaises(ValueError) as refused:
            self.validate_tip(nodes)
        self.assertIn('custody record', str(refused.exception))

    def test_red_receipt_edit_refused(self):
        nodes = self.archived_chain()
        receipt = nodes[0][0] / 'parameter-counter-receipt.json'
        data = json.loads(receipt.read_text(encoding='utf-8'))
        data['counter_sha256'] = '1' * 64
        receipt.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.validate_tip(nodes)

    def test_red_counter_not_in_history_refused(self):
        nodes = self.archived_chain()
        with self.assertRaises(ValueError) as refused:
            counter._counter_for('2' * 64)
        self.assertIn('does not keep', str(refused.exception))

    def test_red_receipt_names_another_checkpoint_refused(self):
        nodes = self.archived_chain()
        receipt = nodes[1][0] / 'parameter-counter-receipt.json'
        other = nodes[0][0] / 'parameter-counter-receipt.json'
        receipt.write_bytes(other.read_bytes())
        with self.assertRaises(ValueError):
            self.validate_tip(nodes)

    def test_attested_parent_facts_fail_closed_in_an_unpatched_derive(self):
        facts = counter._AttestedParentFacts()
        with self.assertRaises(KeyError):
            facts['parameters']

    def test_historic_producer_goes_through_the_attested_boundary(self):
        historic = self.require_historic()
        self.verify_with(historic)                   # every receipt in this chain is written by the 7d46fc9d counter
        nodes = self.chain(5)
        self.write_custody(nodes, range(5))
        self.archive(nodes[1][0])
        self.archive(nodes[0][0])
        _, operation = self.validate_tip(nodes)
        self.assertEqual(sorted(operation.attested), [2, 3])


# The inherited ValidationOperationTests methods would re-run here against the new class; mask them.
for _name in [n for n in dir(_Chain) if n.startswith('test_')]:
    if not hasattr(AncestorCustodyTests.__dict__.get(_name), '__call__'):
        setattr(AncestorCustodyTests, _name, None)
del _Chain, _name   # a TestCase imported into this namespace would be collected and re-run

if __name__ == '__main__':
    unittest.main()
