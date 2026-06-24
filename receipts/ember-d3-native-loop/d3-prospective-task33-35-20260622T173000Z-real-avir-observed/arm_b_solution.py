from pathlib import Path

for name in [
    "pred_results/pred_plot_acc.txt",
    "pred_results/pred_plot_acc_L100.png"
]:
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('instruction-only placeholder\n', encoding='utf-8')
