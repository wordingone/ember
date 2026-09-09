"""Exact numerical subject binding; this module grants no dispatch authority."""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import importlib.metadata
import importlib.machinery
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import types

from ember.model.ember_v0_contract import validate_cia_architecture, census
from ember.governance.scripts import training_closure

CONFIG = 'configs/ember-cia-3b.json'
ENTRY = 'tests/test_issue2163_cia_cuda.py'
CONTROL_PATHS = (
    'src/ember/__init__.py',
    'src/ember/governance/scripts/cia_conformance.py',
    'src/ember/governance/scripts/cia_conformance_launch.py',
    'src/ember/governance/scripts/cia_conformance_resources.py',
    'src/ember/governance/scripts/ember_dispatch_token.py',
    'runtime/ember-lab/src/lib.rs',
    'runtime/ember-lab/src/data_catalog.rs',
    'runtime/ember-lab/src/rpc.rs',
    'runtime/ember-lab/src/main.rs',
    'runtime/ember-lab/src/training_verify.rs',
    'runtime/ember-lab/Cargo.toml',
    'runtime/ember-lab/Cargo.lock',
    'src/ember/governance/scripts/verify_authority_conservation.py',
    'src/ember/infrastructure/tools/ember-restart-3b/disk_budget_runner.py',
    'src/ember/governance/scripts/registry_gate.py',
    'src/ember/governance/scripts/gpu_lock_guard.py',
    'src/ember/governance/scripts/owned_process.py',
    'docs/domains/governance/authority/GOAL.md',
    'docs/domains/governance/contracts/registry-dispatch-gate-spec-v0.md',
    'docs/domains/governance/ledgers/technique-registry.jsonl',
    'manifests/training-dependency-closure.json',
    ENTRY,
)


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def fixed_input_values():
    tokens = list(range(1025))
    positions = [(index, 0, 0) for index in range(1025)]
    return tokens, positions


def fixture_identity():
    tokens, positions = fixed_input_values()
    payload = b''.join(struct.pack('<q', value) for value in tokens)
    payload += b''.join(struct.pack('<qqq', *position) for position in positions)
    return {'encoding': 'tokens then positions, signed little-endian int64',
            'tokens': 1025, 'sha256': hashlib.sha256(payload).hexdigest(),
            'seed': 2163, 'checkpoint_ingress': None, 'corpus_ingress': None}


def runtime_identity():
    """Hash installed torch and its active declared distribution dependencies."""
    import torch
    from packaging.requirements import Requirement
    pending = ['torch', 'numpy', 'packaging']
    packages = {}
    while pending:
        requested = pending.pop()
        distribution = importlib.metadata.distribution(requested)
        name = distribution.metadata['Name'].lower().replace('_', '-')
        if name in packages:
            continue
        records = distribution.files
        if not records:
            raise ValueError(f'runtime distribution has no file inventory: {name}')
        files = {}
        for record in records:
            path = Path(distribution.locate_file(record)).resolve(strict=True)
            if not path.is_file():
                raise ValueError(f'runtime member is not a file: {name}/{record}')
            files[str(record)] = file_sha256(path)
        packages[name] = {'version': distribution.version, 'files': files,
                          'origin_root': str(Path(distribution.locate_file('')).resolve())}
        for text in distribution.requires or ():
            requirement = Requirement(text)
            if requirement.marker is None or requirement.marker.evaluate({'extra': ''}):
                pending.append(requirement.name)
    result = {'python_version': sys.version, 'python_executable_sha256': file_sha256(sys.executable),
            'torch_version': str(torch.__version__), 'torch_cuda_build': torch.version.cuda,
            'distributions': packages}
    verify_runtime_origins(result)
    return result


def verify_runtime_origins(identity, modules=None):
    """Loaded code must be a member of the exact distribution whose bytes were hashed."""
    modules = sys.modules if modules is None else modules
    packages = identity['distributions']
    package_map = importlib.metadata.packages_distributions()
    inventories = {
        name: {str((Path(row['origin_root']) / relative).resolve()): digest
               for relative, digest in row['files'].items()}
        for name, row in packages.items()
    }
    for module_name, module in tuple(modules.items()):
        owners = [name.lower().replace('_', '-') for name in package_map.get(module_name.split('.')[0], ())]
        governed = [name for name in owners if name in packages]
        if not governed:
            continue
        origin = getattr(module, '__file__', None)
        if origin is None or (type(module) is not types.ModuleType and not Path(origin).is_absolute()):
            locations = list(vars(module).get('__path__', ()))
            expected_locations = {str((Path(packages[name]['origin_root']) / Path(*module_name.split('.'))).resolve()) for name in governed}
            if locations and all(str(Path(location).resolve()) in expected_locations and any(any(Path(member).is_relative_to(Path(location).resolve()) for member in inventories[name]) for name in governed) for location in locations):
                continue
            # Torch replaces some Python modules with ModuleType subclasses
            # (_VF, ops, classes). Bind their defining methods to that exact
            # Python source, rather than trusting a missing __file__ marker.
            cls = type(module)
            methods = [value for value in vars(cls).values() if isinstance(value, types.FunctionType)]
            owner_name = getattr(cls, '__module__', '')
            if isinstance(module, types.ModuleType) and cls is not types.ModuleType and methods:
                relative_owner = owner_name.replace('.', '/') + '.py'
                candidates = [str((Path(packages[name]['origin_root']) / relative_owner).resolve()) for name in governed]
                if all(method.__module__ == owner_name and str(Path(method.__code__.co_filename).resolve()) in candidates for method in methods):
                    owner_paths = {str(Path(method.__code__.co_filename).resolve()) for method in methods}
                    if all(any(inventories[name].get(path) == file_sha256(path) for name in governed) for path in owner_paths):
                        continue
            # Pybind exports native submodules from a single extension. Require
            # the actual parent export chain and the bound ExtensionFileLoader.
            native_bound = False
            parts = module_name.split('.')
            for depth in range(len(parts) - 1, 0, -1):
                parent_name = '.'.join(parts[:depth])
                parent = modules.get(parent_name)
                if parent is None:
                    continue
                parent_origin = getattr(parent, '__file__', None)
                loader = getattr(parent, '__loader__', None)
                if parent_origin and isinstance(loader, importlib.machinery.ExtensionFileLoader):
                    # Native exports can have an attribute alias (e.g.
                    # compiled_autograd exports a module named autograd_compiler).
                    pending, visited = [parent], set()
                    exported = False
                    while pending and len(visited) < 128:
                        candidate = pending.pop()
                        if id(candidate) in visited:
                            continue
                        visited.add(id(candidate))
                        if candidate is module and getattr(candidate, '__name__', None) == module_name:
                            exported = True
                            break
                        pending.extend(value for value in vars(candidate).values()
                                       if isinstance(value, types.ModuleType)
                                       and getattr(value, '__name__', '').startswith(parent_name + '.'))
                    if not exported:
                        continue
                    path = str(Path(parent_origin).resolve())
                    if Path(loader.path).resolve() != Path(path):
                        break
                    observed = file_sha256(path)
                    native_bound = any(inventories[name].get(path) == observed for name in governed)
                    break
            if native_bound:
                continue
            raise ValueError(f'unbound runtime namespace: {module_name}')
        path = str(Path(origin).resolve())
        observed = file_sha256(path)
        if not any(inventories[name].get(path) == observed for name in governed):
            raise ValueError(f'loaded runtime origin or bytes differ: {module_name}')


def daemon_identity(root):
    from ember.governance.scripts.ember_dispatch_token import (
        _canonical_ember_lab_binary, _canonical_ember_lab_source_sha256)
    binary = _canonical_ember_lab_binary(root)
    source = _canonical_ember_lab_source_sha256(root)
    if binary is None or source is None:
        raise ValueError('current canonical daemon identity is unavailable')
    return {'binary_sha256': file_sha256(binary), 'source_sha256': source}


def build_subject_binding(root):
    root = Path(root).resolve(strict=True)
    config = json.loads((root / CONFIG).read_text(encoding='utf-8'))
    shape = validate_cia_architecture(config)
    population = census(shape).total_unique
    manifest = training_closure.load_manifest(root)
    paths = set(training_closure.declared_paths(manifest)) | set(CONTROL_PATHS)
    sources = {relative: file_sha256(root / relative) for relative in sorted(paths)}
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    revision = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                              check=True, capture_output=True, text=True, timeout=20, **flags).stdout.strip()
    runtime = runtime_identity()
    return {'schema_version': 'ember-registry-numerical-subject-v1',
            'purpose': 'numerical_conformance', 'architecture_revision': config['architecture_revision'],
            'unique_parameters': population, 'source_revision': revision,
            'config_path': CONFIG, 'config_sha256': file_sha256(root / CONFIG),
            'sources': sources, 'fixture': fixture_identity(), 'runtime': runtime,
            'daemon': daemon_identity(root),
            'entry': ENTRY, 'entry_argv': ['--live'], 'applied_updates': 1,
            'trained_token_credit': 0, 'capability_credit': 'none',
            'retained_checkpoint': None, 'serving_generation': None}


def verify_subject_binding(root, binding):
    current = {key: value for key, value in binding.items() if key != 'launch'}
    if canonical(current) != canonical(build_subject_binding(root)):
        raise ValueError('numerical subject identity or scope differs from current consumer')


def verify_loaded_sources(root, binding, modules=None):
    root = Path(root).resolve(strict=True)
    modules = sys.modules if modules is None else modules
    for name, module in tuple(modules.items()):
        if name != 'ember' and not name.startswith('ember.'):
            continue
        origin = getattr(module, '__file__', None)
        expected = root / 'src' / Path(*name.split('.'))
        if origin is None:
            locations = list(getattr(module, '__path__', ()))
            if locations and all(Path(path).resolve() == expected.resolve() for path in locations):
                continue
            raise ValueError(f'foreign or missing namespace: {name}')
        path = Path(origin).resolve()
        if not path.is_relative_to(root / 'src/ember'):
            raise ValueError(f'foreign module origin: {name}')
        if path not in (expected.with_suffix('.py').resolve(), (expected / '__init__.py').resolve()):
            raise ValueError(f'module name does not match source origin: {name}')
        relative = path.relative_to(root).as_posix()
        if binding['sources'].get(relative) != file_sha256(path):
            raise ValueError(f'unbound or changed loaded module bytes: {name}')


def require_current_dispatch(root, binding):
    """Recompute numerical authority in the actual fixed, resource-bound consumer."""
    verify_subject_binding(root, binding)
    from ember.governance.scripts import registry_gate
    from ember.governance.scripts.cia_conformance_launch import verify_envelope
    verify_envelope(Path(root), binding)
    verify_loaded_sources(root, binding)
    goal, outcome = registry_gate.load_goal_binding(Path(root))
    if registry_gate.load_goal_policy(Path(root)).get('authority_only_goal') is True:
        raise ValueError('authority-only goal forbids numerical dispatch')
    config = json.loads((Path(root) / CONFIG).read_text(encoding='utf-8'))
    ok, reason = registry_gate.check_dispatch_authority(config, goal, outcome, purpose='numerical_conformance')
    if not ok:
        raise ValueError(f'numerical dispatch refused: {reason}')
    ok, detail = registry_gate.run_authority_conservation(Path(root))
    if not ok:
        raise ValueError(f'authority conservation refused: {detail}')
    verdict = registry_gate.check(config, registry_gate.load_registry(Path(root) /
        'docs/domains/governance/ledgers/technique-registry.jsonl'), root=Path(root))
    if not verdict['ok']:
        raise ValueError(f'mechanism registry refused: {verdict}')
    print('REGISTRY_NUMERICAL_CONFORMANCE', json.dumps({
        'subject_sha256': hashlib.sha256(canonical(binding)).hexdigest(),
        'goal_id': goal, 'next_executed_outcome': outcome,
        'purpose': 'numerical_conformance', 'mechanisms': verdict,
        'claim': 'dispatch checks only; no model birth or learning credit'}), flush=True)
