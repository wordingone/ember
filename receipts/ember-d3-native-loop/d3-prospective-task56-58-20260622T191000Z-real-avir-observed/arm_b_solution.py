from pathlib import Path

for name in [
    "pred_results/pred_benchmark.csv",
    "pred_results/pred_benchmark_summary.txt",
    "pred_results/pred_run_kancd_demo.csv",
    "pred_results/pred_run_kancd_demo_summary.json"
]:
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('instruction-only placeholder\n', encoding='utf-8')
