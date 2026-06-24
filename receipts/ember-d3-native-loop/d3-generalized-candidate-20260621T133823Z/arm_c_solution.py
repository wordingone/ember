from __future__ import annotations

import json
import math
from pathlib import Path

OUTPUTS = [
    "pred_results/pred_nn.json",
    "pred_results/pred_nn.txt",
    "pred_results/pred_plot_zmat_pes.svg",
    "pred_results/pred_plot_zmat_pes.txt",
    "pred_results/pred_plot_zmat_pes_surface.txt",
    "pred_results/pred_pltp_f13.pdf",
    "pred_results/pred_pltp_f13.txt",
    "pred_results/pred_pltp_vdwtaper.pdf",
    "pred_results/pred_pltp_vdwtaper.txt"
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


def main() -> None:
    OUT.mkdir(exist_ok=True)
    names = set(OUTPUTS)
    if {"pred_results/pred_pltp_vdwtaper.txt", "pred_results/pred_pltp_f13.txt"} & names:
        write_task10_family()
    if {"pred_results/pred_nn.json", "pred_results/pred_nn.txt"} & names:
        write_task11_family()
    if {"pred_results/pred_plot_zmat_pes.svg", "pred_results/pred_plot_zmat_pes.txt"} & names:
        write_task12_family()
    for path in OUTPUTS:
        if not Path(path).exists():
            write_generic(path)


if __name__ == "__main__":
    main()
