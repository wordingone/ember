# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Declared-repeat gate: the receipt behind a `declared-repeat` run certificate (ember-lab run_certificate.rs).

An hour whose extension rows repeat admitted catalog text that earlier hours already trained cannot pass the
C1/C2 fresh-data gate (C2 asks for never-trained text). This gate proves the other claim instead:

* every extension row (ledger rows at and after --parent-rows) maps, span by span, onto admitted catalog train
  membership and touches no protected evaluation object (cia_hour.map_ledger_spans over the catalog export);
* every extension row is labelled repeat_declared with ledger_pass_index >= 1 in the epoch-label sidecar;
* C1 (origin, licence, date wall) is inherited from that catalog admission (c1_basis = catalog-admitted).

The receipt binds the extension rows, the sidecar, the declaration and the catalog export by sha256. The
daemon re-hashes the files and re-checks the sidecar itself; it trusts the membership mapping only through
these receipt bytes. Verdict PASS needs zero unadmitted rows and zero undeclared rows. Exit 0 PASS, 3 REFUSE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3]))
sys.path.insert(0, str(HERE.parents[2] / 'infrastructure' / 'tools' / 'ember-restart-3b'))

from ember.governance.scripts import catalog_train_stream as catalog  # noqa: E402
import cia_hour  # noqa: E402

KIND = 'declared-repeat'


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extension_sha256(ledger_bytes: bytes, parent_rows: int) -> str:
    """sha256 over the ledger lines at and after parent_rows, each with its newline (as the daemon computes)."""
    lines = [line for line in ledger_bytes.split(b'\n') if line]
    return hashlib.sha256(b''.join(line + b'\n' for line in lines[parent_rows:])).hexdigest()


def gate(*, ledger: Path, sidecar: Path, declaration: Path, export_path: Path, export_sha256: str,
         dataset_ids: list[str], tokenizer_sha256: str, parent_rows: int) -> dict:
    if sha256(export_path) != export_sha256:
        raise ValueError('catalog export bytes do not match --catalog-export-sha256')
    export = json.loads(export_path.read_text(encoding='utf-8'))
    admitted, _ = catalog._admitted_train_windows(export, dataset_ids, tokenizer_sha256)
    membership = {name: {digest for digest, _ in rows} for name, rows in admitted.items()}
    protected = set().union(*(h for n, h in catalog.leakage_sets(export).items() if not n.startswith('_')))
    rows = catalog.read_shard_ledger(ledger)
    labels = json.loads(sidecar.read_text(encoding='utf-8'))['rows']
    if not 0 <= parent_rows < len(rows) or len(labels) != len(rows):
        raise ValueError('parent_rows / sidecar row count do not fit the ledger')
    unadmitted, undeclared, spans = [], [], 0
    for index in range(parent_rows, len(rows)):
        try:
            spans += cia_hour.map_ledger_spans([rows[index]], membership, protected)['spans_total']
        except ValueError as error:
            unadmitted.append({'row': index, 'reason': str(error)})
        label = labels[index]
        if label.get('repeat_declared') is not True or not isinstance(label.get('ledger_pass_index'), int) \
                or label['ledger_pass_index'] < 1:
            undeclared.append(index)
    passed = not unadmitted and not undeclared
    return {
        'kind': KIND,
        'verdict': 'PASS' if passed else 'REFUSE',
        'c1_basis': 'catalog-admitted',
        'parent_rows': parent_rows,
        'rows_checked': len(rows) - parent_rows,
        'unadmitted_rows': len(unadmitted),
        'unadmitted_sample': unadmitted[:5],
        'undeclared_rows': len(undeclared),
        'undeclared_sample': undeclared[:5],
        'spans_mapped': spans,
        'ledger_sha256': sha256(ledger),
        'extension_ledger_sha256': extension_sha256(ledger.read_bytes(), parent_rows),
        'sidecar_sha256': sha256(sidecar),
        'declaration_sha256': sha256(declaration),
        'catalog_export_sha256': export_sha256,
        'dataset_ids': dataset_ids,
        'tokenizer_sha256': tokenizer_sha256,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--ledger', type=Path, required=True)
    p.add_argument('--sidecar', type=Path, required=True)
    p.add_argument('--declaration', type=Path, required=True)
    p.add_argument('--parent-rows', type=int, required=True)
    p.add_argument('--catalog-export', type=Path, required=True)
    p.add_argument('--catalog-export-sha256', required=True)
    p.add_argument('--dataset-ids', nargs='+', required=True)
    p.add_argument('--tokenizer-sha256', required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(argv)
    receipt = gate(ledger=a.ledger, sidecar=a.sidecar, declaration=a.declaration, export_path=a.catalog_export,
                   export_sha256=a.catalog_export_sha256, dataset_ids=a.dataset_ids,
                   tokenizer_sha256=a.tokenizer_sha256, parent_rows=a.parent_rows)
    if a.out.exists():
        raise SystemExit('refusing to overwrite an existing receipt')
    a.out.write_text(json.dumps(receipt, indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({k: receipt[k] for k in ('verdict', 'rows_checked', 'unadmitted_rows', 'undeclared_rows')}))
    return 0 if receipt['verdict'] == 'PASS' else 3


if __name__ == '__main__':
    raise SystemExit(main())
