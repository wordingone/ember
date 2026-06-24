from pathlib import Path

for name in [
    "pred_results/pred_dkt_forget_dataloader.json",
    "pred_results/pred_dkt_forget_dataloader_qtest.json",
    "pred_results/pred_que_data_loader_promptkt.json"
]:
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('instruction-only placeholder\n', encoding='utf-8')
