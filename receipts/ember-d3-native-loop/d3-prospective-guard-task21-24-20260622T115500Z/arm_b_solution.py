from pathlib import Path

for name in [
    "pred_results/pred_gp_uncertainty.json",
    "pred_results/pred_gp_uncertainty_analysis.json",
    "pred_results/pred_integrate_C_O.csv",
    "pred_results/pred_integrate_C_O.png",
    "pred_results/pred_integrate_C_O_summary.txt",
    "pred_results/pred_md.traj",
    "pred_results/pred_rotate_summary.txt"
]:
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('instruction-only placeholder\n', encoding='utf-8')
