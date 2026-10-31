"""Export the Gerbers and drill files of a board as a zip to upload to the fab.

Run with plain Python from the repo root, once per board:
    python hardware/tools/export_gerbers.py keys
    python hardware/tools/export_gerbers.py encoders

Writes hardware/addon-<board>/production/addon-<board>-gerbers.zip (git-ignored),
with the same settings as fablights' tools/jlc_export.py: JLCPCB's layer names,
Excellon drill files with plated and unplated holes apart. Export again after
any change to the board, and look through the fab's preview before ordering.
"""
import pathlib
import shutil
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
LAYERS = "F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"


def main(build):
    project = f"addon-{build}"
    pcb = ROOT / "hardware" / project / f"{project}.kicad_pcb"
    out = pcb.parent / "production"
    tmp = out / "gerbers"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    subprocess.run([CLI, "pcb", "export", "gerbers", str(pcb), "-o", str(tmp) + "\\", "--layers", LAYERS,
                    "--subtract-soldermask", "--no-x2", "--use-drill-file-origin", "--check-zones"],
                   check=True, capture_output=True)
    subprocess.run([CLI, "pcb", "export", "drill", str(pcb), "-o", str(tmp) + "\\", "--format", "excellon",
                    "--drill-origin", "plot", "--excellon-units", "mm", "--excellon-separate-th"],
                   check=True, capture_output=True)
    z = out / f"{project}-gerbers.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(tmp.iterdir()):
            zf.write(f, f.name)
    shutil.rmtree(tmp)
    print(f"wrote {z}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("keys", "encoders"):
        sys.exit("usage: export_gerbers.py keys|encoders")
    main(sys.argv[1])
