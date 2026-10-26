"""Place an add-on board: addon-keys or addon-encoders. Placement only, not routed yet.

Run with KiCad's Python from the repo root, once per board (after gen_addon.py):
    "C:/Program Files/KiCad/10.0/bin/python.exe" hardware/addon/place_addon.py keys
    "C:/Program Files/KiCad/10.0/bin/python.exe" hardware/addon/place_addon.py encoders

Front view, x right, y down; the front faces the room (keys, encoders, radar,
LEDs, SHT40) and, on the tab, the panel's back (the 2x4 header only). The tab
behind the panel carries the electronics on its back (wall) side, inside the
wall box and away from the SHT40.
- Enclosure (front): 85.6 mm wide (the bar plus 1.1 mm walls), a 5 mm border,
  then 1 mm around each 20 x 20 mm keycap or 25 mm knob: 32 mm tall for the
  keys, 37 mm for the encoders. Three keys spread evenly inside the border:
  26.8 mm apart, centred 16 mm below the panel's bottom edge.
- Bar: 83.4 mm wide, centred on the panel as fitted (it sat flush with the
  panel's left edge and 0.9 mm short of its right), 1.1 mm inside the
  enclosure all round. It ends 1.1 mm above a 5 mm bottom border.
- keys: switches turned 90 deg counter-clockwise, so the socket pads stay
  inside the switch outline and the LED slot faces right. The radar is on a
  break-away piece at the bar's left end, its top edge 0.3 mm below key 1's
  switch body, so the bottom border with the radar is ~17.4 mm. The break line
  steps up under it (a notch in the bar's bottom edge, hidden behind the 5 mm
  border when the piece is snapped off). Three 4 mm bridges with 0.5 mm
  mouse-bite holes; the five radar tracks cross the left one between its two
  end holes.
- encoders: the knobs (25 mm) as far apart as the enclosure allows: 5 mm
  border, 1 mm gap, knob ... knob, 1 mm, 5 mm, so 48.6 mm between centres.
  The same top to bottom, so the bar is 5 mm taller than the keys board's and
  the encoders sit 2.5 mm below its key row. The radar sits midway between
  them, level with them (no break-away piece needed).
  Encoders this far out can't share a board with the keys: their pins and tab
  slots land on the switches' holes and pads in every rotation.
- SHT40 (bare, 1.5 mm DFN) on a U-tab at the bar's right end, beside key 3 or
  encoder 2, with its capacitor; free lower end near the bottom edge.
- Panel: 86.5 x 86.5 x 13.6 mm (Guition's drawing). Its H1 header (2x4,
  2.54 mm) was measured: centre 23.7 mm left of and 16.2 mm below the
  panel's centre, seen from the front (HDR_*).
- The tab stays clear of the stock back cover's screw near the panel's
  lower-left corner (front view, about 37 mm left of and 29 mm below the centre).
- Still a placeholder: the tab's outline.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hardware" / "tools"))
import pcbnew  # noqa: E402
import pcbbuild  # noqa: E402
from pcbbuild import Board  # noqa: E402

BUILD = sys.argv[1] if len(sys.argv) > 1 else ""
if BUILD not in ("keys", "encoders"):
    sys.exit("usage: place_addon.py keys|encoders")
PROJECT = f"addon-{BUILD}"
HERE = ROOT / "hardware" / PROJECT

# --- panel geometry (measure the header before ordering) -------------------------------------------
W = 86.5             # panel width (Guition drawing)
# H1 measured on a panel (front view): the header body starts 17 mm from the left edge and
# 22 mm from the bottom edge, so with a 5.08 x 10.16 mm body its centre is 19.54 mm from the
# left and 27.08 mm from the bottom. The Printables replacement cover 1487412 has its
# window centred within 0.1 mm of that.
HDR_DX = 17.0 + 2.54 - W / 2   # -23.71: H1 centre from the panel's centre line
HDR_DY = W / 2 - (22.0 + 5.08)  # 16.17: H1 centre below the panel's centre
HDR_Y = 9.5          # H1 centre below the tab's top edge (room for the wire pads above-left)
TAB_X0 = -33.5       # tab's left edge from the panel's centre line: clear of the back-cover screw
TAB_W = 28.5         # tab width (room for the electronics on its back)

CX = W / 2                      # panel centre line (the tab and header are placed from it)
# The bar: test-fitted, it sat flush with the panel's left edge and 0.9 mm short of its
# right edge, so it comes in 0.9 mm on the left to centre it, plus 1.1 mm on both sides
# for the enclosure walls.
BL, BR = 2.0, W - 1.1           # bar's left and right edges (board mm)
EC = (BL + BR) / 2              # bar / enclosure centre line
WALL, BORDER, GAP, CAP = 1.1, 5.0, 1.0, 20.0
E_INNER = (BR - BL) + 2 * WALL - 2 * BORDER          # 75.6: inside the enclosure's border
KP = (E_INNER - 2 * GAP - CAP) / 2                   # 26.8: key pitch, outer caps 1 mm from the border
YB0 = HDR_Y + W / 2 - HDR_DY    # bar top = panel bottom edge = enclosure top edge
YK = YB0 + BORDER + GAP + CAP / 2                    # key row
KNOB = 25.0
YE = YB0 + BORDER + GAP + KNOB / 2                   # encoder row, 2.5 mm below the key row
EX0, EX1 = BL - WALL, BR + WALL # enclosure's outer edges
ENC_X = [EX0 + BORDER + GAP + KNOB / 2, EX1 - BORDER - GAP - KNOB / 2]   # 48.6 mm apart
FACE = CAP if BUILD == "keys" else KNOB              # keycap or knob, with 1 mm gaps and the border round it
YBR = YB0 + BORDER + 2 * GAP + FACE + BORDER - WALL  # bar bottom: 1.1 mm above a 5 mm border
# break-away radar piece at the bar's left end, as close to key 1 as the switch allows: the
# radar's top edge 0.3 mm below key 1's switch body. Under it the break line moves up to just
# below key 1's lowest copper (its socket pad, 8.64 mm below the key centre), notching the
# bar's bottom edge; in a build without the radar the notch hides behind the 5 mm border.
RX = BL + 0.3 + 10.0            # radar centre x: 0.3 mm in from the bar's left edge
RY = YK + 6.98 + 0.3 + 10.0     # radar centre y: top edge 0.3 mm below key 1's switch body
YNB = YK + 8.64 + 0.36          # the bar's edge above the piece (top of the notch)
YPT = YNB + 1.0                 # piece top: 1 mm routed gap
YPB = RY + 10.0                 # piece bottom = the radar's bottom edge
PX0, PX1 = BL, RX + 10.5        # piece left and right edges
# 4 mm bridges: two across the top gap, clear of key 1's socket and its courtyard (x 9.9-16.3,
# reaching 8.9 mm below the key centre), and one across the gap on the piece's right side.
# The first, by the radar's header column, carries its five tracks.
BRIDGES = [RX - 6.8, RX + 6.7]  # x centres, top gap
BR_Y = YPT + 2.45               # y centre, right-side gap
TX0, TX1 = CX + TAB_X0, CX + TAB_X0 + TAB_W

if BUILD == "keys":
    OUTLINE = [(TX0, 0), (TX1, 0), (TX1, YB0), (BR, YB0), (BR, YBR), (PX1 + 1.0, YBR), (PX1 + 1.0, BR_Y + 2),
               (PX1, BR_Y + 2), (PX1, YPB), (PX0, YPB), (PX0, YPT), (BRIDGES[0] - 2, YPT),
               (BRIDGES[0] - 2, YNB), (BL, YNB), (BL, YB0), (TX0, YB0)]
    BOTTOM = YPB
else:
    OUTLINE = [(TX0, 0), (TX1, 0), (TX1, YB0), (BR, YB0), (BR, YBR), (BL, YBR), (BL, YB0), (TX0, YB0)]
    BOTTOM = YBR
# the gaps between the bridges: closed cut-outs (the second one is L-shaped, round the corner)
GAPS = [[(BRIDGES[0] + 2, YNB), (BRIDGES[1] - 2, YNB), (BRIDGES[1] - 2, YPT), (BRIDGES[0] + 2, YPT)],
        [(BRIDGES[1] + 2, YNB), (PX1 + 1.0, YNB), (PX1 + 1.0, BR_Y - 2), (PX1, BR_Y - 2), (PX1, YPT),
         (BRIDGES[1] + 2, YPT)]]

# SHT40 U-tab at the bar's right end: from key 3's LED pads (x +KP + 5.955 from the middle
# key) or encoder 2's right mounting-tab pad (+6.9) to the board edge. Two 1 mm slots joined
# across the bottom; the tongue hangs from the top and is free at its lower end, near the
# bar's bottom edge. 1 mm of board stays outside the right slot.
RIGHT_CU = EC + KP + 5.955 if BUILD == "keys" else ENC_X[1] + 6.9
UL, UR = RIGHT_CU + 0.85, BR - 1.0                   # outer edges of the U
UT, UB = YBR - 23.9, YBR - 1.9                       # top of the side slots, bottom of the U
USLOT = [(UL, UT), (UL + 1.0, UT), (UL + 1.0, UB - 1.0), (UR - 1.0, UB - 1.0), (UR - 1.0, UT),
         (UR, UT), (UR, UB), (UL, UB)]
TONGUE_X = (UL + 1.0 + UR - 1.0) / 2

if BUILD == "keys":
    pcbbuild.DRU += """
# The radar sits right under key 1, so on its 2.5 mm header it reaches over key 1's lower
# edge, the notch in the bar and the break-away bridges (their mouse-bite holes).
(rule "radar floats over the break line"
  (constraint courtyard_clearance (min -25mm))
  (condition "A.Reference == 'U3' || B.Reference == 'U3'"))

# Each key LED sits in its switch's LED slot, under the switch.
(rule "LED in the switch's LED slot"
  (constraint courtyard_clearance (min -10mm))
  (condition "A.Reference == 'D*' && B.Reference == 'SW*'"))
"""

b = Board(HERE / f"{PROJECT}.kicad_sch", W, BOTTOM, layers=2, outline=OUTLINE)
LABELS = []


def label(s, x, y, size=1.0, back=False):
    t = b.text(s, x, y, size=size, layer=pcbnew.B_SilkS if back else pcbnew.F_SilkS)
    t.SetTextThickness(pcbnew.FromMM(0.15))
    if back:
        t.SetMirrored(True)
    t.SetLocked(True)
    LABELS.append(t)
    return t


def cutout(pts):
    for a, c in zip(pts, pts[1:] + pts[:1]):
        seg = pcbnew.PCB_SHAPE(b.board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pcbbuild.mm(*a))
        seg.SetEnd(pcbbuild.mm(*c))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(pcbnew.FromMM(0.1))
        b.board.Add(seg)


if BUILD == "keys":
    # switches turned 90 deg counter-clockwise: socket pads inside the outline, LED slot to the right
    for i, dx in enumerate((-KP, 0.0, KP)):
        b.place(f"SW{i + 1}", EC + dx, YK, 90)
        b.place(f"D{i + 1}", EC + dx + 5.08, YK, 90)        # in the LED slot, cathode (pad 1) down
        label(f"K{i + 1}", EC + dx, YK - 8.3)
    # break-away radar piece
    for g in GAPS:
        cutout(g)
    b.add_footprint("addon:MouseBite_4mm_Traces", BRIDGES[0], YNB, ref="MB1")
    b.add_footprint("addon:MouseBite_4mm", BRIDGES[1], YNB, ref="MB2")
    b.add_footprint("addon:MouseBite_4mm", PX1 + 1.0, BR_Y, rot=90, ref="MB3")
    # radar turned 180 deg from Hi-Link's figure: header column on the left, all five pins on the piece
    b.place("U3", RX, RY, 180)
    label("RADAR - break away", RX + 2.0, YPB - 1.2, size=0.8, back=True)
else:
    for i, x in enumerate(ENC_X):
        b.place(f"ENC{i + 1}", x, YE, 0)
        label(f"E{i + 1}", x, YE - 9.6)
    # radar between the knobs, centred on them, as in Hi-Link's figure 6-1
    b.place("U3", EC, YE, 0)
    label("RADAR", EC, YE + 11.2, size=0.8)

# --- SHT40 on the U-tab --------------------------------------------------------------------------------
cutout(USLOT)
b.place("U5", TONGUE_X, UB - 3.5, 90)                        # pads (extended) run along the tongue
b.place("C4", TONGUE_X, UB - 9.5, 90)
label("SHT40", TONGUE_X, UB + 1.0, size=0.8)

# --- enclosure, for reference only (User.Drawings): its outline (and, for the keys, the
# outline with the radar's border), the 5 mm border, the 20 mm keycaps or the 25 mm knobs -----------
def dwg(shape, *args):
    s = pcbnew.PCB_SHAPE(b.board)
    if shape == "rect":
        x0, y0, x1, y1 = args
        s.SetShape(pcbnew.SHAPE_T_RECT)
        s.SetStart(pcbbuild.mm(x0, y0))
        s.SetEnd(pcbbuild.mm(x1, y1))
    else:
        x, y, r = args
        s.SetShape(pcbnew.SHAPE_T_CIRCLE)
        s.SetCenter(pcbbuild.mm(x, y))
        s.SetEnd(pcbbuild.mm(x + r, y))
    s.SetLayer(pcbnew.Dwgs_User)
    s.SetWidth(pcbnew.FromMM(0.15))
    b.board.Add(s)


dwg("rect", EX0, YB0, EX1, YBR + WALL)                                     # 5 mm bottom border
dwg("rect", EX0 + BORDER, YB0 + BORDER, EX1 - BORDER, YBR + WALL - BORDER)  # inside the border
if BUILD == "keys":
    dwg("rect", EX0, YB0, EX1, YPB + WALL)                                 # border with the radar
    for dx in (-KP, 0.0, KP):
        dwg("rect", EC + dx - CAP / 2, YK - CAP / 2, EC + dx + CAP / 2, YK + CAP / 2)
else:
    for x in ENC_X:
        dwg("circle", x, YE, KNOB / 2)

# --- tab: 2x4 header on the front, electronics on the back ---------------------------------------------
HX = CX + HDR_DX
b.place("J1", HX, HDR_Y, 0)                                  # pads numbered as the panel's H1
label("GUITION H1", HX, HDR_Y + 7.0, size=0.8)
# top: power in on the wall side. Wire pads along the left edge; USB-C at the right
# edge, opening to the right (front view), clear of the header's pins on the back
b.place("J2", TX0 + 2.2, 3.0, -90)                           # pad 1 (+5V, square) at the top
label("+5V", TX0 + 5.0, 3.0, size=0.8, back=True)
label("GND", TX0 + 5.0, 7.6, size=0.8, back=True)
b.place("J3", TX1 - 4.5, 6.0, -90, side="B")                 # on the back: -90 points the opening to +x
b.place("R1", TX1 - 10.1, 4.0, 0, side="B")                   # CC pull-downs left of the USB-C
b.place("R2", TX1 - 10.1, 8.0, 0, side="B")
# middle: LDO (left) and co-processor (right)
b.place("U1", TX0 + 6.0, 19.5, 0, side="B")
b.place("C1", TX0 + 6.0, 26.3, 0, side="B")
b.place("U2", TX1 - 7.0, 22.0, 0, side="B")
b.place("C3", TX1 - 7.0, 15.2, 0, side="B")
b.place("C2", TX0 + 13.0, 22.0, 90, side="B")                # 3.3 V output
# bottom: a row of resistors (I2C pull-ups, LED resistors) and the programming pads
for i, ref in enumerate(r for r in ("R3", "R4", "R5", "R6", "R7") if r in b.comps):
    b.place(ref, TX0 + 3.0 + 3.2 * i, 32.0, 90, side="B")
b.place_row("J4", TX1 - 8.5, YB0 - 3.0)                      # SWIO 3V3 GND, pins running right
label("SWIO 3V3 GND", TX1 - 6.0, YB0 - 5.2, size=0.8, back=True)

print("overlaps:", b.overlaps())
print("unplaced:", b.unplaced())

for ref in [r for r in ("D1", "D2", "D3") if r in b.fps]:   # LEDs under the switches: silk never seen
    for g in list(b.fps[ref].GraphicalItems()):
        if g.GetLayer() == pcbnew.F_SilkS and not isinstance(g, pcbnew.PCB_TEXT):
            b.fps[ref].Remove(g)
b.refs_to_fab()
for fp in b.fps.values():           # JLCPCB legend minimum is 0.15 mm lines
    for g in fp.GraphicalItems():
        if (g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and not isinstance(g, pcbnew.PCB_TEXT)
                and not g.IsAnyFill() and g.GetWidth() < pcbnew.FromMM(0.15)):
            g.SetWidth(pcbnew.FromMM(0.15))

b.save(HERE / f"{PROJECT}.kicad_pcb", netclasses={
    "Supply": (0.5, 0.2, ["+5V", "+3V3", "GND"]),
    "Default": (0.25, 0.2, []),
})
