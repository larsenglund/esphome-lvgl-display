"""Import LCSC parts into the shared KiCad library (hardware/lib/addon.*).

Usage: <fablights venv python> hardware/tools/import_lcsc.py C3192337 C7470701 ...
       <fablights venv python> hardware/tools/import_lcsc.py --fixup   (only re-apply fixes)

Wraps easyeda2kicad, then cleans up what it produces:
- 3D models: absolute .wrl paths -> ${KIPRJMOD}/../lib/...step (STEP only)
- mounting pegs exported as zero-annulus plated pads -> non-plated holes
- "unspecified" pin types -> passive
- 3D model offsets easyeda2kicad gets wrong (MODEL_OFFSETS), measured on an
  STL export of the board
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
LIB = ROOT / "hardware" / "lib" / "addon"
MODEL_PREFIX = "${KIPRJMOD}/../lib/addon.3dshapes/"
PEG = re.compile(r'\(pad "" thru_hole (circle|oval) (\(at [^)]*\)) '
                 r'\(size ([\d.]+) ([\d.]+)\) \(drill ([\d.]+)\)')
# model file stem -> offset (x y z, mm) for models easyeda2kicad places wrong
MODEL_OFFSETS = {}


def fix_footprint(text):
    text = re.sub(r'\(model "[^"]*/addon.3dshapes/([^"]+)\.wrl"',
                  lambda m: f'(model "{MODEL_PREFIX}{m.group(1)}.step"', text)
    for stem, xyz in MODEL_OFFSETS.items():
        text = re.sub(r'(\(model "[^"]*/' + re.escape(stem) + r'\.step"\s*\(offset\s*\(xyz )[^)]*\)',
                      lambda m: m.group(1) + xyz + ")", text)

    def peg(m):
        if abs(float(m.group(3)) - float(m.group(5))) > 0.01:
            return m.group(0)
        return (f'(pad "" np_thru_hole {m.group(1)} {m.group(2)} '
                f'(size {m.group(3)} {m.group(4)}) (drill {m.group(5)})')
    return PEG.sub(peg, text)


def fixup():
    for mod in LIB.with_suffix(".pretty").glob("*.kicad_mod"):
        text = mod.read_text(encoding="utf-8")
        fixed = fix_footprint(text)
        if fixed != text:
            mod.write_text(fixed, encoding="utf-8")
    sym = LIB.with_suffix(".kicad_sym")
    text = sym.read_text(encoding="utf-8")
    fixed = re.sub(r"\(pin unspecified ", "(pin passive ", text)
    if fixed != text:
        sym.write_text(fixed, encoding="utf-8")
    # KiCad renders STEP directly; the VRML copies only bloat the repo.
    for wrl in LIB.with_suffix(".3dshapes").glob("*.wrl"):
        wrl.unlink()


def main(args):
    if not args:
        sys.exit(__doc__)
    if args != ["--fixup"]:
        subprocess.run(
            [sys.executable, "-m", "easyeda2kicad", "--full", "--overwrite",
             "--lcsc_id", *args, "--output", str(LIB)],
            check=True,
        )
    fixup()


if __name__ == "__main__":
    main(sys.argv[1:])
