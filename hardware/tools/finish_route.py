"""Finish the connections an autorouter left open.

Run with KiCad's Python:
    "C:/Program Files/KiCad/10.0/bin/python.exe" hardware/tools/finish_route.py hardware/addon-keys/addon-keys.kicad_pcb

    ... finish_route.py <board> F.Cu,B.Cu

KiCad's own DRC lists the unconnected items; each pair (pad, track or via;
pour islands are left alone, and a pad or via cut off from a pour is wired to
the net's nearest via) is routed with A* on a 0.05 mm grid over the
given copper layers (default F.Cu,B.Cu), with through vias. Clearances come from the net classes in
.kicad_pro (the larger of the two nets'), and the board's real outline with its cut-outs is kept
clear of (these boards are far from rectangular). Crossing the fill of a power pour
is allowed but costs 5x, so signals go around pours where they can (a gate
trace still has to cross the switch node); the GND background pour and V_LED
cost nothing extra. All pours refill around the new tracks - check DRC for
split pours.
New tracks use their net class's width and vias. Results are meant to be
checked with DRC afterwards; the script reports what it could not route.
"""
import fnmatch
import heapq
import json
import math
import pathlib
import subprocess
import sys

import numpy as np
import pcbnew

KICAD_CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
G = 0.05                   # grid (mm)
MARGIN = 0.04              # extra clearance for the grid's rounding (mm)
VIA_COST = 30              # in grid steps (1.5 mm)
CROSSABLE = {"/GND", "/V_LED", "/+3V3"}   # outer pours signals may cross
EDGE_CLEARANCE = 0.3
HOLE_TO_HOLE = 0.3
HOLE_CLEARANCE = 0.2       # board setting: copper to any hole
MAX_EXPAND = 4_000_000
POUR_COST = 5              # step cost multiplier inside another net's power pour
DEBUG = False


class NetClasses:
    def __init__(self, pro):
        ns = json.loads(pro.read_text(encoding="utf-8"))["net_settings"]
        self.cls = {c["name"]: c for c in ns["classes"]}
        self.pat = [(p["pattern"], p["netclass"]) for p in ns.get("netclass_patterns") or []]

    def of(self, net):
        name = next((c for p, c in self.pat if fnmatch.fnmatchcase(net, p)), "Default")
        return self.cls.get(name, self.cls["Default"])


def mm(v):
    return pcbnew.ToMM(v)


class Grid:
    def __init__(self, board):
        bb = board.GetBoardEdgesBoundingBox()
        self.x0, self.y0 = mm(bb.GetX()), mm(bb.GetY())
        self.nx = int(math.ceil(mm(bb.GetWidth()) / G)) + 1
        self.ny = int(math.ceil(mm(bb.GetHeight()) / G)) + 1
        self.w, self.h = mm(bb.GetWidth()), mm(bb.GetHeight())
        xs = self.x0 + np.arange(self.nx) * G
        ys = self.y0 + np.arange(self.ny) * G
        self.X, self.Y = np.meshgrid(xs, ys)          # [row=y, col=x]

    def window(self, x0, y0, x1, y1):
        i0 = max(int((y0 - self.y0) / G) - 1, 0)
        i1 = min(int((y1 - self.y0) / G) + 2, self.ny)
        j0 = max(int((x0 - self.x0) / G) - 1, 0)
        j1 = min(int((x1 - self.x0) / G) + 2, self.nx)
        return slice(i0, i1), slice(j0, j1)

    def cell(self, x, y):
        return int(round((y - self.y0) / G)), int(round((x - self.x0) / G))

    def xy(self, i, j):
        return self.x0 + j * G, self.y0 + i * G


# --- shapes: ("rect", x0, y0, x1, y1) | ("circle", cx, cy, r) | ("seg", ax, ay, bx, by, hw) ---
def shape_bbox(s, d=0.0):
    if s[0] == "rect":
        return s[1] - d, s[2] - d, s[3] + d, s[4] + d
    if s[0] == "circle":
        return s[1] - s[3] - d, s[2] - s[3] - d, s[1] + s[3] + d, s[2] + s[3] + d
    _, ax, ay, bx, by, hw = s
    return min(ax, bx) - hw - d, min(ay, by) - hw - d, max(ax, bx) + hw + d, max(ay, by) + hw + d


def shape_dist(s, X, Y):
    """Distance from grid points to the shape's copper (0 inside)."""
    if s[0] == "rect":
        dx = np.maximum(np.maximum(s[1] - X, 0), X - s[3])
        dy = np.maximum(np.maximum(s[2] - Y, 0), Y - s[4])
        return np.hypot(dx, dy)
    if s[0] == "circle":
        return np.maximum(np.hypot(X - s[1], Y - s[2]) - s[3], 0)
    _, ax, ay, bx, by, hw = s
    vx, vy = bx - ax, by - ay
    L = vx * vx + vy * vy
    t = np.zeros_like(X) if L == 0 else np.clip(((X - ax) * vx + (Y - ay) * vy) / L, 0, 1)
    return np.maximum(np.hypot(X - (ax + t * vx), Y - (ay + t * vy)) - hw, 0)


def paint(grid, arr, s, value, d=0.0):
    """Set arr[cells within d of shape s] = value."""
    rs, cs = grid.window(*shape_bbox(s, d))
    if rs.start >= rs.stop or cs.start >= cs.stop:
        return
    m = shape_dist(s, grid.X[rs, cs], grid.Y[rs, cs]) <= d
    arr[rs, cs][m] = value


def pad_shape(p):
    bb = p.GetBoundingBox()
    if p.GetShape(pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu) == pcbnew.PAD_SHAPE_CIRCLE:
        c = p.GetPosition()
        return ("circle", mm(c.x), mm(c.y), mm(bb.GetWidth()) / 2)
    return ("rect", mm(bb.GetX()), mm(bb.GetY()), mm(bb.GetRight()), mm(bb.GetBottom()))


def poly_fill(grid, arr, rings, value):
    """Even-odd scanline fill of polygon rings [(x, y), ...] into arr."""
    allpts = [p for r in rings for p in r]
    xs = [p[0] for p in allpts]
    ys = [p[1] for p in allpts]
    rs, _ = grid.window(min(xs), min(ys), max(xs), max(ys))
    edges = [(r[k], r[(k + 1) % len(r)]) for r in rings for k in range(len(r))]
    for i in range(rs.start, rs.stop):
        y = grid.y0 + i * G
        cross = sorted(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                       for a, b in edges if (a[1] <= y < b[1]) or (b[1] <= y < a[1]))
        for xa, xb in zip(cross[0::2], cross[1::2]):
            j0 = max(int(math.ceil((xa - grid.x0) / G)), 0)
            j1 = min(int(math.floor((xb - grid.x0) / G)), grid.nx - 1)
            if j1 >= j0:
                arr[i, j0:j1 + 1] = value


def disk(r_cells):
    r = int(math.ceil(r_cells))
    return [(di, dj) for di in range(-r, r + 1) for dj in range(-r, r + 1) if di * di + dj * dj <= r_cells * r_cells]


def dilate(mask, r_mm):
    out = mask.copy()
    ny, nx = mask.shape
    for di, dj in disk(r_mm / G):
        if di == 0 and dj == 0:
            continue
        src = mask[max(-di, 0):ny - max(di, 0), max(-dj, 0):nx - max(dj, 0)]
        out[max(di, 0):ny - max(-di, 0), max(dj, 0):nx - max(-dj, 0)] |= src
    return out


class Router:
    def __init__(self, pcb, layers=("F.Cu", "B.Cu")):
        self.pcb = pathlib.Path(pcb).resolve()
        self.pro = self.pcb.with_suffix(".kicad_pro")
        self.pro_bytes = self.pro.read_bytes()
        self.nc = NetClasses(self.pro)
        self.board = pcbnew.LoadBoard(str(self.pcb))
        self.lids = [self.board.GetLayerID(n) for n in layers]               # routing layers
        self.grid = Grid(self.board)
        g = self.grid
        self.netcode = {}                   # name -> int (>0)
        self.label = [np.zeros((g.ny, g.nx), np.int32) for _ in self.lids]  # copper by net, per layer
        self.zlabel = [np.zeros((g.ny, g.nx), np.int32) for _ in self.lids] # power-pour fills by net
        self.pads_by_net = {}                                                # net -> [(shape, layers)]
        self.smd = np.zeros((g.ny, g.nx), bool)                              # any SMD pad (no via-in-pad)
        self.holes = []                                                      # (x, y, r)
        self.items = {}                                                      # lookup for DRC items
        self._read()
        self.outside = ~self._inside()                                       # off the board: outline and cut-outs
        self.edge_masks = {}

    def code(self, net):
        return self.netcode.setdefault(net, len(self.netcode) + 1)

    def _inside(self):
        polys = pcbnew.SHAPE_POLY_SET()
        self.board.GetBoardPolygonOutlines(polys, False)
        g, inside = self.grid, np.zeros((self.grid.ny, self.grid.nx), bool)
        for k in range(polys.OutlineCount()):
            rings = []
            for h in range(-1, polys.HoleCount(k)):
                ring = polys.Outline(k) if h < 0 else polys.Hole(k, h)
                rings.append([(mm(ring.CPoint(q).x), mm(ring.CPoint(q).y)) for q in range(ring.PointCount())])
            poly_fill(g, inside, rings, True)
        return inside

    def edge_mask(self, d):
        """Cells closer than d to the board's edge."""
        key = round(d, 3)
        if key not in self.edge_masks:
            self.edge_masks[key] = dilate(self.outside, d)
        return self.edge_masks[key]

    def _read(self):
        b, g = self.board, self.grid
        for fp in b.GetFootprints():
            for p in fp.Pads():
                s, n = pad_shape(p), self.code(p.GetNetname())
                for L, lid in enumerate(self.lids):
                    if p.IsOnLayer(lid):
                        paint(g, self.label[L], s, n)
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
                    paint(g, self.smd, s, True)
                if p.GetDrillSizeX() > 0:
                    c = p.GetPosition()
                    self.holes.append((mm(c.x), mm(c.y), mm(p.GetDrillSizeX()) / 2, p.GetNetname()))
                self.items[("pad", fp.GetReference(), p.GetNumber())] = (p.GetNetname(), s,
                    {L for L, lid in enumerate(self.lids) if p.IsOnLayer(lid)})
                self.pads_by_net.setdefault(p.GetNetname(), []).append(
                    (s, {L for L, lid in enumerate(self.lids) if p.IsOnLayer(lid)}))
        self.tracks = []
        for t in b.GetTracks():
            n, net = self.code(t.GetNetname()), t.GetNetname()
            if t.GetClass() == "PCB_VIA":
                c = t.GetPosition()
                s = ("circle", mm(c.x), mm(c.y), mm(t.GetWidth(pcbnew.F_Cu)) / 2)
                for L in range(len(self.lids)):
                    paint(g, self.label[L], s, n)
                self.holes.append((s[1], s[2], mm(t.GetDrillValue()) / 2, net))
                self.tracks.append(("via", net, s, set(range(len(self.lids)))))
            else:
                a, e = t.GetStart(), t.GetEnd()
                if t.GetLayer() not in self.lids:
                    continue
                L = self.lids.index(t.GetLayer())
                s = ("seg", mm(a.x), mm(a.y), mm(e.x), mm(e.y), mm(t.GetWidth()) / 2)
                paint(g, self.label[L], s, n)
                self.tracks.append(("track", net, s, {L}, mm(t.GetLength())))
        self.no_track = [np.zeros((g.ny, g.nx), bool) for _ in self.lids]
        for z in b.Zones():
            if z.GetIsRuleArea():
                if z.GetDoNotAllowTracks() and z.GetLayer() in self.lids:
                    ring = z.Outline().Outline(0)
                    pts = [(mm(ring.CPoint(q).x), mm(ring.CPoint(q).y)) for q in range(ring.PointCount())]
                    poly_fill(g, self.no_track[self.lids.index(z.GetLayer())], [pts], True)
                continue
            net = z.GetNetname()
            L = self.lids.index(z.GetLayer()) if z.GetLayer() in self.lids else None
            # crossable: the GND background / planes and V_LED; the local
            # power pours (priority 3+, e.g. GND under the low-side FET) are not
            if L is None or z.GetIsRuleArea() or (net in CROSSABLE and z.GetAssignedPriority() < 3):
                continue
            polys = z.GetFilledPolysList(z.GetLayer())
            n = self.code(net)
            for k in range(polys.OutlineCount()):
                rings = []
                for h in range(-1, polys.HoleCount(k)):
                    ring = polys.Outline(k) if h < 0 else polys.Hole(k, h)
                    rings.append([(mm(ring.CPoint(q).x), mm(ring.CPoint(q).y)) for q in range(ring.PointCount())])
                poly_fill(g, self.zlabel[L], rings, n)

    # --- DRC items -> (net, shape, layers) ----------------------------------------
    def find(self, desc, pos):
        x, y = pos["x"], pos["y"]
        net = desc.split("[")[1].split("]")[0]
        if desc.startswith(("Pad ", "PTH pad ", "NPTH pad ")):
            num = desc.split("[")[0].split()[-1]
            ref = desc.split(" of ")[1].split()[0]
            return self.items.get(("pad", ref, num))
        if desc.startswith("Via "):
            vias = [t for t in self.tracks if t[0] == "via" and t[1] == net]
            v = min(vias, key=lambda t: math.hypot(t[2][1] - x, t[2][2] - y))
            return net, v[2], set(range(len(self.lids)))
        if desc.startswith("Track "):
            name = desc.split(" on ")[1].split(",")[0]
            layer = self.lids.index(self.board.GetLayerID(name))
            length = float(desc.split("length ")[1].split()[0].replace(",", "."))
            cands = [t for t in self.tracks if t[0] == "track" and t[1] == net and t[3] == {layer}]
            best = min(cands, key=lambda t: (abs(t[4] - length) > 0.002,
                       float(shape_dist(t[2], np.array([x]), np.array([y]))[0])))
            return net, best[2], {layer}
        return None

    def nearest_via(self, a):
        """The net's closest via to item a, as a routing target; a itself doesn't count."""
        net, s, _ = a
        x, y = (s[1], s[2]) if s[0] == "circle" else ((s[1] + s[3]) / 2, (s[2] + s[4]) / 2)
        vias = [t for t in self.tracks if t[0] == "via" and t[1] == net and math.hypot(t[2][1] - x, t[2][2] - y) > 0.01]
        if not vias:
            return None
        v = min(vias, key=lambda t: math.hypot(t[2][1] - x, t[2][2] - y))
        return net, v[2], set(range(len(self.lids)))

    # --- routing ---------------------------------------------------------------------
    def route(self, a, b, max_mm=None):
        """Route item a to item b; None if it can't, or only by a path longer than max_mm."""
        g = self.grid
        net, sa, la = a
        _, sb, lb = b
        n = self.code(net)
        c = self.nc.of(net)
        hw, clr = c["track_width"] / 2, c["clearance"]
        r_via, drill = c["via_diameter"] / 2, c["via_drill"]
        other_clr = {code: self.nc.of(name)["clearance"] for name, code in self.netcode.items()}
        clr_groups = {}
        for code, oc in other_clr.items():
            if code != n:
                clr_groups.setdefault(oc, []).append(code)
        edge = self.edge_mask(EDGE_CLEARANCE + hw + MARGIN)
        blocked, vblock, soft = [], np.zeros((g.ny, g.nx), bool), []
        nl = len(self.lids)
        # every drilled hole (plated or not) keeps HOLE_CLEARANCE from tracks
        # on all layers; own-net plated holes are in the net's copper anyway
        hole_block = np.zeros((g.ny, g.nx), bool)
        for hx, hy, hr, hn in self.holes:
            if hn != net or not hn:
                paint(g, hole_block, ("circle", hx, hy, hr), True, HOLE_CLEARANCE + hw + MARGIN)
        for L in range(nl):
            lab = self.label[L]
            other = (lab != 0) & (lab != n)
            # pour fills: obstacles, except near this net's own pads, so a
            # track can reach a pad that sits inside another net's pour (the
            # pour refills around it, with a small notch)
            own = np.zeros((g.ny, g.nx), bool)
            for ps, pl in self.pads_by_net.get(net, []):
                if L in pl:
                    paint(g, own, ps, True, 0.8)
            zl = self.zlabel[L]
            zone = (zl != 0) & (zl != n) & ~own
            # Pours are soft: crossing one costs POUR_COST per step, so tracks go
            # around when they can; a gate trace has to cross the switch node.
            soft.append(dilate(zone, hw + 0.2 + MARGIN))
            # other nets' copper, grown by the larger of the two net classes'
            # clearances (one group per distinct clearance value)
            bl = edge | dilate(self.no_track[L], hw + MARGIN) | hole_block
            for oc, codes in clr_groups.items():
                m = other & np.isin(lab, codes)
                if m.any():
                    bl |= dilate(m, hw + max(clr, oc) + MARGIN)
                    vblock |= dilate(m, r_via + max(clr, oc) + MARGIN)
            blocked.append(bl)
        vblock |= dilate(self.smd, r_via + 0.05)
        vblock |= self.edge_mask(EDGE_CLEARANCE + r_via + MARGIN)
        for hx, hy, hr, _ in self.holes:
            paint(g, vblock, ("circle", hx, hy, hr), True, HOLE_TO_HOLE + drill / 2 + MARGIN)
        src = [np.zeros((g.ny, g.nx), bool) for _ in range(nl)]
        tgt = [np.zeros((g.ny, g.nx), bool) for _ in range(nl)]
        for L in la:
            paint(g, src[L], sa, True)
        for L in lb:
            paint(g, tgt[L], sb, True)
        for L in range(nl):
            blocked[L] &= ~(src[L] | tgt[L])
        tb = shape_bbox(sb)

        def h(i, j):
            x, y = g.xy(i, j)
            dx = max(tb[0] - x, 0, x - tb[2])
            dy = max(tb[1] - y, 0, y - tb[3])
            return math.hypot(dx, dy) / G

        gs = {}
        parent = {}
        heap = []
        for L in range(nl):
            for i, j in zip(*np.nonzero(src[L])):
                key = (L, int(i), int(j))
                gs[key] = 0.0
                heapq.heappush(heap, (h(i, j), 0.0, key))
        steps = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
                 (-1, -1, 1.414), (-1, 1, 1.414), (1, -1, 1.414), (1, 1, 1.414)]
        expanded = 0
        end = None
        while heap and expanded < MAX_EXPAND:
            f, gc, key = heapq.heappop(heap)
            if gc > gs.get(key, 1e18):
                continue
            L, i, j = key
            if tgt[L][i, j]:
                end = key
                break
            expanded += 1
            for di, dj, cost in steps:
                ii, jj = i + di, j + dj
                if not (0 <= ii < g.ny and 0 <= jj < g.nx) or blocked[L][ii, jj]:
                    continue
                if di and dj and (blocked[L][i, jj] or blocked[L][ii, j]):
                    continue                     # no corner cutting
                nk = (L, ii, jj)
                ng = gc + cost * (POUR_COST if soft[L][ii, jj] else 1)
                if ng < gs.get(nk, 1e18):
                    gs[nk] = ng
                    parent[nk] = key
                    heapq.heappush(heap, (ng + h(ii, jj), ng, nk))
            if not vblock[i, j]:
                for LL in range(nl):
                    if LL == L or blocked[LL][i, j]:
                        continue
                    nk = (LL, i, j)
                    ng = gc + VIA_COST
                    if ng < gs.get(nk, 1e18):
                        gs[nk] = ng
                        parent[nk] = key
                        heapq.heappush(heap, (ng + h(i, j), ng, nk))
        if end is None:
            if DEBUG:
                print(f"   {net}: expanded {expanded}, src cells {[int(m.sum()) for m in src]}, "
                      f"free src {[int((m & ~blocked[L]).sum()) for L, m in enumerate(src)]}, "
                      f"tgt cells {[int(m.sum()) for m in tgt]}", flush=True)
            return None
        if max_mm is not None and gs[end] * G > max_mm:
            print(f"   {net}: only a {gs[end] * G:.0f} mm path (limit {max_mm:.0f} mm)", flush=True)
            return None
        path = [end]
        while path[-1] in parent:
            path.append(parent[path[-1]])
        path.reverse()
        return self._commit(net, n, c, path, blocked, soft)

    @staticmethod
    def _smooth(run, blocked, soft):
        """Line-of-sight simplification of a same-layer run of grid cells:
        from each kept cell, jump to the farthest later cell reachable in a
        straight line over free cells (entering no pour the path avoided), so
        the track gets a few any-angle segments instead of a grid staircase."""
        def clear(a, b):       # quarter-cell samples; MARGIN covers what lies between
            n = max(abs(b[1] - a[1]), abs(b[2] - a[2])) * 4
            for k in range(1, n):
                i = int(round(a[1] + (b[1] - a[1]) * k / n))
                j = int(round(a[2] + (b[2] - a[2]) * k / n))
                if blocked[i, j] or (soft[i, j] and not (soft[a[1], a[2]] or soft[b[1], b[2]])):
                    return False
            return True
        pts, i = [run[0]], 0
        while i < len(run) - 1:
            j = len(run) - 1
            while j > i + 1 and not clear(run[i], run[j]):
                j -= 1
            pts.append(run[j])
            i = j
        return pts

    def _commit(self, net, n, c, path, blocked, soft):
        g, b = self.grid, self.board
        ni = b.FindNet(net)
        added = 0
        runs, cur = [], [path[0]]
        for k in path[1:]:
            if k[0] != cur[-1][0]:
                runs.append(cur)
                cur = [k]
            else:
                cur.append(k)
        runs.append(cur)
        for r, run in enumerate(runs):
            L = run[0][0]
            pts = self._smooth(run, blocked[L], soft[L])
            for p, q in zip(pts, pts[1:]):
                (xa, ya), (xb, yb) = g.xy(p[1], p[2]), g.xy(q[1], q[2])
                t = pcbnew.PCB_TRACK(b)
                t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(xa), pcbnew.FromMM(ya)))
                t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(xb), pcbnew.FromMM(yb)))
                t.SetWidth(pcbnew.FromMM(c["track_width"]))
                t.SetLayer(self.lids[L])
                t.SetNet(ni)
                b.Add(t)
                s = ("seg", xa, ya, xb, yb, c["track_width"] / 2)
                paint(g, self.label[L], s, n)
                self.tracks.append(("track", net, s, {L}, math.hypot(xb - xa, yb - ya)))
                added += 1
            if r + 1 < len(runs):                # layer change: via at the run's last cell
                x, y = g.xy(run[-1][1], run[-1][2])
                v = pcbnew.PCB_VIA(b)
                v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
                v.SetWidth(pcbnew.FromMM(c["via_diameter"]))
                v.SetDrill(pcbnew.FromMM(c["via_drill"]))
                v.SetViaType(pcbnew.VIATYPE_THROUGH)
                v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                v.SetNet(ni)
                b.Add(v)
                s = ("circle", x, y, c["via_diameter"] / 2)
                for LL in range(len(self.lids)):
                    paint(g, self.label[LL], s, n)
                self.holes.append((x, y, c["via_drill"] / 2, net))
                self.tracks.append(("via", net, s, set(range(len(self.lids)))))
                added += 1
        return added

    def save(self):
        self.board.BuildConnectivity()
        pcbnew.ZONE_FILLER(self.board).Fill(self.board.Zones())
        self.board.Save(str(self.pcb))
        self.pro.write_bytes(self.pro_bytes)


def drc(pcb):
    out = pathlib.Path(pcb).with_suffix(".drc.json")
    subprocess.run([KICAD_CLI, "pcb", "drc", str(pcb), "--format", "json", "-o", str(out)],
                   capture_output=True)
    d = json.loads(out.read_text(encoding="utf-8"))
    out.unlink()
    return d


def unconnected(pcb):
    return [u["items"] for u in drc(pcb)["unconnected_items"]]


RIP_TYPES = ("clearance", "shorting_items", "tracks_crossing", "hole_clearance", "hole_to_hole", "copper_edge_clearance")


def rip(pcb):
    """Remove the unlocked track of every clearance-type DRC violation (the
    autorouter's occasional slips, e.g. a signal passing a V_LED via at the
    signal clearance), so the router below can lay it again. Runs in its own
    process: after board.Remove() the bindings can't be trusted to read."""
    tracks = [i for v in drc(pcb)["violations"] if v["type"] in RIP_TYPES
              for i in v["items"] if i["description"].startswith("Track ")]
    if not tracks:
        return 0
    arg = pathlib.Path(pcb).with_suffix(".rip.json")
    arg.write_text(json.dumps(tracks), encoding="utf-8")
    subprocess.run([sys.executable, __file__, "--rip", str(pcb), str(arg)], check=True)
    arg.unlink()
    return len(tracks)


def _rip_items(pcb, arg):
    pcb = pathlib.Path(pcb)
    pro = pcb.with_suffix(".kicad_pro")
    pro_bytes = pro.read_bytes()
    board = pcbnew.LoadBoard(str(pcb))
    want = json.loads(pathlib.Path(arg).read_text(encoding="utf-8"))
    gone = []
    tracks = [t for t in board.GetTracks() if t.GetClass() != "PCB_VIA" and not t.IsLocked()]
    for i in want:
        d = i["description"]
        net = d.split("[")[1].split("]")[0]
        layer = board.GetLayerID(d.split(" on ")[1].split(",")[0])
        length = float(d.split("length ")[1].split()[0].replace(",", "."))
        p = pcbnew.VECTOR2I(pcbnew.FromMM(i["pos"]["x"]), pcbnew.FromMM(i["pos"]["y"]))
        cands = [t for t in tracks if t.GetNetname() == net and t.GetLayer() == layer
                 and abs(mm(t.GetLength()) - length) < 0.002 and t not in gone]
        if cands:
            gone.append(min(cands, key=lambda t: min((t.GetStart() - p).EuclideanNorm(), (t.GetEnd() - p).EuclideanNorm())))
    for t in gone:
        board.Remove(t)
    board.Save(str(pcb))
    pro.write_bytes(pro_bytes)
    print(f"ripped {len(gone)} tracks with clearance errors")


def route_open(pcb, layers, first=()):
    """One routing round over DRC's unconnected list; nets in `first` go
    first. Returns the pairs it could not route (pour islands excluded)."""
    pairs = unconnected(pcb)
    pairs.sort(key=lambda items: items[0]["description"].split("[")[1].split("]")[0] not in first
               if "[" in items[0]["description"] else True)
    r = Router(pcb, layers.split(","))
    done, failed = 0, []
    for items in pairs:
        descs = [i["description"] for i in items]
        if all(d.startswith("Zone") for d in descs):
            print("  pour island (not routed here):", " / ".join(d[:40] for d in descs), flush=True)
            continue
        if any(d.startswith("Zone") for d in descs):     # a pad or via cut off from the pour: wire it to the nearest via
            item = next(i for i in items if not i["description"].startswith("Zone"))
            a = r.find(item["description"], item["pos"])
            b = r.nearest_via(a) if a else None
            limit = 15.0                                 # a longer way round is worth a look by hand
        else:
            a, b = (r.find(i["description"], i["pos"]) for i in items)
            limit = None
        if not a or not b:
            print("  item not found:", " / ".join(descs), flush=True)
            continue
        n = r.route(a, b, limit)
        if n:
            done += 1
            print(f"routed {a[0]}: {n} tracks/vias", flush=True)
        else:
            failed.append(items)
            print(f"FAILED {a[0]}", flush=True)
    r.save()
    print(f"{done} of {len(pairs)} connections routed", flush=True)
    return failed


def _rip_near(pcb, arg):
    """Remove unlocked tracks and vias of other nets within the given radius
    of the given points (they block a connection that has to get through)."""
    pcb = pathlib.Path(pcb)
    pro = pcb.with_suffix(".kicad_pro")
    pro_bytes = pro.read_bytes()
    spec = json.loads(pathlib.Path(arg).read_text(encoding="utf-8"))
    board = pcbnew.LoadBoard(str(pcb))
    pts = [pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)) for x, y in spec["points"]]
    r = pcbnew.FromMM(spec["radius"])
    gone = []
    for t in board.GetTracks():
        if t.IsLocked() or t.GetNetname() in spec["keep"]:
            continue
        if any(t.HitTest(p, r) for p in pts):
            gone.append(t)
    for t in gone:
        board.Remove(t)
    board.Save(str(pcb))
    pro.write_bytes(pro_bytes)
    print(f"ripped {len(gone)} tracks/vias around {len(pts)} blocked ends", flush=True)


def health(pcb):
    """(open connections, routing errors) from DRC."""
    d = drc(pcb)
    bad = [v for v in d["violations"] if v["type"] in RIP_TYPES + ("track_dangling", "via_dangling")]
    return len(d["unconnected_items"]), len(bad)


def main(pcb, layers="F.Cu,B.Cu", attempts=3):
    """Rip up clearance errors and route what is open. For connections that
    still fail, try ripping other nets' tracks around their ends (growing
    radius) and routing them first; each try is kept only if DRC shows fewer
    open connections and no routing errors, otherwise the board is restored."""
    pcb = pathlib.Path(pcb).resolve()
    autoroute = str(pathlib.Path(__file__).with_name("autoroute.py"))
    if rip(pcb):
        subprocess.run([sys.executable, autoroute, str(pcb), "0"], check=True)   # drop dangling pieces
    failed = route_open(pcb, layers)
    best = health(pcb)
    print(f"after routing: {best[0]} open, {best[1]} routing errors", flush=True)
    backup = pcb.with_suffix(".finish_backup")
    for attempt in range(int(attempts)):
        if not failed or best[1]:
            break
        backup.write_bytes(pcb.read_bytes())
        nets = sorted({i["description"].split("[")[1].split("]")[0] for items in failed for i in items})
        pts = [(i["pos"]["x"], i["pos"]["y"]) for items in failed for i in items]
        arg = pcb.with_suffix(".ripnear.json")
        arg.write_text(json.dumps({"points": pts, "radius": 0.6 + 0.4 * attempt, "keep": nets}), encoding="utf-8")
        subprocess.run([sys.executable, __file__, "--rip-near", str(pcb), str(arg)], check=True)
        arg.unlink()
        subprocess.run([sys.executable, autoroute, str(pcb), "0"], check=True)
        print(f"retry {attempt + 1}: {', '.join(nets)} first", flush=True)
        f2 = route_open(pcb, layers, first=set(nets))
        subprocess.run([sys.executable, autoroute, str(pcb), "0"], check=True)   # leftovers of ripped routes
        h = health(pcb)
        if h[0] < best[0] and h[1] == 0:
            best, failed = h, f2
            print(f"  kept: {h[0]} open", flush=True)
        else:
            pcb.write_bytes(backup.read_bytes())
            print(f"  reverted ({h[0]} open, {h[1]} errors)", flush=True)
    backup.unlink(missing_ok=True)
    print(f"result: {best[0]} open, {best[1]} routing errors")
    for items in failed:
        print("  open:", " / ".join(i["description"][:45] for i in items))


if __name__ == "__main__":
    if sys.argv[1] == "--rip":
        _rip_items(*sys.argv[2:])
    elif sys.argv[1] == "--rip-near":
        _rip_near(*sys.argv[2:])
    else:
        main(*sys.argv[1:])
