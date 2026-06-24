from pathlib import Path

for name in [
    "pred_results/pred_dinfo.txt",
    "pred_results/pred_reconstructed_ES_imagenet.json",
    "pred_results/pred_reconstructed_ES_imagenet.txt"
]:
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('instruction-only placeholder\n', encoding='utf-8')
