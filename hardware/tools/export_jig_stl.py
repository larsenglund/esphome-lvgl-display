"""Export the bare board as an STL for a 3D-printed fit test (git-ignored output).

Run with KiCad's Python from the repo root, once per board:
    "C:/Program Files/KiCad/10.0/bin/python.exe" hardware/tools/export_jig_stl.py keys
    "C:/Program Files/KiCad/10.0/bin/python.exe" hardware/tools/export_jig_stl.py encoders

Printed holes come out undersized, so on a temporary copy of the board the holes that
pins have to go through are opened up (the KiCad board keeps the real sizes):
- 2.54 mm header holes (J1 to the panel, J4, the radar U3): 1.7 mm
- encoder pins: 1.5 mm, encoder mounting-tab slots: +0.2 mm
Writes hardware/addon-<board>/mockup/addon-<board>-alignment.stl.
"""
import pathlib
import subprocess
import sys

import pcbnew

ROOT = pathlib.Path(__file__).resolve().parents[2]
BUILD = sys.argv[1] if len(sys.argv) > 1 else ""
if BUILD not in ("keys", "encoders"):
    sys.exit("usage: export_jig_stl.py keys|encoders")
PROJECT = f"addon-{BUILD}"
BOARD = ROOT / "hardware" / PROJECT / f"{PROJECT}.kicad_pcb"
TMP = BOARD.with_name("_jig.kicad_pcb")
OUT = BOARD.with_name("mockup") / f"{PROJECT}-alignment.stl"
CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"

HEADER_DRILL = 1.7
ENC_PIN_DRILL = 1.5
ENC_SLOT_GROW = 0.2


def drill(pad, w, h=None):
    pad.SetDrillSize(pcbnew.VECTOR2I(pcbnew.FromMM(w), pcbnew.FromMM(h if h is not None else w)))


b = pcbnew.LoadBoard(str(BOARD))
for fp in b.GetFootprints():
    ref = fp.GetReference()
    for pad in fp.Pads():
        if pad.GetAttribute() != pcbnew.PAD_ATTRIB_PTH:
            continue
        if ref in ("J1", "J4", "U3"):
            drill(pad, HEADER_DRILL)
        elif ref.startswith("ENC"):
            size = pad.GetDrillSize()
            if size.x != size.y:          # mounting-tab slot
                drill(pad, pcbnew.ToMM(size.x) + ENC_SLOT_GROW, pcbnew.ToMM(size.y) + ENC_SLOT_GROW)
            else:
                drill(pad, ENC_PIN_DRILL)
b.Save(str(TMP))
try:
    OUT.parent.mkdir(exist_ok=True)
    subprocess.run([CLI, "pcb", "export", "stl", "--board-only", "--force", "-o", str(OUT), str(TMP)],
                   check=True, capture_output=True)
finally:
    for suffix in (".kicad_pcb", ".kicad_pro", ".kicad_prl"):
        TMP.with_suffix(suffix).unlink(missing_ok=True)
print(f"wrote {OUT}")
