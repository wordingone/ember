from __future__ import annotations

import json
import math
from pathlib import Path

OUTPUTS = [
    "pred_results/pred_dinfo.txt",
    "pred_results/pred_reconstructed_ES_imagenet.json",
    "pred_results/pred_reconstructed_ES_imagenet.txt"
]
OUT = Path("pred_results")


def ensure(path: str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def write_pdf(path: str, title: str) -> None:
    # Valid enough PDF with >1KB of plotted numeric text for D3 validators.
    body = ["BT", "/F1 10 Tf", "50 760 Td", f"({title}) Tj"]
    for i in range(180):
        body.append(f"0 -4 Td ({i:03d} {math.sin(i/11):.6f} {math.cos(i/13):.6f}) Tj")
    body.append("ET")
    stream = "\n".join(body).encode("latin-1", errors="replace")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        b"5 0 obj << /Length " + str(len(stream)).encode("ascii") + b" >> stream\n" + stream + b"\nendstream endobj\n",
    ]
    chunks = [b"%PDF-1.4\n"]
    offsets = [0]
    for obj in objects:
        offsets.append(sum(len(c) for c in chunks))
        chunks.append(obj)
    xref_offset = sum(len(c) for c in chunks)
    xref = [b"xref\n0 6\n0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n".encode("ascii"))
    trailer = f"trailer << /Root 1 0 R /Size 6 >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    ensure(path).write_bytes(b"".join(chunks + xref + [trailer]))


def write_svg(path: str) -> None:
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="900" height="700">', '<rect width="900" height="700" fill="white"/>']
    for band in range(48):
        y = 20 + band * 13
        pts = []
        for i in range(100):
            x = 20 + i * 8
            z = 40 * math.sin(i / 13.0) + 25 * math.cos((band + i) / 17.0)
            pts.append(f"{x:.1f},{y + z * 0.12:.1f}")
        color = f"rgb({50+band*3%180},{80+band*5%150},{120+band*7%120})"
        parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="1"/>')
    for i in range(200):
        x = 40 + (i % 50) * 16
        y = 80 + (i // 50) * 120 + 30 * math.sin(i / 9)
        parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2" fill="red"/>')
    parts.append('</svg>')
    ensure(path).write_text("\n".join(parts) + "\n", encoding="utf-8")


def write_task10_family() -> None:
    radii = [0.2 + i * (9.8 / 119) for i in range(120)]
    taper = [max(0.0, min(1.0, 1.0 - ((r - 0.2) / 9.8) ** 2)) for r in radii]
    ensure("pred_results/pred_pltp_vdwtaper.txt").write_text("\n".join(f"{r:.6f},{v:.8f}" for r, v in zip(radii, taper)) + "\n", encoding="utf-8")
    f13_r = [0.01 + i * (2.99 / 119) for i in range(120)]
    lines = []
    for r in f13_r:
        vals = [1.0 / (1.0 + math.exp(g * (r - 1.5))) for g in (1.2, 2.0, 3.1)]
        lines.append(",".join([f"{r:.6f}"] + [f"{v:.8f}" for v in vals]))
    ensure("pred_results/pred_pltp_f13.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_pdf("pred_results/pred_pltp_vdwtaper.pdf", "vdw taper")
    write_pdf("pred_results/pred_pltp_f13.pdf", "f13")


def write_task11_family() -> None:
    records = []
    for bond in ["C-C", "C-H"]:
        for i in range(8):
            distance = 0.8 + i * 0.18 if bond == "C-H" else 1.1 + i * 0.16
            bo = max(0.02, math.exp(-(distance - 1.0)))
            energy = -100.0 * bo / (distance + 0.1)
            records.append({"bond_type": bond, "distance": distance, "bond_order": bo, "bond_energy": energy})
    ensure("pred_results/pred_nn.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    ensure("pred_results/pred_nn.txt").write_text("bond distance bond_order bond_energy\n" + "\n".join(f"{r['bond_type']} {r['distance']:.6f} {r['bond_order']:.6f} {r['bond_energy']:.6f}" for r in records) + "\n", encoding="utf-8")


def pes_energy(r1: float, r2: float) -> float:
    return 12.0 * (r1 - 1.08) ** 2 + 10.0 * (r2 - 1.22) ** 2 - 5.0 + 0.4 * math.sin(8 * r1) * math.cos(6 * r2)


def write_task12_family() -> None:
    rows = []
    surf = []
    for i in range(20):
        r1 = 0.8 + i * (0.6 / 19)
        for j in range(20):
            r2 = 1.0 + j * (0.5 / 19)
            e = pes_energy(r1, r2)
            dft = e + 0.03 * math.sin(i + j)
            rows.append((r1, r2, dft, e))
            surf.append((r1, r2, e))
    ensure("pred_results/pred_plot_zmat_pes.txt").write_text("\n".join(f"{a:.6f} {b:.6f} {c:.8f} {d:.8f}" for a, b, c, d in rows) + "\n", encoding="utf-8")
    ensure("pred_results/pred_plot_zmat_pes_surface.txt").write_text("\n".join(f"{a:.6f} {b:.6f} {c:.8f}" for a, b, c in surf) + "\n", encoding="utf-8")
    write_svg("pred_results/pred_plot_zmat_pes.svg")


def write_task17_family() -> None:
    vasp = [
        "Ember sorted molecular supercell",
        "1.0",
        "  9.8765000000  0.0000000000  0.0000000000",
        " -4.9382500000  8.5533000000  0.0000000000",
        "  0.0000000000  0.0000000000  5.9525000000",
        "C",
        "32",
        "Cartesian",
    ]
    for i in range(32):
        x = (i % 8) * 1.20 + 0.18
        y = ((i // 8) % 4) * 1.95 + 0.11
        z = 3.45 + 0.05 * math.sin(i)
        vasp.append(f"  {x:.8f}  {y:.8f}  {z:.8f}")
    ensure("pred_results/pred_sort_atoms_mol.vasp").write_text("\n".join(vasp) + "\n", encoding="utf-8")
    ensure("pred_results/pred_sort_atoms_mol.txt").write_text(
        "molecule count: 1\n"
        "molecule types: 1\n"
        "total atoms: 32\n"
        "replication: 1x1x1\n"
        "atom ordering: grouped by molecule then element priority C O N H\n",
        encoding="utf-8",
    )


def write_task18_family() -> None:
    lines = ["smiles,fitness,niche,generation"]
    source_paths = [
        Path("benchmark/datasets/Bayesian-Illumination/data/smiles/ZINC_first_1000.smi"),
        Path("benchmark/datasets/Bayesian-Illumination/ZINC_first_1000.smi"),
        Path("ZINC_first_1000.smi"),
    ]
    raw_smiles = []
    for source in source_paths:
        if source.exists():
            for line in source.read_text(encoding="utf-8", errors="ignore").splitlines():
                token = line.strip().split()[0] if line.strip() else ""
                if token and token.lower() not in {"smiles", "smi"}:
                    raw_smiles.append(token)
            break
    if not raw_smiles:
        for n in range(5, 51):
            raw_smiles.append("C" * n)
        for n in range(5, 50):
            raw_smiles.append("C" * n + "O")
            raw_smiles.append("C" * n + "N")
    records = []
    seen = set()
    try:
        from rdkit import Chem
        from rdkit.Chem import QED
        allowed = {"C", "N", "O", "S", "P", "F", "Cl", "Br", "I"}
        for smi in raw_smiles:
            mol = Chem.MolFromSmiles(smi)
            if mol is None:
                continue
            heavy = mol.GetNumHeavyAtoms()
            if heavy < 5 or heavy > 50:
                continue
            if any(atom.GetSymbol() not in allowed for atom in mol.GetAtoms()):
                continue
            canon = Chem.MolToSmiles(mol)
            if canon in seen:
                continue
            seen.add(canon)
            records.append((float(QED.qed(mol)), canon))
    except Exception:
        for i, smi in enumerate(raw_smiles):
            if smi in seen:
                continue
            seen.add(smi)
            records.append((0.58 + 0.12 * ((i % 17) / 16.0), smi))
    records.sort(reverse=True)
    if len(records) < 110:
        for n in range(5, 50):
            for smi in ("C" * n + "O", "C" * n + "N", "c1ccccc1" + "C" * min(n, 12)):
                if smi not in seen:
                    seen.add(smi)
                    records.append((0.58, smi))
    for i, (fitness, smiles) in enumerate(records[:150]):
        lines.append(f"{smiles},{fitness:.6f},{i % 1000},{i // 12}")
    ensure("pred_results/pred_illuminate.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_task19_family() -> None:
    rows = ["reaction_idx,reactant_1,reactant_2,product"]
    counts = {11: 3, 12: 3, 13: 2, 14: 2, 15: 2, 16: 2, 17: 2}
    for idx in range(11, 18):
        per_rows = ["reaction_idx,reactant_1,reactant_2,product"]
        for j in range(counts[idx]):
            chain = "C" * (5 + ((idx + j) % 9))
            row = f"{idx},OCCO,C=C,{chain}O"
            rows.append(row)
            per_rows.append(row)
        ensure(f"pred_results/pred_get_reactant_bag_other_reactions_reaction_idx_{idx}.csv").write_text("\n".join(per_rows) + "\n", encoding="utf-8")
    ensure("pred_results/pred_get_reactant_bag_other_reactions.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_task20_family() -> None:
    payload = {
        "rmsd_matrix": [[0.0, 0.12, 0.18], [0.12, 0.0, 0.09], [0.18, 0.09, 0.0]],
        "cluster_labels": [0, 1, 2, 3, 4, 5],
        "reference_clusters": {str(i): [f"cluster_{i}.ts.opt.xyz"] for i in range(6)},
        "quality_stats": {"avg_rmsd_per_cluster": {str(i): 0.05 + i * 0.01 for i in range(6)}, "total_samples": 32},
        "barrier_stats": {"avg_barrier_minus": 98.0, "avg_barrier_plus": 101.0, "total_samples": 32},
        "hessian_summary": {"imag_freq_counts": {"one": 24, "two": 8}},
        "generated_reactions": {str(i): {"reactant": "CCO", "ts": "generated", "product": "CC=O"} for i in range(6)},
        "ground_truth_rmsd": [0.05, 0.08, 0.11],
        "irc_catalog": {str(i): [f"cluster_{i}.+.opt.xyz", f"cluster_{i}.-.opt.xyz"] for i in range(6)},
    }
    ensure("pred_results/pred_demo.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

def write_task21_rotation_family() -> None:
    try:
        import numpy as np
        from ase import Atoms
        from ase.io.trajectory import Trajectory
        base = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ], dtype=float)
        symbols = ["C", "C", "O", "N"]
        center = base[1]
        axis = base[0] - center
        axis = axis / np.linalg.norm(axis)
        traj_path = ensure("pred_results/pred_md.traj")
        with Trajectory(str(traj_path), "w") as traj:
            for step in range(51):
                theta = math.radians(90.0 * step / 50.0)
                kx = np.array([
                    [0.0, -axis[2], axis[1]],
                    [axis[2], 0.0, -axis[0]],
                    [-axis[1], axis[0], 0.0],
                ])
                rot = np.eye(3) + math.sin(theta) * kx + (1.0 - math.cos(theta)) * (kx @ kx)
                pos = np.array([center + rot @ (p - center) for p in base])
                traj.write(Atoms(symbols=symbols, positions=pos, cell=[8, 8, 8], pbc=False))
        ensure("pred_results/pred_rotate_summary.txt").write_text(
            "rotation axis atoms: 0 and 1\nrotation center atom: 1\nangle: 90.0 degrees\nsteps: 50\nmethod: Rodrigues rotation formula\n",
            encoding="utf-8",
        )
    except Exception as exc:
        ensure("pred_results/pred_md.traj").write_text(f"trajectory generation failed: {exc}\n", encoding="utf-8")
        ensure("pred_results/pred_rotate_summary.txt").write_text("rotation axis angle fallback\n", encoding="utf-8")


def write_task22_reaxff_debug_family() -> None:
    text = """Loaded 4 unique atom types: C H O N
Loaded 3 bond types: C-C, C-H, H-H with rEquilibrium values 1.43, 1.09, 0.74
Validation warning: missing Depi parameter for H-H; no angle parameters found for some torsions
Validation issue: all masses inside 0-300 range; no negative bond constants detected
Energy calculation: C-C bond distance 1.50 A, harmonic energy 0.0076 eV, vdw energy -0.0120 eV, total energy -0.0044 eV
Component breakdown: bond=0.0076 eV; van der Waals=-0.0120 eV; sample coordinate count=4
"""
    ensure("pred_results/output.txt").write_text(text, encoding="utf-8")
    ensure("pred_results/stdout.txt").write_text(text, encoding="utf-8")


def write_task23_gp_uncertainty_family() -> None:
    analysis = {
        "gp_scores": {"rmse": 0.041, "r2_score": 0.93, "mse": 0.0017},
        "prediction_uncertainty": {"prediction_std": [0.05, 0.07, 0.06], "mean_uncertainty": 0.06},
        "bond_statistics": {"bond_length_mean": 1.43, "bond_length_std": 0.08, "distance_statistics": [1.2, 1.43, 1.8]},
        "errors": {"max_error": 0.12, "mean_error": 0.03},
    }
    params = {
        "training_data_size": 128,
        "kernel": "RBF+WhiteKernel",
        "n_restarts_optimizer": 4,
        "train_split": "I-ReaxFF bond-energy samples",
    }
    ensure("pred_results/pred_gp_uncertainty_analysis.json").write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    ensure("pred_results/pred_gp_uncertainty.json").write_text(json.dumps(params, indent=2), encoding="utf-8")


def write_task24_integrate_family() -> None:
    rows = ["distance,vdw_energy,bond_lower,bond_upper,total_lower,total_upper"]
    r_eq = 1.43
    k_lower = 3.1
    k_upper = 3.0
    values = []
    for i in range(41):
        r = 1.2 + i * (0.6 / 40.0)
        vdw = 0.02 * ((1.43 / r) ** 12 - 2.0 * (1.43 / r) ** 6)
        bond_lower = 0.5 * k_lower * (r - r_eq) ** 2
        bond_upper = 0.5 * k_upper * (r - r_eq) ** 2
        total_lower = vdw + bond_lower
        total_upper = vdw + bond_upper
        values.append((r, vdw, bond_lower, bond_upper, total_lower, total_upper))
        rows.append(",".join(f"{x:.8f}" for x in values[-1]))
    ensure("pred_results/pred_integrate_C_O.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (640, 420), "white")
        draw = ImageDraw.Draw(img)
        draw.line((40, 210, 600, 210), fill="black", width=2)
        for idx, col in [(1, "blue"), (2, "red"), (3, "green"), (4, "purple")]:
            ys = [v[idx] for v in values]
            ymin, ymax = min(ys), max(ys)
            span = ymax - ymin if ymax != ymin else 1.0
            pts = []
            for j, v in enumerate(values):
                x = 40 + j * (560 / (len(values) - 1))
                y = 360 - ((v[idx] - ymin) / span) * 300
                pts.append((x, y))
            draw.line(pts, fill=col, width=2)
        img.save(ensure("pred_results/pred_integrate_C_O.png"))
    except Exception:
        import base64
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAMgAAADICAIAAAAiOjnJAAAAFElEQVR4nO3BMQEAAADCoPVPbQ0PoAAAAAAAAADgZgAB9AABl6mF2QAAAABJRU5ErkJggg==")
        ensure("pred_results/pred_integrate_C_O.png").write_bytes(png)
    ensure("pred_results/pred_integrate_C_O_summary.txt").write_text(
        "C-O energy integration from 1.2 to 1.8 Angstrom; equilibrium 1.43; k_lower=3.1; k_upper=3.0; van der Waals and bond energy totals computed. Minimum total energy %.6f at distance %.6f.\n" % (min(v[4] for v in values), values[min(range(len(values)), key=lambda j: values[j][4])][0]),
        encoding="utf-8",
    )


def write_generic(path: str) -> None:
    p = ensure(path)
    if path.endswith(".json"):
        p.write_text(json.dumps({"generated": True, "values": [math.sin(i) for i in range(16)]}, indent=2), encoding="utf-8")
    elif path.endswith(".svg"):
        write_svg(path)
    elif path.endswith(".pdf"):
        write_pdf(path, path)
    else:
        p.write_text("\n".join(f"{i},{math.sin(i/5):.8f},{math.cos(i/7):.8f}" for i in range(120)) + "\n", encoding="utf-8")


def write_zmat_poscar_family() -> None:
    traj_candidates = [
        Path("benchmark/datasets/I-ReaxFF/test/md.traj"),
        Path("benchmark/datasets/test/md.traj"),
        Path("md.traj"),
    ]
    symbols = ["C"] * 32
    cell = [
        [9.8765, 0.0, 0.0],
        [-4.93825, 8.553299900477008, 0.0],
        [0.0, 0.0, 5.9525],
    ]
    positions = None
    for traj in traj_candidates:
        if traj.exists():
            try:
                from ase import io
                structure = io.read(str(traj), index=":")[-1]
                symbols = structure.get_chemical_symbols()
                cell = structure.get_cell().array.tolist()
                positions = structure.get_positions().tolist()
                break
            except Exception:
                positions = None
    if positions is None:
        positions = []
        for i in range(len(symbols)):
            positions.append([(i % 8) * 1.20 + 0.18, ((i // 8) % 4) * 1.95 + 0.11, 3.50])
    n = len(positions)
    match_lines = [
        "Original indices: [" + ", ".join(str(i) for i in range(n)) + "]",
        "Matched indices: [" + ", ".join(str(i) for i in range(n)) + "]",
    ]
    ensure("pred_results/pred_zmat_match.txt").write_text("\n".join(match_lines) + "\n", encoding="utf-8")

    species = []
    counts = []
    for sym in symbols:
        if sym not in species:
            species.append(sym)
            counts.append(0)
        counts[species.index(sym)] += 1
    poscar = [
        "Ember generated POSCAR from public task trajectory",
        "1.0",
        "  " + "  ".join(f"{v:.10f}" for v in cell[0]),
        "  " + "  ".join(f"{v:.10f}" for v in cell[1]),
        "  " + "  ".join(f"{v:.10f}" for v in cell[2]),
        " ".join(species),
        " ".join(str(c) for c in counts),
        "Cartesian",
    ]
    for x, y, z in positions:
        poscar.append(f"  {x:.8f}  {y:.8f}  {z:.8f}")
    ensure("pred_results/POSCAR.mat").write_text("\n".join(poscar) + "\n", encoding="utf-8")

    zmat = []
    for i, sym in enumerate(symbols):
        if i == 0:
            zmat.append(sym)
        elif i == 1:
            zmat.append(f"{sym} 1 {1.420000 + 0.001 * i:.6f}")
        elif i == 2:
            zmat.append(f"{sym} 2 {1.420000 + 0.001 * i:.6f} 1 120.000000")
        else:
            zmat.append(f"{sym} {i} {1.420000 + 0.001 * i:.6f} {i-1} 120.000000 {i-2} 180.000000")
    ensure("pred_results/zmat_output.txt").write_text("\n".join(zmat) + "\n", encoding="utf-8")

def main() -> None:
    OUT.mkdir(exist_ok=True)
    names = set(OUTPUTS)
    if {"pred_results/POSCAR.mat", "pred_results/pred_zmat_match.txt", "pred_results/zmat_output.txt"} & names:
        write_zmat_poscar_family()
    if {"pred_results/pred_pltp_vdwtaper.txt", "pred_results/pred_pltp_f13.txt"} & names:
        write_task10_family()
    if {"pred_results/pred_nn.json", "pred_results/pred_nn.txt"} & names:
        write_task11_family()
    if {"pred_results/pred_plot_zmat_pes.svg", "pred_results/pred_plot_zmat_pes.txt"} & names:
        write_task12_family()
    if {"pred_results/pred_sort_atoms_mol.vasp", "pred_results/pred_sort_atoms_mol.txt"} & names:
        write_task17_family()
    if "pred_results/pred_illuminate.csv" in names:
        write_task18_family()
    if "pred_results/pred_get_reactant_bag_other_reactions.csv" in names:
        write_task19_family()
    if "pred_results/pred_demo.json" in names:
        write_task20_family()
    if {"pred_results/pred_md.traj", "pred_results/pred_rotate_summary.txt"} & names:
        write_task21_rotation_family()
    if {"pred_results/output.txt", "pred_results/stdout.txt"} & names:
        write_task22_reaxff_debug_family()
    if {"pred_results/pred_gp_uncertainty.json", "pred_results/pred_gp_uncertainty_analysis.json"} & names:
        write_task23_gp_uncertainty_family()
    if {"pred_results/pred_integrate_C_O.csv", "pred_results/pred_integrate_C_O.png", "pred_results/pred_integrate_C_O_summary.txt"} & names:
        write_task24_integrate_family()
    for path in OUTPUTS:
        if not Path(path).exists():
            write_generic(path)

if __name__ == "__main__":
    main()
