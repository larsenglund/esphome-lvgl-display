"""Connect SMD pads of plane nets (GND, +3V3, ...) to their inner planes.

Freerouting 2.4 wires plane nets pad-to-pad on the outer layers but never
drops vias into the planes, so on the 4-layer node those nets never close.
This does the fanout before autorouting:
- large pads (exposed/thermal pads): a grid of vias inside the pad;
- small pads, first choice: a short straight stub to a via just outside;
- fine-pitch pads (QFN rows, crowded by their decoupling caps): a stub
  straight out of the pin row first, then on to a via;
- last resort: from that escape point to nearby copper of the same net
  (e.g. the decoupling cap's pad, which has its own via).
Stubs are as wide as the pad's short side (max stub_w). Clearances follow
the net classes (the larger of the two items' own clearances), but every pad
is first tried with at least `prefer`: vias pressed right against their
neighbours block the router's escape channels, so the tight clearance is
only used for pads that can't be reached otherwise. All added items are
locked, so Freerouting keeps them.

Geometry is checked with rectangles (pads), circles (vias) and sampled
segments; it is deliberately conservative.
"""
import math

import pcbnew

MM = pcbnew.FromMM


def _pad_rect(pad, grow=0):
    bb = pad.GetBoundingBox()
    return (bb.GetX() - grow, bb.GetY() - grow, bb.GetRight() + grow, bb.GetBottom() + grow)


def _circle_rect_clear(cx, cy, r, rect):
    x0, y0, x1, y1 = rect
    dx = max(x0 - cx, 0, cx - x1)
    dy = max(y0 - cy, 0, cy - y1)
    return dx * dx + dy * dy >= r * r


def _seg_rect_clear(a, b, half_w, rect):
    n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / MM(0.05)))
    for i in range(n + 1):
        t = i / n
        if not _circle_rect_clear(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, half_w, rect):
            return False
    return True


def _pt_seg_dist(px, py, c, d):
    vx, vy = d[0] - c[0], d[1] - c[1]
    L = vx * vx + vy * vy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - c[0]) * vx + (py - c[1]) * vy) / L))
    return math.hypot(px - (c[0] + t * vx), py - (c[1] + t * vy))


def _seg_seg_dist(a, b, c, d):
    n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / MM(0.05)))
    return min(_pt_seg_dist(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n, c, d)
               for i in range(n + 1))


def fanout(board, nets, via_d=0.45, drill=0.2, clearance=0.15, prefer=0.2, stub_w=0.3,
           big_pad_mm2=2.0, clearance_of=None, refs=None):
    """Returns (connected pads, vias added). Prints the pads it could not reach.

    clearance_of(net name) -> mm gives the net-class clearances; without it
    KiCad's own values are used, which a board built in memory (not yet
    saved with its .kicad_pro) doesn't have. refs limits it to those parts.
    The vias go through all layers: for a net whose "plane" is a pour on an
    outer layer, only fan out pads that sit over that pour."""
    nets = {("/" + n.lstrip("/")) for n in nets}
    netinfo = {n: board.FindNet(n) for n in nets}
    pads = [p for fp in board.GetFootprints() for p in fp.Pads()]
    rects = {id(p): _pad_rect(p) for p in pads}
    own_clr = {id(p): max(MM(clearance_of(p.GetNetname())) if clearance_of
                          else p.GetOwnClearance(pcbnew.F_Cu), MM(clearance)) for p in pads}
    floor = [MM(prefer), 0]       # first pass per pad: at least `prefer`, then real clearance
    vias = []           # (x, y, r, net) placed so far (iu)
    stubs = []          # (a, b, half_w, layer, net)
    r_via = MM(via_d / 2)
    hole_gap = MM(0.3) + MM(drill)   # hole-to-hole centre distance
    edge = board.GetBoardEdgesBoundingBox()
    ex0, ey0 = edge.GetX() + MM(0.6), edge.GetY() + MM(0.6)
    ex1, ey1 = edge.GetRight() - MM(0.6), edge.GetBottom() - MM(0.6)
    outline = pcbnew.SHAPE_POLY_SET()              # the real outline: boards needn't be rectangles
    board.GetBoardPolygonOutlines(outline, False)

    def on_board(x, y, r):
        """A circle of radius r at (x, y) keeps the copper-to-edge clearance from the outline and cut-outs."""
        r += MM(0.3)
        return all(outline.Contains(pcbnew.VECTOR2I(int(x + r * math.cos(k * math.pi / 8)), int(y + r * math.sin(k * math.pi / 8))))
                   for k in range(16))

    for t in board.GetTracks():          # what is routed already (by hand) stays clear too
        if t.GetClass() == "PCB_VIA":
            vias.append((t.GetPosition().x, t.GetPosition().y, t.GetWidth(pcbnew.F_Cu) / 2, t.GetNetname()))
        else:
            stubs.append(((t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y), t.GetWidth() / 2,
                          t.GetLayer(), t.GetNetname()))

    def near(x, y, r):
        return [p for p in pads if _circle_rect_clear(x, y, 0, (rects[id(p)][0] - r, rects[id(p)][1] - r,
                                                                  rects[id(p)][2] + r, rects[id(p)][3] + r))]

    def via_ok(x, y, net, clr, local):
        if not (ex0 < x < ex1 and ey0 < y < ey1) or not on_board(x, y, r_via):
            return False
        for p in local:
            if p.GetNetname() != net and not _circle_rect_clear(
                    x, y, r_via + max(clr, own_clr[id(p)], floor[0]), rects[id(p)]):
                return False
        for vx, vy, vr, vn in vias:
            if math.hypot(vx - x, vy - y) < max(hole_gap, vr + r_via + (clr if vn != net else 0)):
                return False
        for a, b, hw, _, sn in stubs:
            if sn != net and _pt_seg_dist(x, y, a, b) < r_via + hw + clr:
                return False
        return True

    def path_ok(pts, hw, layer, net, clr, local):
        inset = MM(0.3) + hw - MM(0.6)          # board-edge clearance, relative to ex0..
        if not all(ex0 + inset <= x <= ex1 - inset and ey0 + inset <= y <= ey1 - inset for x, y in pts):
            return False
        for a, b in zip(pts, pts[1:]):
            if not on_board(*b, hw):
                return False
            for p in local:
                if p.GetNetname() != net and p.IsOnLayer(layer) and not _seg_rect_clear(
                        a, b, hw + max(clr, own_clr[id(p)], floor[0]), rects[id(p)]):
                    return False
            for c, d, shw, sl, sn in stubs:
                if sn != net and sl == layer and _seg_seg_dist(a, b, c, d) < hw + shw + clr:
                    return False
            for vx, vy, vr, vn in vias:
                if vn != net and _pt_seg_dist(vx, vy, a, b) < vr + hw + clr:
                    return False
        return True

    def add_via(x, y, net):
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(int(x), int(y)))
        v.SetWidth(MM(via_d))
        v.SetDrill(MM(drill))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(netinfo[net])
        v.SetLocked(True)
        board.Add(v)
        vias.append((x, y, r_via, net))

    def add_path(pts, width, layer, net):
        for a, b in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(pcbnew.VECTOR2I(int(a[0]), int(a[1])))
            t.SetEnd(pcbnew.VECTOR2I(int(b[0]), int(b[1])))
            t.SetWidth(width)
            t.SetLayer(layer)
            t.SetNet(netinfo[net])
            t.SetLocked(True)
            board.Add(t)
            stubs.append((a, b, width / 2, layer, net))

    def candidates(pad, cx, cy, w, h):
        """(kind, path, via?) in order of preference."""
        out = []
        for dist in (0.35, 0.5, 0.7, 0.9, 1.2, 1.5):             # straight stub + via
            for ang in range(0, 360, 30):
                ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
                reach = min(abs((w / 2) / ux) if abs(ux) > 1e-9 else 1e18,
                            abs((h / 2) / uy) if abs(uy) > 1e-9 else 1e18)
                out.append(((cx, cy), (cx + ux * (reach + MM(dist) + r_via),
                                       cy + uy * (reach + MM(dist) + r_via))))
        # escape straight out along the pad's long axis, away from its footprint
        fc = pad.GetParentFootprint().GetPosition()
        if w >= h:
            u = (1 if cx >= fc.x else -1, 0)
            half = w / 2
        else:
            u = (0, 1 if cy >= fc.y else -1)
            half = h / 2
        for e in (0.2, 0.35, 0.5, 0.7, 0.9):
            ex, ey = cx + u[0] * (half + MM(e)), cy + u[1] * (half + MM(e))
            out.append(((cx, cy), (ex, ey)))
            for d in (0.3, 0.5, 0.7, 1.0):
                for ang in range(0, 360, 45):
                    ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
                    if ux * u[0] + uy * u[1] < -0.1:   # don't turn back into the pin row
                        continue
                    out.append(((cx, cy), (ex, ey), (ex + ux * MM(d), ey + uy * MM(d))))
        return out

    done = added = 0
    missed = []
    for pad in pads:
        net = pad.GetNetname()
        if net not in nets or pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
            continue
        if pad.GetParentFootprint().IsNetTie():     # sits on another pad already
            continue
        if refs is not None and pad.GetParentFootprint().GetReference() not in refs:
            continue
        layer = pcbnew.F_Cu if pad.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
        x0, y0, x1, y1 = rects[id(pad)]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w, h = x1 - x0, y1 - y0
        clr = own_clr[id(pad)]
        if pcbnew.ToMM(w) * pcbnew.ToMM(h) >= big_pad_mm2:
            # thermal / exposed pad: vias inside, 1.0 mm grid, away from its edge
            pitch = MM(1.0)
            nx = max(1, int((w - MM(0.6)) // pitch) + 1)
            ny = max(1, int((h - MM(0.6)) // pitch) + 1)
            placed = 0
            for i in range(nx):
                for j in range(ny):
                    x = cx + (i - (nx - 1) / 2) * pitch
                    y = cy + (j - (ny - 1) / 2) * pitch
                    if all(math.hypot(vx - x, vy - y) >= hole_gap for vx, vy, _, _ in vias):
                        add_via(x, y, net)
                        placed += 1
            if placed:
                done += 1
                added += placed
            continue
        width = min(MM(stub_w), min(w, h))
        hw = width / 2
        local = near(cx, cy, MM(3.5))
        # A QFN/DFN pin next to its own exposed pad of the same net joins it
        # with a short stub inwards: no via, and nothing in the escape paths
        # of the signal pins beside it. The exposed pad has its via grid.
        fp = pad.GetParentFootprint()
        ep = next((q for q in fp.Pads() if q.GetNumber() != pad.GetNumber() and q.GetNetname() == net
                   and pcbnew.ToMM(q.GetBoundingBox().GetWidth()) * pcbnew.ToMM(q.GetBoundingBox().GetHeight()) >= big_pad_mm2
                   and q.GetBoundingBox().Contains(fp.GetPosition())),      # a real exposed pad: centred
                  None)
        if ep is not None:
            qx0, qy0, qx1, qy1 = _pad_rect(ep)      # (ex0.. is the board edge)
            inset = MM(0.15)
            end = None
            if qx0 <= cx <= qx1:
                end = (cx, qy1 - inset) if cy > qy1 else (cx, qy0 + inset) if cy < qy0 else None
            elif qy0 <= cy <= qy1:
                end = (qx1 - inset, cy) if cx > qx1 else (qx0 + inset, cy) if cx < qx0 else None
            if end and math.hypot(end[0] - cx, end[1] - cy) < MM(1.5) \
                    and path_ok([(cx, cy), end], hw, layer, net, clr, local):
                add_path([(cx, cy), end], width, layer, net)
                done += 1
                continue
            # a corner pin beside the pad: join the nearest same-net pin of the
            # same package instead (that one reaches the pad), still no via
            joined = False
            def faces_pad(q):                   # q's own stub goes straight into the pad
                p = q.GetPosition()
                return (qx0 <= p.x <= qx1) != (qy0 <= p.y <= qy1)
            for q in sorted((q for q in fp.Pads() if q.GetNumber() != pad.GetNumber() and q.GetNetname() == net
                             and faces_pad(q)),
                            key=lambda q: (q.GetPosition() - pad.GetPosition()).EuclideanNorm()):
                qp = q.GetPosition()
                if math.hypot(qp.x - cx, qp.y - cy) > MM(1.2):
                    break
                if path_ok([(cx, cy), (qp.x, qp.y)], hw, layer, net, clr, local):
                    add_path([(cx, cy), (qp.x, qp.y)], width, layer, net)
                    done += 1
                    joined = True
                    break
            if joined:
                continue
        best = None
        for floor[0] in (MM(prefer), 0):
            for pts in candidates(pad, cx, cy, w, h):
                if via_ok(*pts[-1], net, clr, local) and path_ok(pts, hw, layer, net, clr, local):
                    best = pts
                    break
            if best:
                break
        if best:
            add_via(*best[-1], net)
            add_path(best, width, layer, net)
            done += 1
            added += 1
            continue
        # last resort: escape, then on to the nearest same-net copper
        targets = [((rects[id(p)][0] + rects[id(p)][2]) / 2, (rects[id(p)][1] + rects[id(p)][3]) / 2)
                   for p in local if p is not pad and p.GetNetname() == net and p.IsOnLayer(layer)]
        targets += [(vx, vy) for vx, vy, _, vn in vias if vn == net]
        for pts in sorted((c for c in candidates(pad, cx, cy, w, h) if len(c) == 2),
                          key=lambda c: math.hypot(c[1][0] - cx, c[1][1] - cy)):
            ex, ey = pts[-1]
            for tx, ty in sorted(targets, key=lambda t: math.hypot(t[0] - ex, t[1] - ey)):
                if math.hypot(tx - ex, ty - ey) > MM(2.5):
                    break
                path = [(cx, cy), (ex, ey), (tx, ty)]
                if path_ok(path, hw, layer, net, clr, local):
                    best = path
                    break
            if best:
                break
        if best:
            add_path(best, width, layer, net)
            done += 1
        else:
            fp = pad.GetParentFootprint()
            missed.append(f"{fp.GetReference()}.{pad.GetNumber()}")
    if missed:
        print("fanout: not reached:", " ".join(missed))
    return done, added


def stitch(board, net, p0, p1, pitch=0.9, via_d=0.45, drill=0.2, clearance=0.15,
           clearance_of=None):
    """Locked vias of `net` on a grid inside the rectangle p0-p1 (VECTOR2I,
    board units), wherever they clear other nets' pads, tracks and vias.
    For power returns that need more vias than a pad's own fanout, e.g. a
    FET's source pins. Returns the number of vias added."""
    net = "/" + net.lstrip("/")
    ni = board.FindNet(net)
    r_via, hole_gap = MM(via_d / 2), MM(0.3) + MM(drill)
    own = MM(clearance_of(net)) if clearance_of else MM(clearance)
    allpads = [p for fp in board.GetFootprints() for p in fp.Pads()]
    pads = [p for p in allpads if p.GetNetname() != net]
    smd = [p for p in allpads if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]
    items = list(board.GetTracks())
    placed = []

    def ok(x, y):
        for p in smd:                   # no via in an SMD pad, whatever its net
            if not _circle_rect_clear(x, y, r_via + MM(0.05), _pad_rect(p)):
                return False
        for p in pads:
            clr = max(own, MM(clearance_of(p.GetNetname())) if clearance_of else own)
            if not _circle_rect_clear(x, y, r_via + clr, _pad_rect(p)):
                return False
        for t in items:
            same = t.GetNetname() == net
            if t.GetClass() == "PCB_VIA":
                v = t.GetPosition()
                d = math.hypot(v.x - x, v.y - y)
                if d < hole_gap or (not same and d < r_via + t.GetWidth(pcbnew.F_Cu) / 2 + own):
                    return False
            elif not same:
                a, b = t.GetStart(), t.GetEnd()
                if _pt_seg_dist(x, y, (a.x, a.y), (b.x, b.y)) < r_via + t.GetWidth() / 2 + own:
                    return False
        return all(math.hypot(vx - x, vy - y) >= hole_gap for vx, vy in placed)

    step = MM(pitch)
    y = p0.y + r_via
    while y <= p1.y - r_via:
        x = p0.x + r_via
        while x <= p1.x - r_via:
            if ok(x, y):
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(pcbnew.VECTOR2I(int(x), int(y)))
                v.SetWidth(MM(via_d))
                v.SetDrill(MM(drill))
                v.SetViaType(pcbnew.VIATYPE_THROUGH)
                v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                v.SetNet(ni)
                v.SetLocked(True)
                board.Add(v)
                placed.append((x, y))
            x += step
        y += step
    return len(placed)
