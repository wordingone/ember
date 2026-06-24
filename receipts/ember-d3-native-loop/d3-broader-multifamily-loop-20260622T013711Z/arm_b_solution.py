from pathlib import Path

for name in [
    "pred_results/pred_demo.json",
    "pred_results/pred_get_reactant_bag_other_reactions.csv",
    "pred_results/pred_illuminate.csv",
    "pred_results/pred_sort_atoms_mol.txt",
    "pred_results/pred_sort_atoms_mol.vasp"
]:
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('instruction-only placeholder\n', encoding='utf-8')
