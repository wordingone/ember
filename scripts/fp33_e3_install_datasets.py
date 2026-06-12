"""fp33_e3_install_datasets.py — install datasets in csi-eval venv.

datasets is not inherited via --system-site-packages (it lives in
csi-train venv, not the base Python). Install it directly in csi-eval.

Runs under csi-train Python; installs into csi-eval via pip.
"""
from __future__ import annotations

import subprocess
import sys

VENV_PIP = "/mnt/c/Users/Admin/.venvs/csi-eval/bin/pip"


def main():
    print(f"[DATASETS] base Python: {sys.executable}", flush=True)
    r = subprocess.run(
        [VENV_PIP, "install", "--upgrade", "datasets"],
        capture_output=False, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"pip install datasets failed (rc={r.returncode})")

    # verify
    check = subprocess.run(
        ["/mnt/c/Users/Admin/.venvs/csi-eval/bin/python", "-c",
         "from datasets import load_dataset; print('datasets OK')"],
        capture_output=True, text=True,
    )
    print(f"[DATASETS] verify: {check.stdout.strip()}", flush=True)
    if check.returncode != 0:
        print(f"[DATASETS] verify stderr: {check.stderr.strip()}", flush=True)
        raise RuntimeError("datasets import failed after install")

    print("FP33_E3_INSTALL_DATASETS_DONE", flush=True)


if __name__ == "__main__":
    main()
