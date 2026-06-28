from pathlib import Path

for name in [
    "pred_results/POSCAR.mat",
    "pred_results/pred_zmat_match.txt",
    "pred_results/zmat_output.txt"
]:
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('instruction-only placeholder\n', encoding='utf-8')
