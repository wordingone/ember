from pathlib import Path

for name in [
    "pred_results/pred_Fig13(b)-Performance-of-channel-estimation-SNR.pdf",
    "pred_results/pred_ParaLearn.txt"
]:
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('instruction-only placeholder\n', encoding='utf-8')
