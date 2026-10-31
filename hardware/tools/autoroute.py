"""Autoroute a KiCad board with Freerouting and import the result.

Run with KiCad's Python:
    "C:/Program Files/KiCad/10.0/bin/python.exe" hardware/tools/autoroute.py hardware/addon-keys/addon-keys.kicad_pcb [passes]

Needs freerouting-*.jar and a Java 25 runtime in hardware/tools/ext/ or in a
fablights checkout next to this repo (tools/ext/; not committed). Locked tracks
are kept, so hand-routed tracks stay as they are.

    ... autoroute.py <board> 20 --planes=GND,+3V3
    ... autoroute.py <board> 0      (cleanup only)
    ... autoroute.py <board> 0 --stubs   (cleanup, including locked tracks with a free end and locked
                                          vias on one layer: hand-routed stubs the router joined further
                                          along, and stitching vias that routing cut off)
    ... autoroute.py <board> 1 --import --planes=GND,+3V3
                                               (import an existing .ses)
    ... autoroute.py <board> 20 --lock --planes=GND,+3V3
                                               (keep the routing, add what's missing)

--planes names nets that reach an inner plane through vias placed before
routing (tools/fanout.py). Freerouting 2.4 does not count a via into a plane
as a connection and keeps wiring those nets pad-to-pad, so their pin lists
are dropped from the DSN: the pads stay as obstacles, the nets are not
routed, and their existing tracks and vias are kept as they are.

pcbnew.ImportSpecctraSES() hangs without the GUI in KiCad 10.0.6, so the
session file's routes are read here and added as tracks and vias directly.
"""
import math
import pathlib
import re
import subprocess
import sys

import pcbnew

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXT = next((d for d in (ROOT / "hardware" / "tools" / "ext", ROOT.parent / "fablights" / "tools" / "ext") if d.exists()),
           ROOT / "hardware" / "tools" / "ext")
sys.path.insert(0, str(ROOT / "hardware" / "tools"))
from schgen import find, find_all, parse  # noqa: E402


def java():
    return next(EXT.glob("jdk-25*/bin/java.exe"))


def freerouting():
    return sorted(EXT.glob("freerouting-*.jar"))[-1]


def import_session(board, ses, keep=()):
    tree = parse(pathlib.Path(ses).read_text(encoding="utf-8"))
    routes = find(tree, "routes")
    res = find(routes, "resolution")
    unit_nm = {"um": 1000, "mm": 1e6, "mil": 25400}[str(res[1])] / float(res[2])

    def pt(x, y):
        return pcbnew.VECTOR2I(int(float(x) * unit_nm), int(-float(y) * unit_nm))

    # The session holds the routing, so it replaces what is on the board,
    # except: nets in `keep` were not routed (their tracks stay, the session's
    # copy is ignored), and locked items (fanout, stitching vias) stay too -
    # Freerouting doesn't hand all of them back, and they were being lost.
    q = lambda v: (round(v.x, -4), round(v.y, -4))  # noqa: E731  (10 um)
    fixed = set()
    for t in list(board.GetTracks()):
        if t.GetNetname() in keep or t.IsLocked():
            if t.GetClass() == "PCB_VIA":
                fixed.add(("v", t.GetNetname(), q(t.GetPosition())))
            else:
                fixed.add(("t", t.GetNetname(), t.GetLayer(), frozenset((q(t.GetStart()), q(t.GetEnd())))))
            continue
        board.Remove(t)
    added = 0
    for net in find_all(find(routes, "network_out"), "net"):
        if str(net[1]) in keep:
            continue
        name = str(net[1])
        ni = board.FindNet(name)
        for wire in find_all(net, "wire"):
            path = find(wire, "path")
            layer = board.GetLayerID(str(path[1]))
            # Freerouting sometimes necks a track down below the board minimum
            width = max(int(float(path[2]) * unit_nm), board.GetDesignSettings().m_TrackMinWidth)
            coords = path[3:]
            pts = [pt(coords[i], coords[i + 1]) for i in range(0, len(coords) - 1, 2)]
            for a, b in zip(pts, pts[1:]):
                if ("t", name, layer, frozenset((q(a), q(b)))) in fixed:
                    continue
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(a)
                t.SetEnd(b)
                t.SetWidth(width)
                t.SetLayer(layer)
                t.SetNet(ni)
                board.Add(t)
                added += 1
        for via in find_all(net, "via"):
            if ("v", name, q(pt(via[2], via[3]))) in fixed:
                continue
            m = re.search(r"_(\d+):(\d+)_um", str(via[1]))
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(pt(via[2], via[3]))
            v.SetWidth(pcbnew.FromMM(int(m.group(1)) / 1000))
            v.SetDrill(pcbnew.FromMM(int(m.group(2)) / 1000))
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            v.SetNet(ni)
            board.Add(v)
            added += 1
    return added


def _seg_dist(p, a, b):
    """Distance from point p to segment a-b (tuples, internal units)."""
    vx, vy = b[0] - a[0], b[1] - a[1]
    L = vx * vx + vy * vy
    u = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L))
    return math.hypot(p[0] - (a[0] + u * vx), p[1] - (a[1] + u * vy))


def cleanup(board, stubs=False):
    """Remove what Freerouting left of connections it didn't finish: unlocked
    vias joining fewer than two copper layers, and unlocked tracks with a free
    end (locked ones too with stubs=True; run that only on a finished board).
    Repeats until nothing changes. Zones must be filled. Returns count.

    After board.Remove(), KiCad 10.0.6's Python bindings can hand back untyped
    objects from later calls ("SwigPyObject has no attribute ..."). So all
    geometry and all pad/zone hit tests are read first, the iteration runs on
    plain Python data, and the board is only touched again to remove items."""
    xy = lambda v: (v.x, v.y)  # noqa: E731
    copper = [pcbnew.F_Cu, pcbnew.B_Cu] + [pcbnew.In1_Cu + 2 * i for i in range(board.GetCopperLayerCount() - 2)]
    pads, zones = {}, {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            pads.setdefault(p.GetNetCode(), []).append(p)
    for z in board.Zones():
        zones.setdefault(z.GetNetCode(), []).append(z)
    tracks, vias = [], []            # plain records; "obj" only used for removal
    for t in board.GetTracks():
        net = t.GetNetCode()
        if t.GetClass() == "PCB_VIA":
            pos, r = t.GetPosition(), t.GetWidth(pcbnew.F_Cu) // 2
            fixed = {l for p in pads.get(net, []) if p.HitTest(pos)
                     for l in (pcbnew.F_Cu, pcbnew.B_Cu) if p.IsOnLayer(l)}
            fixed |= {l for z in zones.get(net, []) for l in copper if z.IsOnLayer(l)
                      and z.HitTestFilledArea(l, pos, r + pcbnew.FromMM(0.6))}
            vias.append({"obj": t, "net": net, "pos": xy(pos), "r": r, "locked": t.IsLocked(),
                         "fixed": fixed})
        else:
            layer, w = t.GetLayer(), t.GetWidth()
            ends = [t.GetStart(), t.GetEnd()]
            anchored = [any(p.IsOnLayer(layer) and p.HitTest(e, w // 2) for p in pads.get(net, []))
                        or any(z.IsOnLayer(layer) and z.HitTestFilledArea(layer, e, w // 2)
                               for z in zones.get(net, [])) for e in ends]
            tracks.append({"obj": t, "net": net, "layer": layer, "w": w, "ends": [xy(e) for e in ends],
                           "locked": t.IsLocked(), "anchored": anchored})
    tol = pcbnew.FromMM(0.005)
    alive_t, alive_v = set(range(len(tracks))), set(range(len(vias)))
    t_by_net, v_by_net = {}, {}
    for i, t in enumerate(tracks):
        t_by_net.setdefault(t["net"], []).append(i)
    for i, v in enumerate(vias):
        v_by_net.setdefault(v["net"], []).append(i)
    while True:
        dead_v = set()
        for i in alive_v:
            v = vias[i]
            if v["locked"] and not stubs:
                continue
            layers = set(v["fixed"])
            layers |= {tracks[k]["layer"] for k in t_by_net.get(v["net"], []) if k in alive_t
                       and _seg_dist(v["pos"], *tracks[k]["ends"]) <= v["r"] + tracks[k]["w"] / 2}
            if len(layers) < 2:
                dead_v.add(i)
        dead_t = set()
        for i in alive_t:
            t = tracks[i]
            if t["locked"] and not stubs:
                continue
            for e, anchored in zip(t["ends"], t["anchored"]):
                if anchored:
                    continue
                # an end inside another track's copper is connected, as KiCad sees it
                # (finish_route ends its tracks anywhere on the target's width)
                if any(k != i and k in alive_t and tracks[k]["layer"] == t["layer"]
                       and _seg_dist(e, *tracks[k]["ends"]) <= tracks[k]["w"] / 2 + tol for k in t_by_net.get(t["net"], [])):
                    continue
                if any(k in alive_v and k not in dead_v and math.hypot(e[0] - vias[k]["pos"][0], e[1] - vias[k]["pos"][1]) <= vias[k]["r"]
                       for k in v_by_net.get(t["net"], [])):
                    continue
                dead_t.add(i)
                break
        if not dead_v and not dead_t:
            break
        alive_v -= dead_v
        alive_t -= dead_t
    gone = [vias[i]["obj"] for i in range(len(vias)) if i not in alive_v] +            [tracks[i]["obj"] for i in range(len(tracks)) if i not in alive_t]
    for item in gone:
        board.Remove(item)
    return len(gone)


def add_keepouts(dsn, keepouts):
    """Insert (keepout ...) polygons into the DSN structure (um, y up)."""
    if not keepouts:
        return
    lines = []
    for layer, pts in keepouts:
        coords = "  ".join(f"{pcbnew.ToMM(x) * 1000:.1f} {-pcbnew.ToMM(y) * 1000:.1f}" for x, y in pts)
        lines.append(f'    (keepout "" (polygon {layer} 0  {coords}))')
    text = dsn.read_text(encoding="utf-8")
    i = text.index("    (boundary")
    dsn.write_text(text[:i] + "\n".join(lines) + "\n" + text[i:], encoding="utf-8")


def drop_pins(dsn, nets):
    """Empty the pin lists of `nets` in the DSN network section."""
    text = dsn.read_text(encoding="utf-8")
    for n in nets:
        text, k = re.subn(r"\(net " + re.escape(n) + r"\s*\(pins[^)]*\)", f"(net {n}", text)
        if not k:
            sys.exit(f"net {n} not found in {dsn.name}")
    dsn.write_text(text, encoding="utf-8")


def main(pcb, passes=40, *extra):
    planes = [a for a in extra if a.startswith("--planes=")]
    import_only = "--import" in extra
    lock = "--lock" in extra
    stubs = "--stubs" in extra
    extra = [a for a in extra if a not in planes and a not in ("--import", "--lock", "--stubs")]
    planes = ["/" + n.lstrip("/") for a in planes for n in a.split("=", 1)[1].split(",")]
    pcb = pathlib.Path(pcb).resolve()
    # board.Save() can rewrite .kicad_pro with default net settings (seen with
    # KiCad 10.0.6 when the project was already loaded), so keep a copy.
    pro = pcb.with_suffix(".kicad_pro")
    pro_bytes = pro.read_bytes() if pro.exists() else None
    board = pcbnew.LoadBoard(str(pcb))
    if passes == 0:                     # no routing: just clean up an earlier result
        finish(board, pcb, pro_bytes, stubs)
        return
    dsn, ses = pcb.with_suffix(".dsn"), pcb.with_suffix(".ses")
    if lock:
        # --lock: finish an earlier result. Existing tracks go out as protected
        # wiring, so Freerouting only adds the missing connections instead of
        # ripping everything up; they come back unlocked from the session.
        for t in board.GetTracks():
            t.SetLocked(True)
    if not import_only:                 # --import: take the existing .ses as it is
        route(board, pcb, dsn, ses, passes, planes, extra)
    if not ses.exists():
        sys.exit("no session file produced")
    n = import_session(board, ses, keep=set(planes))
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(pcb))
    if pro_bytes is not None:
        pro.write_bytes(pro_bytes)
    print(f"routed {pcb.name}: {n} tracks/vias added", flush=True)
    # The cleanup reads the board back; after import_session() removed the old
    # tracks the SWIG objects in this process are unreliable, so it runs in a
    # fresh one.
    subprocess.run([sys.executable, __file__, str(pcb), "0"], check=True)
    dsn.unlink(missing_ok=True)
    ses.unlink(missing_ok=True)


def route(board, pcb, dsn, ses, passes, planes, extra):
    """DSN export -> Freerouting -> .ses next to the board."""
    # Pours would be cut into islands by the routed traces, so take them out
    # and let Freerouting wire every net; put them back after.
    # Only inner-layer pours of the --planes nets are real planes (their layer
    # is marked as such, Freerouting doesn't route on it); every other pour is
    # lifted, so an inner layer that only carries a filler pour (e.g. +3V3 on
    # the NODE's In2) stays a routing layer.
    # Rule areas without tracks: KiCad doesn't export board-level rule areas,
    # so they are added to the DSN as keepouts (Freerouting has no track-only
    # keepout; blocking its vias there too is stricter, not wrong).
    keepouts = []
    for z in board.Zones():
        if z.GetIsRuleArea() and z.GetDoNotAllowTracks():
            ring = z.Outline().Outline(0)
            pts = [(ring.CPoint(k).x, ring.CPoint(k).y) for k in range(ring.PointCount())]
            keepouts.append((board.GetLayerName(z.GetLayer()), pts))
    removed = []
    for z in list(board.Zones()):
        if z.GetLayer() not in (pcbnew.F_Cu, pcbnew.B_Cu) and z.GetNetname() in planes:
            board.SetLayerType(z.GetLayer(), pcbnew.LT_POWER)
        else:
            removed.append(z)
            board.Remove(z)
    if not pcbnew.ExportSpecctraDSN(board, str(dsn)):
        sys.exit("DSN export failed")
    for z in removed:
        board.Add(z)
    drop_pins(dsn, planes)
    add_keepouts(dsn, keepouts)
    cmd = [str(java()), "-jar", str(freerouting()), "-de", str(dsn), "-do", str(ses),
           "-mp", str(passes), "--gui.enabled=false", *extra]
    print(" ".join(cmd), flush=True)
    log = pcb.with_suffix(".route.log")   # streamed, so progress is visible while it runs
    with open(log, "w", encoding="utf-8") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)
    print("\n".join(log.read_text(encoding="utf-8").strip().splitlines()[-4:]), flush=True)


def finish(board, pcb, pro_bytes, stubs=False):
    """Fill zones, drop unfinished route pieces, refill, save."""
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    k = cleanup(board, stubs)
    if k:
        print(f"cleanup: removed {k} dangling vias/track pieces", flush=True)
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(pcb))
    if pro_bytes is not None:
        pcb.with_suffix(".kicad_pro").write_bytes(pro_bytes)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 40, *sys.argv[3:])
