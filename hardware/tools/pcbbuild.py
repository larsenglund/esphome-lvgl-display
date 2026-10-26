"""Build a KiCad PCB from a schematic netlist and a placement table.

Run with KiCad's bundled Python (it provides `pcbnew`), e.g.
    "C:/Program Files/KiCad/10.0/bin/python.exe" hardware/node/place_node.py

The board keeps the schematic link (footprint paths = symbol UUIDs), so later
changes can still go through "Update PCB from Schematic" in the GUI.
"""
import fnmatch
import json
import pathlib
import subprocess
import sys

import pcbnew

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hardware" / "tools"))
from schgen import find, find_all, parse  # noqa: E402

KICAD = pathlib.Path(r"C:\Program Files\KiCad\10.0")
STD_FP = KICAD / "share" / "kicad" / "footprints"
ORIGIN = (100.0, 100.0)  # board top-left corner in KiCad coordinates (mm)


def mm(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(ORIGIN[0] + x), pcbnew.FromMM(ORIGIN[1] + y))


def lib_path(lib):
    if lib == "addon":
        return str(ROOT / "hardware" / "lib" / "addon.pretty")
    return str(STD_FP / f"{lib}.pretty")


def read_netlist(sch):
    net = sch.with_suffix(".net")
    for attempt in range(4):  # kicad-cli 10.0.6 occasionally crashes on export
        r = subprocess.run([str(KICAD / "bin" / "kicad-cli.exe"), "sch", "export", "netlist",
                            str(sch), "-o", str(net)], capture_output=True)
        if r.returncode == 0:
            break
    else:
        raise RuntimeError(f"netlist export failed: {r.returncode}")
    tree = parse(net.read_text(encoding="utf-8"))
    net.unlink()
    comps = {}
    for c in find_all(find(tree, "components"), "comp"):
        ref = str(find(c, "ref")[1])
        props = {str(find(p, "name")[1]): (str(find(p, "value")[1]) if find(p, "value") else "")
                 for p in find_all(c, "property")}
        comps[ref] = {"value": str(find(c, "value")[1]),
                      "footprint": str(find(c, "footprint")[1]) if find(c, "footprint") else "",
                      "uuid": str(find(c, "tstamps")[1]),
                      "props": props}
    pads = {}
    for n in find_all(find(tree, "nets"), "net"):
        name = str(find(n, "name")[1])
        for node in find_all(n, "node"):
            pads[(str(find(node, "ref")[1]), str(find(node, "pin")[1]))] = name
    return comps, pads


def clearance_lookup(netclasses):
    """net name -> clearance (mm), from the same spec that Board.save() writes
    into .kicad_pro. For code that needs net-class clearances before the
    board has been saved (a board built in memory doesn't know its classes)."""
    default = netclasses.get("Default", (0, 0.2))[1]
    rules = [(pat, spec[1]) for spec in netclasses.values() for pat in spec[2]]

    def lookup(net):
        n = net.lstrip("/")
        return next((clr for pat, clr in rules if fnmatch.fnmatchcase(n, pat)), default)
    return lookup


# Custom DRC rules, written next to every board.
DRU = """(version 1)

# Header and jack pins at the board edge or between neighbouring pins can't
# get two thermal spokes; one 0.5 mm spoke carries far more than they need,
# and a full connection would make them hard to hand-solder.
(rule "THT pads: one thermal spoke is enough"
  (constraint min_resolved_spokes 1)
  (condition "A.Type == 'Pad' && A.Pad_Type == 'Through-hole'"))

# The NODE's edge-hole rows (and the matching headers on its carriers) are
# split into several 2.54 mm strips that continue each other end to end.
(rule "pin-header strips continue each other"
  (constraint courtyard_clearance (min -1mm))
  (condition "A.Library_Link == 'Connector_PinHeader_2.54mm:*' && B.Library_Link == 'Connector_PinHeader_2.54mm:*'"))
"""


class Board:
    def __init__(self, sch, width, height, layers=4, corner=1.0, outline=None):
        """outline: optional closed polygon [(x, y), ...] in board mm for
        boards that aren't a plain width x height rectangle (notches)."""
        self.sch = pathlib.Path(sch)
        self.w, self.h = width, height
        self.board = pcbnew.BOARD()
        self.board.SetCopperLayerCount(layers)
        ds = self.board.GetDesignSettings()  # JLCPCB-safe minimums
        ds.m_MinClearance = pcbnew.FromMM(0.127)
        ds.m_TrackMinWidth = pcbnew.FromMM(0.127)
        ds.m_CopperEdgeClearance = pcbnew.FromMM(0.3)
        ds.m_HoleClearance = pcbnew.FromMM(0.2)
        ds.m_HoleToHoleMin = pcbnew.FromMM(0.3)
        ds.m_MinThroughDrill = pcbnew.FromMM(0.2)
        ds.m_ViasMinSize = pcbnew.FromMM(0.4)
        ds.m_ViasMinAnnularWidth = pcbnew.FromMM(0.1)
        ds.m_SilkClearance = pcbnew.FromMM(0.1)
        self.comps, self.pads = read_netlist(self.sch)
        self.nets = {}
        for name in sorted(set(self.pads.values())):
            ni = pcbnew.NETINFO_ITEM(self.board, name)
            self.board.Add(ni)
            self.nets[name] = ni
        self.fps = {}
        self._boxes = {}
        self._outline(corner, outline)

    # -- geometry -----------------------------------------------------------
    def _outline(self, r, pts=None):
        w, h = self.w, self.h
        pts = pts or [(r, 0), (w - r, 0), (w, r), (w, h - r), (w - r, h), (r, h), (0, h - r), (0, r)]
        for a, b in zip(pts, pts[1:] + pts[:1]):
            seg = pcbnew.PCB_SHAPE(self.board)
            seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
            seg.SetStart(mm(*a))
            seg.SetEnd(mm(*b))
            seg.SetLayer(pcbnew.Edge_Cuts)
            seg.SetWidth(pcbnew.FromMM(0.1))
            self.board.Add(seg)

    def place(self, ref, x, y, rot=0, side="F"):
        c = self.comps[ref]
        lib, name = c["footprint"].split(":", 1)
        fp = pcbnew.FootprintLoad(lib_path(lib), name)
        if fp is None:
            raise RuntimeError(f"{ref}: footprint {c['footprint']} not found")
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetPath(pcbnew.KIID_PATH("/" + c["uuid"]))
        fp.SetFPIDAsString(c["footprint"])
        for key, val in c["props"].items():
            if key in ("LCSC", "Variant", "Note") and val:
                fp.SetField(key, val)
                fld = fp.GetField(key)
                if fld:
                    fld.SetVisible(False)
        if c["props"].get("dnp") is not None or "DNP" in c["props"]:
            fp.SetDNP(True)
        for pad in fp.Pads():
            net = self.pads.get((ref, pad.GetNumber()))
            if net:
                pad.SetNet(self.nets[net])
        self.board.Add(fp)
        if side == "B":
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetOrientationDegrees(rot)
        fp.SetPosition(mm(x, y))
        self.fps[ref] = fp
        return fp

    def place_box(self, ref, x, y, rot=0, side="F"):
        """Place so the keep-out box's top-left corner lands at (x, y)."""
        fp = self.place(ref, 0, 0, rot, side)
        x0, y0, _, _ = self.box(ref)
        fp.Move(pcbnew.VECTOR2I(pcbnew.FromMM(x - x0), pcbnew.FromMM(y - y0)))
        return fp

    def place_row(self, ref, x, y, side="F", reverse=False):
        """Pin header whose pin 1 sits at (x, y), pins running towards +x
        (towards -x with reverse=True, e.g. a module turned 180 degrees)."""
        fp = self.place(ref, x, y, 90, side)
        pads = sorted(fp.Pads(), key=lambda p: int(p.GetNumber()))
        if len(pads) > 1 and (pads[1].GetPosition().x < pads[0].GetPosition().x) != reverse:
            fp.SetOrientationDegrees(-90)
            fp.SetPosition(mm(x, y))
        return fp

    def place_row_back(self, ref, x, y):
        """Pin header on the back whose pin 1 sits at (x, y), pins running
        towards -x as seen from the top: the hole row of a NODE edge group when
        the module is mounted flat-to-flat on this board's back (its
        component side facing away), i.e. mirrored left-right."""
        fp = self.place(ref, x, y, 90, side="B")
        pads = sorted(fp.Pads(), key=lambda p: int(p.GetNumber()))
        if len(pads) > 1 and pads[1].GetPosition().x > pads[0].GetPosition().x:
            fp.SetOrientationDegrees(-90)
            fp.SetPosition(mm(x, y))
        return fp

    PAD_MARGIN = 0.2  # keep-out around pads (EasyEDA courtyards often cover only the body)

    def box(self, ref):
        """Keep-out box (x0, y0, x1, y1) in board mm: courtyard united with
        the pads grown by PAD_MARGIN."""
        fp = self.fps[ref]
        fp.BuildCourtyardCaches()
        court = fp.GetCourtyard(pcbnew.F_CrtYd if not fp.IsFlipped() else pcbnew.B_CrtYd)
        bb = court.BBox() if court.OutlineCount() else fp.GetBoundingBox(False)
        x0, y0, x1, y1 = bb.GetX(), bb.GetY(), bb.GetRight(), bb.GetBottom()
        m = pcbnew.FromMM(self.PAD_MARGIN)
        for pad in fp.Pads():
            pb = pad.GetBoundingBox()
            x0, y0 = min(x0, pb.GetX() - m), min(y0, pb.GetY() - m)
            x1, y1 = max(x1, pb.GetRight() + m), max(y1, pb.GetBottom() + m)
        return (pcbnew.ToMM(x0) - ORIGIN[0], pcbnew.ToMM(y0) - ORIGIN[1],
                pcbnew.ToMM(x1) - ORIGIN[0], pcbnew.ToMM(y1) - ORIGIN[1])

    def overlaps(self):
        """Pairs of footprints whose courtyard boxes overlap (quick check)."""
        refs = list(self.fps)
        boxes = {r: self.box(r) for r in refs}
        out = []
        for i, a in enumerate(refs):
            for b in refs[i + 1:]:
                A, B = boxes[a], boxes[b]
                if A[0] < B[2] and B[0] < A[2] and A[1] < B[3] and B[1] < A[3]:
                    out.append((a, b))
        return out

    def _free(self, box, ignore=(), margin=0.15, gap=0.0):
        x0, y0, x1, y1 = box
        if x0 < margin or y0 < margin or x1 > self.w - margin or y1 > self.h - margin:
            return False
        x0, y0, x1, y1 = x0 - gap, y0 - gap, x1 + gap, y1 + gap
        for r, fb in list(self._boxes.items()) + [(f"_ko{i}", k) for i, k in enumerate(self.keepouts)]:
            if r in ignore:
                continue
            if x0 < fb[2] and fb[0] < x1 and y0 < fb[3] and fb[1] < y1:
                return False
        return True

    keepouts = []

    def keepout(self, x0, y0, x1, y1):
        """Area the small-part legaliser must not use (e.g. under a module)."""
        self.keepouts = self.keepouts + [(x0, y0, x1, y1)]

    def pad_xy(self, ref, pad):
        p = next(p for p in self.fps[ref].Pads() if p.GetNumber() == str(pad))
        return (pcbnew.ToMM(p.GetPosition().x) - ORIGIN[0], pcbnew.ToMM(p.GetPosition().y) - ORIGIN[1])

    def neighbours(self, ref, skip=("GND", "+3V3", "+5V", "+48V")):
        """Mean position of placed pads sharing a (non-supply) net with `ref`."""
        nets = {n for (r, _), n in self.pads.items() if r == ref}
        signal = {n for n in nets if n.lstrip("/") not in skip} or nets
        pts = []
        for (r, pad), n in self.pads.items():
            if n in signal and r != ref and r in self.fps:
                try:
                    pts.append(self.pad_xy(r, pad))
                except StopIteration:
                    pass
        if not pts:
            return None
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

    GAP = 0.35  # extra room around auto-placed passives for escape vias

    def place_near(self, ref, target=None, rot=90, step=0.2, radius=15.0):
        """Put a small part in the free spot closest to `target` (default: its
        neighbours' pads), trying both orientations."""
        target = target or self.neighbours(ref) or (self.w / 2, self.h / 2)
        self._boxes = {r: self.box(r) for r in self.fps if r not in self.ROW_REFS}
        fp = self.place(ref, 0, 0, rot)
        best = None
        for gap in (self.GAP, self.GAP / 2, 0.0):   # relax the via gap only if needed
            best = self._search(fp, ref, target, rot, step, radius, gap)
            if best:
                break
        if best is None:
            raise RuntimeError(f"no room for {ref} near {target}")
        _, r, x, y = best
        fp.SetOrientationDegrees(r)
        fp.SetPosition(mm(x, y))
        return fp

    def _search(self, fp, ref, target, rot, step, radius, gap):
        best = None
        for r in (rot, rot + 90):
            fp.SetOrientationDegrees(r)
            fp.SetPosition(mm(0, 0))
            bx = self.box(ref)
            w, h = bx[2] - bx[0], bx[3] - bx[1]
            ox, oy = -bx[0], -bx[1]  # courtyard offset from origin
            n = int(radius / step)
            for ring in range(n):
                cands = []
                for i in range(-ring, ring + 1):
                    for j in (-ring, ring):
                        cands += [(i, j), (j, i)]
                found = None
                for i, j in sorted(set(cands), key=lambda t: t[0] ** 2 + t[1] ** 2):
                    cx, cy = target[0] + i * step - w / 2, target[1] + j * step - h / 2
                    if self._free((cx, cy, cx + w, cy + h), ignore=(ref,), gap=gap):
                        found = (cx, cy)
                        break
                if found:
                    d = (found[0] + w / 2 - target[0]) ** 2 + (found[1] + h / 2 - target[1]) ** 2
                    if best is None or d < best[0]:
                        best = (d, r, found[0] + ox, found[1] + oy)
                    break
        return best

    ROW_REFS = ()

    def refs_to_fab(self):
        """Keep reference designators on the fab layer (the module is too
        dense for readable silkscreen); JLC assembly doesn't need them."""
        for fp in self.fps.values():
            fp.Reference().SetLayer(pcbnew.B_Fab if fp.IsFlipped() else pcbnew.F_Fab)
            fp.Value().SetVisible(False)

    def text(self, s, x, y, size=0.8, rot=0, layer=None):
        t = pcbnew.PCB_TEXT(self.board)
        t.SetText(s)
        t.SetPosition(mm(x, y))
        t.SetLayer(layer if layer is not None else pcbnew.F_SilkS)
        t.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size), pcbnew.FromMM(size)))
        t.SetTextThickness(pcbnew.FromMM(size * 0.15))
        t.SetTextAngleDegrees(rot)
        self.board.Add(t)
        return t

    def outside(self):
        return [r for r in self.fps if (lambda b: b[0] < 0 or b[1] < 0 or b[2] > self.w or b[3] > self.h)(self.box(r))]

    def add_footprint(self, fpid, x, y, rot=0, ref="", side="F"):
        """A footprint that isn't in the schematic (mounting holes, logos)."""
        lib, name = fpid.split(":", 1)
        fp = pcbnew.FootprintLoad(lib_path(lib), name)
        fp.SetReference(ref)
        fp.Reference().SetVisible(False)
        fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_BOARD_ONLY | pcbnew.FP_EXCLUDE_FROM_BOM
                         | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
        self.board.Add(fp)
        if side == "B":
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetOrientationDegrees(rot)
        fp.SetPosition(mm(x, y))
        self.fps[ref or f"_{len(self.fps)}"] = fp
        return fp

    def zone(self, net, layer, margin=0.3, priority=0, rect=None, power=False):
        """Copper pour; whole board unless rect=(x0, y0, x1, y1) in board mm.
        power=True: SMD pads join the pour solidly (thermal spokes would sit in
        the high-current path), through-hole pins keep spokes for soldering."""
        z = pcbnew.ZONE(self.board)
        z.SetLayer(layer)
        z.SetNet(self.nets.get(net) or self.nets["/" + net])
        z.SetAssignedPriority(priority)
        z.SetLocalClearance(pcbnew.FromMM(0.35))  # >= the 48 V netclass clearance
        z.SetMinThickness(pcbnew.FromMM(0.2))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL if power else pcbnew.ZONE_CONNECTION_THERMAL)
        ol = z.Outline()
        ol.NewOutline()
        m = margin
        x0, y0, x1, y1 = rect or (0, 0, self.w, self.h)
        x0, y0, x1, y1 = max(x0, m), max(y0, m), min(x1, self.w - m), min(y1, self.h - m)
        for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
            ol.Append(mm(x, y).x, mm(x, y).y)
        self.board.Add(z)
        return z

    def no_tracks(self, layer, rect):
        """Rule area on `layer` over rect (board mm) where no tracks may run:
        keeps a pour there in one piece. Vias, pads and pours stay allowed.
        Freerouting gets it as a keep-out."""
        z = pcbnew.ZONE(self.board)
        z.SetIsRuleArea(True)
        z.SetDoNotAllowTracks(True)
        z.SetDoNotAllowVias(False)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        z.SetDoNotAllowZoneFills(False)
        z.SetLayer(layer)
        ol = z.Outline()
        ol.NewOutline()
        x0, y0, x1, y1 = rect
        for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
            ol.Append(mm(x, y).x, mm(x, y).y)
        self.board.Add(z)
        return z

    def unplaced(self):
        return sorted(set(self.comps) - set(self.fps), key=lambda r: (r.rstrip("0123456789"), len(r), r))

    def save(self, path, netclasses=None):
        path = pathlib.Path(path)
        missing = [r for r in self.unplaced() if self.comps[r]["footprint"]]
        if missing:
            print("NOT PLACED:", ", ".join(missing))
        self.board.BuildConnectivity()   # else the filler can't tell which islands are orphaned
        filler = pcbnew.ZONE_FILLER(self.board)
        filler.Fill(self.board.Zones())
        self.board.Save(str(path))
        if netclasses:
            self._write_netclasses(path.with_suffix(".kicad_pro"), netclasses)
        path.with_suffix(".kicad_dru").write_text(DRU, encoding="utf-8")
        print(f"saved {path}")

    @staticmethod
    def _write_netclasses(pro, netclasses):
        data = json.loads(pro.read_text(encoding="utf-8")) if pro.exists() else {}
        classes, patterns = [], []
        for name, spec in netclasses.items():
            track, clearance, nets = spec[:3]
            via_d, via_drill = spec[3:5] if len(spec) >= 5 else (0.6, 0.3)
            classes.append({"name": name, "track_width": track, "clearance": clearance,
                            "via_diameter": via_d, "via_drill": via_drill,
                            "diff_pair_width": 0.2, "diff_pair_gap": 0.2,
                            "pcb_color": "rgba(0, 0, 0, 0.000)",
                            "schematic_color": "rgba(0, 0, 0, 0.000)",
                            "wire_width": 6, "bus_width": 12, "line_style": 0,
                            "microvia_diameter": 0.3, "microvia_drill": 0.1, "priority": 0})
            patterns += [{"netclass": name, "pattern": "/" + n} for n in nets]
        data.setdefault("net_settings", {})
        data["net_settings"]["classes"] = classes
        data["net_settings"]["netclass_patterns"] = patterns
        data["net_settings"]["meta"] = {"version": 4}
        rules = data.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rules", {})
        rules["min_hole_to_hole"] = 0.3   # JLC via-to-via hole spacing is well below this
        # boards are always placed from fresh library footprints; a mismatch can
        # only be tools/silk_cleanup.py trimming outline lines on an instance
        sev = data["board"]["design_settings"].setdefault("rule_severities", {})
        sev["lib_footprint_mismatch"] = "ignore"
        pro.write_text(json.dumps(data, indent=2), encoding="utf-8")
