"""Tie the GND pours on the two sides together with stitching vias, after routing.

Run with KiCad's Python:
    "C:/Program Files/KiCad/10.0/bin/python.exe" hardware/tools/stitch.py hardware/addon-keys/addon-keys.kicad_pcb [pitch]

Works out what is connected to what: every piece of pour, GND pad, via and track,
with the board's largest piece of pour as the main ground. Pour islands are kept
meanwhile, so a piece that the routing cut off can still get its via.
- Grid (pitch in mm, default 7): a locked via near each node, where the fill
  surrounds it on both sides and it adds to the main ground, clear of part bodies
  (so nothing sits on a via), pads, holes and silkscreen. The radar floats on its
  header, so vias can go under it. A node looks for a spot within a third of the
  pitch; a node with a GND via near it already is skipped.
- Rescue: copper still cut off gets a via wherever one can join it to the main
  ground, even under a part. A via joining two pockets that connect to nothing else
  is never placed: it would only keep them both.
It then prints what is still cut off, with its pads. Pieces with no pads are removed
as islands when the pours refill.
"""
import math
import pathlib
import sys

import pcbnew

NET = "/GND"
VIA_D, VIA_DRILL = 0.6, 0.3
HOLE_GAP = 0.5       # hole edge to hole edge (mm)
SILK_GAP = 0.2       # via copper to silkscreen text (mm)
FLOATING = ("U3",)   # parts standing clear of the board
LAYERS = (pcbnew.F_Cu, pcbnew.B_Cu)


class Groups:
    """Union-find over hashable items."""

    def __init__(self):
        self.up = {}

    def find(self, a):
        self.up.setdefault(a, a)
        while self.up[a] != a:
            self.up[a] = self.up[self.up[a]]
            a = self.up[a]
        return a

    def join(self, a, b):
        self.up[self.find(a)] = self.find(b)


def ring(x, y, r, n=16):
    return [(x + r * math.cos(k * 2 * math.pi / n), y + r * math.sin(k * 2 * math.pi / n)) for k in range(n)]


def v2(x, y):
    return pcbnew.VECTOR2I(int(x), int(y))


def main(pcb, pitch=7.0):
    pcb, pitch = pathlib.Path(pcb).resolve(), float(pitch)
    pro = pcb.with_suffix(".kicad_pro")
    pro_bytes = pro.read_bytes()
    board = pcbnew.LoadBoard(str(pcb))
    zones = [z for z in board.Zones() if not z.GetIsRuleArea() and z.GetNetname() == NET]
    for z in zones:
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())

    # --- the pieces of pour on each side ----------------------------------------------------------
    pieces = {lay: [] for lay in LAYERS}         # layer -> [(piece, size)]
    for z in zones:
        polys = z.GetFilledPolysList(z.GetLayer())
        for k in range(polys.OutlineCount()):
            one = pcbnew.SHAPE_POLY_SET()
            one.AddOutline(polys.Outline(k))
            for h in range(polys.HoleCount(k)):
                one.AddHole(polys.Hole(k, h))
            bb = polys.Outline(k).BBox()
            pieces[z.GetLayer()].append((one, bb.GetWidth() * bb.GetHeight()))

    def piece_at(lay, x, y):
        p = v2(x, y)
        return next(((lay, k) for k, (one, _) in enumerate(pieces[lay]) if one.Contains(p)), None)

    # --- what is connected to what ----------------------------------------------------------------
    g = Groups()
    main_ground = max(((lay, k) for lay in LAYERS for k in range(len(pieces[lay]))),
                      key=lambda n: pieces[n[0]][n[1]][1])
    for lay in LAYERS:
        for k in range(len(pieces[lay])):
            g.find((lay, k))

    keep_pads, keep_parts, holes, gnd_vias, gnd_pads = [], [], [], [], []
    grow = pcbnew.FromMM(VIA_D / 2 + 0.1)

    def box(bb, m):
        return bb.GetX() - m, bb.GetY() - m, bb.GetRight() + m, bb.GetBottom() + m

    for fp in board.GetFootprints():
        for p in fp.Pads():
            keep_pads.append(box(p.GetBoundingBox(), grow))
            if p.GetDrillSizeX() > 0:
                holes.append((p.GetPosition().x, p.GetPosition().y, max(p.GetDrillSizeX(), p.GetDrillSizeY()) / 2))
            if p.GetNetname() != NET:
                continue
            name = f"{fp.GetReference()}.{p.GetNumber()}"
            gnd_pads.append(name)
            x, y, bb = p.GetPosition().x, p.GetPosition().y, p.GetBoundingBox()
            r = min(bb.GetWidth(), bb.GetHeight()) * 0.45
            for lay in LAYERS:
                if p.IsOnLayer(lay):
                    for px, py in [(x, y)] + ring(x, y, r):
                        n = piece_at(lay, px, py)
                        if n:
                            g.join(name, n)
        if fp.GetReference() in FLOATING:
            continue
        fp.BuildCourtyardCaches()
        court = fp.GetCourtyard(pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd)
        if court.OutlineCount():
            keep_parts.append(box(court.BBox(), grow))
    silk = pcbnew.FromMM(VIA_D / 2 + SILK_GAP)
    for d in board.GetDrawings():
        if d.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            keep_parts.append(box(d.GetBoundingBox(), silk))

    tracks = []                                  # this net's tracks: (id, layer, start, end, half width)
    for i, t in enumerate(board.GetTracks()):
        if t.GetClass() == "PCB_VIA":
            x, y = t.GetPosition().x, t.GetPosition().y
            holes.append((x, y, t.GetDrillValue() / 2))
            if t.GetNetname() == NET:
                gnd_vias.append((x, y))
                g.find(("via", x, y))
                for lay in LAYERS:
                    n = piece_at(lay, x, y)
                    if n:
                        g.join(("via", x, y), n)
        elif t.GetNetname() == NET:
            a, c = t.GetStart(), t.GetEnd()
            tracks.append((("track", i), t.GetLayer(), (a.x, a.y), (c.x, c.y), t.GetWidth() / 2))
    pads = [(f"{fp.GetReference()}.{p.GetNumber()}", p) for fp in board.GetFootprints() for p in fp.Pads()
            if p.GetNetname() == NET]
    for tid, lay, a, c, hw in tracks:
        for e in (a, c, ((a[0] + c[0]) / 2, (a[1] + c[1]) / 2)):
            n = piece_at(lay, *e)
            if n:
                g.join(tid, n)
        for e in (a, c):
            for name, p in pads:
                if p.IsOnLayer(lay) and p.HitTest(v2(*e), int(hw)):
                    g.join(tid, name)
        for vx, vy in gnd_vias:             # a via may sit anywhere along a track
            ux, uy = c[0] - a[0], c[1] - a[1]
            u = max(0.0, min(1.0, ((vx - a[0]) * ux + (vy - a[1]) * uy) / (ux * ux + uy * uy or 1)))
            if math.hypot(vx - a[0] - u * ux, vy - a[1] - u * uy) <= pcbnew.FromMM(0.2):
                g.join(tid, ("via", vx, vy))
    for k, (tid, lay, a, c, hw) in enumerate(tracks):
        for tid2, lay2, a2, c2, hw2 in tracks[k + 1:]:
            if lay == lay2 and any(math.hypot(e[0] - f[0], e[1] - f[1]) <= hw + hw2 for e in (a, c) for f in (a2, c2)):
                g.join(tid, tid2)

    # --- where a via can go --------------------------------------------------------------------------
    r_fill = pcbnew.FromMM(VIA_D / 2 + 0.05)
    gap = pcbnew.FromMM(VIA_DRILL / 2 + HOLE_GAP)

    def in_fill(x, y):
        pts = [(x, y)] + ring(x, y, r_fill, 8)
        return all(any(z.IsOnLayer(lay) and z.HitTestFilledArea(lay, v2(px, py), 0) for z in zones)
                   for lay in LAYERS for px, py in pts)

    def free(x, y, boxes):
        return (not any(b[0] < x < b[2] and b[1] < y < b[3] for b in boxes)
                and all(math.hypot(x - hx, y - hy) >= hr + gap for hx, hy, hr in holes) and in_fill(x, y))

    def joins_main(x, y):
        """The two pieces of pour at (x, y), when a via there adds to the main ground."""
        f, b = piece_at(pcbnew.F_Cu, x, y), piece_at(pcbnew.B_Cu, x, y)
        if f and b and g.find(f) != g.find(b) and g.find(main_ground) in (g.find(f), g.find(b)):
            return f, b
        return None

    def add_via(x, y, f, b):
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(v2(x, y))
        v.SetWidth(pcbnew.FromMM(VIA_D))
        v.SetDrill(pcbnew.FromMM(VIA_DRILL))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(board.FindNet(NET))
        v.SetLocked(True)
        board.Add(v)
        holes.append((x, y, pcbnew.FromMM(VIA_DRILL) / 2))
        gnd_vias.append((x, y))
        g.join(f, b)

    # --- grid --------------------------------------------------------------------------------------------
    bb = board.GetBoardEdgesBoundingBox()
    step, reach = pcbnew.FromMM(0.5), pcbnew.FromMM(pitch / 3)
    n_steps = int(reach / step)
    offsets = sorted(((i * step, j * step) for i in range(-n_steps, n_steps + 1) for j in range(-n_steps, n_steps + 1)),
                     key=lambda o: math.hypot(*o))
    p, near = pcbnew.FromMM(pitch), pcbnew.FromMM(pitch / 2)
    grid = rescued = 0
    for gy in range(bb.GetY() + p // 2, bb.GetBottom(), p):
        for gx in range(bb.GetX() + p // 2, bb.GetRight(), p):
            if any(math.hypot(gx - vx, gy - vy) < near for vx, vy in gnd_vias):
                continue
            for dx, dy in offsets:
                x, y = gx + dx, gy + dy
                if not free(x, y, keep_pads + keep_parts):
                    continue
                f, b = piece_at(pcbnew.F_Cu, x, y), piece_at(pcbnew.B_Cu, x, y)
                # both sides already on the main ground: an ordinary stitching via, for the return paths
                if f and b and (joins_main(x, y) or g.find(f) == g.find(b) == g.find(main_ground)):
                    add_via(x, y, f, b)
                    grid += 1
                    break

    # --- rescue: a cut-off group with a pad or a fair piece of pour, by a via that joins it to the main
    # ground. Clear of part bodies if it can be. Small pockets with neither aren't worth a via ------------
    fine = pcbnew.FromMM(0.25)
    big = pcbnew.FromMM(5.0) ** 2

    def rescue_spot(one):
        bk = one.BBox()
        for boxes in (keep_pads + keep_parts, keep_pads):
            for y in range(bk.GetY(), bk.GetBottom(), fine):
                for x in range(bk.GetX(), bk.GetRight(), fine):
                    if one.Contains(v2(x, y)) and joins_main(x, y) and free(x, y, boxes):
                        return x, y
        return None

    changed = True
    while changed:
        changed = False
        with_pads = {g.find(name) for name in gnd_pads}
        for lay in LAYERS:
            for k, (one, size) in enumerate(pieces[lay]):
                root = g.find((lay, k))
                if root == g.find(main_ground) or (root not in with_pads and size < big):
                    continue
                spot = rescue_spot(one)
                if spot:
                    add_via(*spot, *joins_main(*spot))
                    rescued += 1
                    changed = True
                    with_pads = {g.find(name) for name in gnd_pads}

    cut_off = sorted(name for name in gnd_pads if g.find(name) != g.find(main_ground))
    for z in zones:
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(pcb))
    pro.write_bytes(pro_bytes)
    print(f"{pcb.name}: {grid} stitching vias, {rescued} to rescue cut-off copper")
    if cut_off:
        print("  GND pads still cut off from the main ground:", " ".join(cut_off))


if __name__ == "__main__":
    main(*sys.argv[1:])
