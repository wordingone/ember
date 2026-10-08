# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The MMMU evaluator measures whether the image projection was trained on the evaluated checkpoint itself.

It used to read `'embed_image' in cia_step_runner.py` and published that string test as a property of the checkpoint.
The runner now embeds images, so the string test answers true for every checkpoint, including one whose projection never
moved. These tests pin the measured form: the head's own `image.weight` against the lineage root's.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
SUBJECT_PATH = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b/mmmu_cia_evaluation.py'
SPEC = importlib.util.spec_from_file_location('bound_checkout_mmmu_cia_evaluation', SUBJECT_PATH)
evaluation = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = evaluation
SPEC.loader.exec_module(evaluation)

CORE = {'sha256': 'c' * 64, 'bytes': 1, 'architecture_sha256': 'a' * 64}
GENESIS = torch.zeros(4, 3, dtype=torch.bfloat16)


class Artifacts:
    """Stands in for checkpoint_artifacts.read_cia_core_object; records what it was asked to read."""

    def __init__(self, cores):
        self.cores, self.reads = cores, []

    def read_cia_core_object(self, root, *, record, architecture_config):
        self.reads.append((Path(root).name, record['sha256']))
        if Path(root).name not in self.cores:
            raise ValueError('core digest mismatch')
        return dict(self.cores[Path(root).name])


def checkpoint(tmp_path, name, parent=None, core=CORE):
    """The real manifest shape: the parent lives in `lineage`, bound by the parent manifest's digest; a root has none."""
    directory = tmp_path / name
    directory.mkdir()
    manifest = {'core': core, 'architecture_config': {'model': {}}}
    if parent is not None:
        parent_raw = (tmp_path / parent / 'checkpoint-manifest.json').read_bytes()
        manifest['lineage'] = {'parent_checkpoint': str(tmp_path / parent),
                               'parent_manifest_sha256': hashlib.sha256(parent_raw).hexdigest()}
    (directory / 'checkpoint-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return directory


def lineage(tmp_path, depth=3):
    checkpoint(tmp_path, 'c0')
    for k in range(1, depth + 1):
        checkpoint(tmp_path, f'c{k}', parent=f'c{k - 1}')
    return tmp_path / f'c{depth}'


def test_a_moved_projection_reads_trained_against_the_lineage_root(tmp_path):
    head = lineage(tmp_path)
    moved = GENESIS.clone(); moved[0, 0] = 0.5
    artifacts = Artifacts({'c0': {'image.weight': GENESIS}})
    source = evaluation.image_projection_source(artifacts, head, moved)
    assert source['trained'] is True and source['lineage_depth'] == 3 and source['changed_elements'] == 1
    assert source['lineage_root'] == str((tmp_path / 'c0').resolve()) and source['lineage_root_core_sha256'] == 'c' * 64
    assert artifacts.reads == [('c0', 'c' * 64)]   # only the root core is read, by its pinned record


def test_an_unmoved_projection_reads_untrained_even_though_the_runner_embeds_images(tmp_path):
    # The deliberate red for the old rule: the runner source does call embed_image, and the head never moved.
    runner = (ROOT / 'src/ember/infrastructure/tools/ember-restart-3b/cia_step_runner.py').read_text(encoding='utf-8')
    assert 'embed_image' in runner   # the old string test would have said True here
    source = evaluation.image_projection_source(Artifacts({'c0': {'image.weight': GENESIS}}), lineage(tmp_path), GENESIS.clone())
    assert source['trained'] is False and source['max_abs_difference'] == 0.0


def test_the_root_itself_reads_untrained_without_a_core_read(tmp_path):
    root = checkpoint(tmp_path, 'c0')
    artifacts = Artifacts({})
    source = evaluation.image_projection_source(artifacts, root, GENESIS.clone())
    assert source['trained'] is False and source['lineage_depth'] == 0 and artifacts.reads == []


def test_the_walk_reaches_the_root_through_the_nested_lineage_record(tmp_path):
    # The real manifests carry the parent under `lineage`, not at the top level; a top-level-only walk reads every
    # head as its own root and calls it untrained (caught on the real H34 head, depth 0).
    root, manifest, root_sha256, depth = evaluation.lineage_root(lineage(tmp_path, depth=4))
    assert depth == 4 and root == tmp_path / 'c0' and 'lineage' not in manifest
    assert root_sha256 == hashlib.sha256((tmp_path / 'c0' / 'checkpoint-manifest.json').read_bytes()).hexdigest()


def test_the_evaluator_no_longer_reads_runner_source_text():
    text = SUBJECT_PATH.read_text(encoding='utf-8')
    assert "'embed_image' in runner" not in text and 'cia_step_runner.py' not in text.split('def repository', 1)[1].split('\ndef ', 1)[0]


@pytest.mark.parametrize('case', ['head_missing', 'root_missing', 'root_unreadable', 'shape', 'dtype', 'parent_digest',
                                  'broken_parent', 'malformed_lineage', 'top_level_parent', 'manifest_not_object',
                                  'too_deep'])
def test_every_unmeasurable_case_refuses(tmp_path, case):
    head, projection, cores = lineage(tmp_path, depth=2), GENESIS.clone(), {'c0': {'image.weight': GENESIS}}
    if case == 'head_missing':
        projection = None
    elif case == 'root_missing':
        cores = {'c0': {'other.weight': GENESIS}}
    elif case == 'root_unreadable':
        cores = {}
    elif case == 'shape':
        projection = torch.zeros(4, 4, dtype=torch.bfloat16)
    elif case == 'dtype':
        projection = torch.zeros(4, 3, dtype=torch.float32)
    elif case == 'parent_digest':
        # a root swapped after its child was written: same path, different bytes
        (tmp_path / 'c0' / 'checkpoint-manifest.json').write_text(json.dumps({'core': CORE, 'swapped': True}),
                                                                   encoding='utf-8')
    elif case == 'broken_parent':
        (tmp_path / 'c0' / 'checkpoint-manifest.json').unlink()
    elif case == 'malformed_lineage':
        (head / 'checkpoint-manifest.json').write_text(json.dumps({'lineage': {'parent_checkpoint': 7}}), encoding='utf-8')
    elif case == 'top_level_parent':
        (head / 'checkpoint-manifest.json').write_text(json.dumps({'parent_checkpoint': str(tmp_path / 'c1')}),
                                                       encoding='utf-8')
    elif case == 'manifest_not_object':
        (head / 'checkpoint-manifest.json').write_text('[]', encoding='utf-8')
    elif case == 'too_deep':
        deep = tmp_path / 'deep'
        deep.mkdir()
        head = lineage(deep, depth=evaluation.LINEAGE_DEPTH_LIMIT + 1)
    with pytest.raises(evaluation.ProducerRefusal) as caught:
        evaluation.image_projection_source(Artifacts(cores), head, projection)
    assert caught.value.token == 'PROJECTION_SOURCE'
