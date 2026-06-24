from pathlib import Path

for name in [
    "pred_results/pred_add_cores_to_linker.csv",
    "pred_results/pred_boxmodel.txt"
]:
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('instruction-only placeholder\n', encoding='utf-8')
