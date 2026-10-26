"""3D renders of the boards: top, bottom and an angled view.

Run with KiCad's Python:
    "C:/Program Files/KiCad/10.0/bin/python.exe" tools/render3d.py [board ...]

Default: all boards. Writes hardware/<board>/renders/<name>-{top,bottom,angled}.png.
The NODE is rendered once per assembly variant (NODE-W, NODE-B): parts of
the other variant (the schematic's "Variant" field) are hidden as DNP. Its
edge-hole header footprints get no 3D model, since nothing is fitted there
at assembly. A library model missing from this KiCad install is replaced by
a stand-in from hardware/lib (STAND_INS). All of this is done on a temporary
copy; the board files are not touched. DNP parts (e.g. the NODE's RJ45) are
not shown.
"""
import os
import pathlib
import subprocess
import sys

import pcbnew

ROOT = pathlib.Path(__file__).resolve().parents[2]
KICAD_CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
KICAD_3D = os.environ.get("KICAD10_3DMODEL_DIR", r"C:\Program Files\KiCad\10.0\share\kicad\3dmodels")
BOARDS = {
    # board: (variants or [None], refs whose 3D model is hidden)
    "addon-keys": ([None], []),
    "addon-encoders": ([None], []),
}
# library model -> (stand-in model, offset mm (3D axes: +y = up the board), rotation deg),
# used only while the library model file is missing.
# HRO TYPE-C-31-M-12 (C165948): the LCSC model of the same-size 16-pin
# TYPE-C16PIN (C393939). Its pegs and shell legs sit 1.31 mm further back in
# its own footprint; the offset puts its body on the KiCad footprint's
# F.Fab outline (y -3.65..3.65), checked in a render.
STAND_INS = {}
VIEWS = {
    "top": ["--side", "top"],
    "bottom": ["--side", "bottom"],
    "angled": ["--side", "top", "--perspective", "--rotate", "-45,0,45", "--zoom", "0.9", "--floor"],
}


def model_spec(m):
    """(filename, offset, rotation, scale, opacity, show) of a footprint's 3D
    model, with a stand-in for a library model that isn't installed."""
    name = m.m_Filename.replace("\\", "/").rsplit("/", 1)[-1]
    if name in STAND_INS and not pathlib.Path(m.m_Filename.replace("${KICAD10_3DMODEL_DIR}", KICAD_3D)).exists():
        filename, offset, rotation = STAND_INS[name]
        return filename, offset, rotation, (1, 1, 1), 1.0, True
    xyz = lambda v: (v.x, v.y, v.z)  # noqa: E731
    return m.m_Filename, xyz(m.m_Offset), xyz(m.m_Rotation), xyz(m.m_Scale), m.m_Opacity, m.m_Show


def prepare(board, variant, hide):
    """Temporary copy next to the board (so ${KIPRJMOD} model paths resolve)."""
    src = ROOT / "hardware" / board / f"{board}.kicad_pcb"
    tmp = src.with_name(f"_render_{variant or board}.kicad_pcb")
    b = pcbnew.LoadBoard(str(src))
    for fp in b.GetFootprints():
        if fp.GetReference() in hide:
            fp.Models().clear()        # (setting m_Show on the items only changes copies)
        specs = [model_spec(m) for m in fp.Models()]
        if any(s[0] != m.m_Filename for s, m in zip(specs, fp.Models())):
            fp.Models().clear()        # rebuilt from values: the old items die with the list
            for filename, offset, rotation, scale, opacity, show in specs:
                m = pcbnew.FP_3DMODEL()
                m.m_Filename = filename
                m.m_Offset = pcbnew.VECTOR3D(*offset)
                m.m_Rotation = pcbnew.VECTOR3D(*rotation)
                m.m_Scale = pcbnew.VECTOR3D(*scale)
                m.m_Opacity = opacity
                m.m_Show = show
                fp.Models().append(m)
        if variant:
            f = fp.GetField("Variant")
            v = f.GetText() if f else ""
            if v and not v.startswith(variant):
                fp.SetDNP(True)
    b.Save(str(tmp))
    return tmp


def main(boards):
    # board.Save() can rewrite the project file of the loaded board: keep them
    pros = {p: p.read_bytes() for p in (ROOT / "hardware").glob("*/*.kicad_pro")}
    try:
        render(boards)
    finally:
        for p, data in pros.items():
            p.write_bytes(data)


def render(boards):
    for board in boards or BOARDS:
        variants, hide = BOARDS[board]
        out = ROOT / "hardware" / board / "renders"
        out.mkdir(exist_ok=True)
        for variant in variants:
            name = variant.lower() if variant else board
            tmp = prepare(board, variant, hide)
            try:
                for view, args in VIEWS.items():
                    png = out / f"{name}-{view}.png"
                    r = subprocess.run([KICAD_CLI, "pcb", "render", str(tmp), "-o", str(png),
                                        "--width", "1600", "--height", "1200", "--quality", "high",
                                        "--background", "opaque", *args],
                                       capture_output=True, text=True)
                    print(f"{png.relative_to(ROOT)}: {'ok' if r.returncode == 0 else r.stderr.strip()[-200:]}",
                          flush=True)
            finally:
                for f in tmp.parent.glob(tmp.stem + ".*"):
                    f.unlink()


if __name__ == "__main__":
    main(sys.argv[1:])
