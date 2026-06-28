from pathlib import Path

for name in [
    "pred_results/pred_nn.json",
    "pred_results/pred_nn.txt",
    "pred_results/pred_plot_zmat_pes.svg",
    "pred_results/pred_plot_zmat_pes.txt",
    "pred_results/pred_plot_zmat_pes_surface.txt",
    "pred_results/pred_pltp_f13.pdf",
    "pred_results/pred_pltp_f13.txt",
    "pred_results/pred_pltp_vdwtaper.pdf",
    "pred_results/pred_pltp_vdwtaper.txt"
]:
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('instruction-only placeholder\n', encoding='utf-8')
