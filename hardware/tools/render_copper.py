"""Render copper layers of a board to a PNG for quick review.

Usage (repo venv, needs pymupdf):
    tools/.venv/Scripts/python tools/render_copper.py hardware/tjunction/tjunction.kicad_pcb out.png [layers] [dpi]
layers defaults to "F.Cu,B.Cu,Edge.Cuts".
"""
import pathlib
import subprocess
import sys
import tempfile

import pymupdf

KICAD_CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"


def main(pcb, png, layers="F.Cu,B.Cu,Edge.Cuts", dpi=250):
    svg = pathlib.Path(tempfile.gettempdir()) / (pathlib.Path(pcb).stem + "_render.svg")
    subprocess.run([KICAD_CLI, "pcb", "export", "svg", str(pcb), "--layers", layers,
                    "--mode-single", "--fit-page-to-board", "--exclude-drawing-sheet",
                    "-o", str(svg)], check=True, capture_output=True)
    doc = pymupdf.open(str(svg))
    doc[0].get_pixmap(dpi=int(dpi)).save(str(png))
    print(f"{png}: {doc[0].rect}")


if __name__ == "__main__":
    main(*sys.argv[1:])
