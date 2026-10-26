"""Make the add-on board's own symbols and footprints (hardware/lib/addon.*).

Run with any Python, then normalise the footprints with kicad-cli:
    python hardware/tools/addon_lib.py
    "C:/Program Files/KiCad/10.0/bin/kicad-cli.exe" fp upgrade --force hardware/lib/addon.pretty
Don't run `kicad-cli sym upgrade` on addon.kicad_sym: kicad-cli 10.0.6 then
crashes loading any schematic that embeds the upgraded symbol.

The STEP models come from the LCSC imports (hardware/tools/import_lcsc.py
C456012 C41430893 C49234235 C143790); this script keeps them and replaces the
imported footprints and symbols with the ones below.

- HLK-LD2402 (symbol + footprint): Hi-Link LD2402 radar, manual p. 7 (pins)
  and p. 37 (drawing). 20 x 20 mm, J2 = 5 pins at 2.54 mm, column 1.53 mm in
  from one edge, first pin 1.62 mm from the corner. Drawn as in Hi-Link's
  figure 6-1 (antenna side up, header on the right, pin 5 RX at the top):
  1 VCC, 2 OUT (IO), 3 GND, 4 TX, 5 RX. Soldered straight on its own 2.5 mm
  header, so no 3D model.
- SW_MX_Hotswap_CPG151101S11: MX switch (HanElectricity CPG151101D13, 3-pin,
  13.96 mm body) in a CPG151101S11-16 hot-swap socket on the back. NPTH 4.0
  centre, 1.75 pegs (5-pin switches fit too), 3.0 at the switch pins. Socket
  pads from the LCSC land pattern (C41430893) mirrored to the back.
  Origin = switch centre, pins towards -y, LED slot towards +y.
- RotaryEncoder_Bourns_PEC11R-4xxxF-Sxxxx_Vertical: Bourns PEC11R datasheet,
  PEC11R-4xxxF-Sxxxx land pattern: A C B at y +7.5, switch at y -7.0,
  mounting tabs at x +-5.7 (13.2 mm over the slot edges), 1.1 mm holes with
  2.0 mm pads for hand soldering. Origin = shaft.
- Guition_H1_2x04_P2.54mm_Mating: the male 2x4 header into the panel's H1
  socket, pads numbered like the H1 pins they plug into (see below).
- Sensirion_DFN-4_1.5x1.5mm_P0.8mm_SHT4x_HandSolder: KiCad's SHT4x land pattern
  with the pads 0.5 mm longer outwards.
- SOIC-16_3.9x9.9mm_P1.27mm_HandSolder: KiCad's SOIC-16 with the pads 0.8 mm
  longer outwards, for the CH32V003A4M6.
- USB_C_Receptacle_SHOU-HAN_TYPE-C-6P: the LCSC import of C456012 with the
  shell pads renamed SH (KiCad's USB_C_Receptacle_PowerOnly_6P symbol).
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hardware" / "tools"))
from schgen import Str, dump, find, find_all, parse, uid  # noqa: E402

LIB = ROOT / "hardware" / "lib"
PRETTY = LIB / "addon.pretty"
MODELS = "${KIPRJMOD}/../lib/addon.3dshapes/"
STD = pathlib.Path(r"C:\Program Files\KiCad\10.0\share\kicad\footprints")


def f(v):
    v = round(v, 4)
    return str(int(v)) if v == int(v) else str(v)


def font(size=1.0):
    return ["effects", ["font", ["size", f(size), f(size)], ["thickness", f(size * 0.15)]]]


def line(x0, y0, x1, y1, layer, w=0.1):
    return ["fp_line", ["start", f(x0), f(y0)], ["end", f(x1), f(y1)],
            ["stroke", ["width", f(w)], ["type", "solid"]], ["layer", Str(layer)], ["uuid", Str(uid())]]


def rect(x0, y0, x1, y1, layer, w=0.1):
    return ["fp_rect", ["start", f(x0), f(y0)], ["end", f(x1), f(y1)],
            ["stroke", ["width", f(w)], ["type", "solid"]], ["fill", "no"], ["layer", Str(layer)],
            ["uuid", Str(uid())]]


def circle(x, y, r, layer, w=0.1):
    return ["fp_circle", ["center", f(x), f(y)], ["end", f(x + r), f(y)],
            ["stroke", ["width", f(w)], ["type", "solid"]], ["fill", "no"], ["layer", Str(layer)],
            ["uuid", Str(uid())]]


def text(kind, s, x, y, layer, hide=False, size=1.0):
    return ["property", Str(kind), Str(s), ["at", f(x), f(y), "0"], ["layer", Str(layer)],
            ["uuid", Str(uid())], font(size)] + ([["hide", "yes"]] if hide else [])


def tht(num, x, y, d, drill, shape="circle"):
    return ["pad", Str(num), "thru_hole", shape, ["at", f(x), f(y)], ["size", f(d), f(d)],
            ["drill", f(drill)], ["layers", Str("*.Cu"), Str("*.Mask")], ["uuid", Str(uid())]]


def slot(num, x, y, w, h, dw, dh):
    return ["pad", Str(num), "thru_hole", "roundrect", ["at", f(x), f(y)], ["size", f(w), f(h)],
            ["drill", "oval", f(dw), f(dh)], ["layers", Str("*.Cu"), Str("*.Mask")],
            ["roundrect_rratio", "0.25"], ["uuid", Str(uid())]]


def npth(x, y, d):
    return ["pad", Str(""), "np_thru_hole", "circle", ["at", f(x), f(y)], ["size", f(d), f(d)],
            ["drill", f(d)], ["layers", Str("*.Cu"), Str("*.Mask")], ["uuid", Str(uid())]]


def smd(num, x, y, w, h, side="B"):
    return ["pad", Str(num), "smd", "roundrect", ["at", f(x), f(y)], ["size", f(w), f(h)],
            ["layers", Str(f"{side}.Cu"), Str(f"{side}.Paste"), Str(f"{side}.Mask")],
            ["roundrect_rratio", "0.1"], ["uuid", Str(uid())]]


def model(name, offset=(0, 0, 0), rotate=(0, 0, 0)):
    return ["model", Str(MODELS + name), ["offset", ["xyz"] + [f(v) for v in offset]],
            ["scale", ["xyz", "1", "1", "1"]], ["rotate", ["xyz"] + [f(v) for v in rotate]]]


def footprint(name, descr, attr, items):
    return ["footprint", Str(name), ["version", "20260206"], ["generator", Str("addon_lib")],
            ["generator_version", Str("10.0")], ["layer", Str("F.Cu")], ["descr", Str(descr)],
            ["attr"] + attr] + items


def save(tree):
    (PRETTY / f"{tree[1]}.kicad_mod").write_text(dump(tree) + "\n", encoding="utf-8")
    print("wrote", tree[1])


# --- HLK-LD2402 ------------------------------------------------------------------
LD_PINS = {"1": "VCC", "2": "OUT", "3": "GND", "4": "TX", "5": "RX"}
LD_X = 10 - 1.53                                     # header column, 1.53 mm in from the right edge


def ld_y(n):                                         # pin 5 1.62 mm below the top edge
    return -10 + 1.62 + (5 - int(n)) * 2.54


items = [text("Reference", "REF**", 0, -11.2, "F.SilkS"),
         text("Value", "HLK-LD2402", 0, 11.2, "F.Fab"),
         text("Footprint", "", 0, 0, "F.Fab", hide=True),
         text("Datasheet", "", 0, 0, "F.Fab", hide=True)]
items += [rect(-10, -10, 10, 10, "F.Fab"),
          rect(-8.0, -7.5, -3.0, -5.0, "F.Fab"),     # patch antennas (upper left, lower right)
          rect(3.0, 5.0, 8.0, 7.5, "F.Fab"),
          rect(-10.25, -10.25, 10.25, 10.25, "F.CrtYd", 0.05),
          # silkscreen: only the header's outline and a pin-1 mark (the module covers other footprints)
          line(LD_X - 1.2, ld_y("5") - 1.4, LD_X + 1.2, ld_y("5") - 1.4, "F.SilkS", 0.15),
          line(LD_X - 1.2, ld_y("1") + 1.4, LD_X + 1.2, ld_y("1") + 1.4, "F.SilkS", 0.15),
          line(LD_X + 1.4, ld_y("1") - 0.6, LD_X + 1.4, ld_y("1") + 0.6, "F.SilkS", 0.15)]
for n in LD_PINS:
    items.append(tht(n, LD_X, ld_y(n), 1.7, 1.0, "rect" if n == "1" else "circle"))
save(footprint("HLK-LD2402", "Hi-Link HLK-LD2402 24 GHz radar module, 20x20 mm, J2 1x5 2.54 mm "
               "(1 VCC, 2 OUT, 3 GND, 4 TX, 5 RX), as in Hi-Link's figure 6-1", ["through_hole"], items))

# --- MX switch in a hot-swap socket ------------------------------------------------
# LCSC CPG151101S11-16 land pattern: holes at (-3.18,-1.27) / (3.17,1.27), pads
# 2.5 x 2.55 at (-6.72,-1.27) / (6.72,1.27), seen from the socket side. On the back
# of a switch at the origin (pins at (-3.81,-2.54) and (2.54,-5.08)) the socket
# is mirrored and its centre sits at (-0.64,-3.81).
SX, SY = -0.64, -3.81
items = [text("Reference", "REF**", 0, -8.2, "F.SilkS"),
         text("Value", "MX hot-swap", 0, 8.2, "F.Fab"),
         text("Footprint", "", 0, 0, "F.Fab", hide=True),
         text("Datasheet", "", 0, 0, "F.Fab", hide=True)]
items += [npth(0, 0, 4.0), npth(-5.08, 0, 1.75), npth(5.08, 0, 1.75),
          npth(-3.81, -2.54, 3.0), npth(2.54, -5.08, 3.0),
          smd("1", SX + 6.72, SY - 1.27, 2.5, 2.55), smd("2", SX - 6.72, SY + 1.27, 2.5, 2.55),
          rect(-6.98, -6.98, 6.98, 6.98, "F.Fab"),               # switch body at the board
          rect(-1.6, 4.28, 1.6, 6.98, "F.Fab"),                  # LED slot (1206 LED goes here)
          rect(-7.25, -7.25, 7.25, 7.25, "F.CrtYd", 0.05),   # no silk: it would sit under the switch
          rect(SX - 5.45, SY - 2.95, SX + 5.45, SY + 2.95, "B.Fab"),   # socket body 10.9 x 5.89
          rect(SX - 8.25, SY - 3.2, SX + 8.25, SY + 3.2, "B.CrtYd", 0.05),
          # switch: the LCSC model of CPG151101D13 is centred on the switch;
          # socket model turned over onto the back of a 1.6 mm board
          model("KEY-TH_L15.6-W14.0-H15.3.step", (0, 0, 0), (0, 0, 270)),
          model("SMD_KEYBOARD-SW.step", (SX, -SY, -1.6), (0, 180, 0))]
save(footprint("SW_MX_Hotswap_CPG151101S11", "MX switch (HanElectricity CPG151101D13) in a "
               "CPG151101S11-16 hot-swap socket on the back; LED slot at +y", ["smd"], items))

# --- Bourns PEC11R vertical with push switch ---------------------------------------
items = [text("Reference", "REF**", 0, -9.6, "F.SilkS"),
         text("Value", "PEC11R-4215F-S0024", 0, 10.2, "F.Fab"),
         text("Footprint", "", 0, 0, "F.Fab", hide=True),
         text("Datasheet", "", 0, 0, "F.Fab", hide=True)]
items += [tht("A", -2.5, 7.5, 2.0, 1.1, "rect"), tht("C", 0, 7.5, 2.0, 1.1), tht("B", 2.5, 7.5, 2.0, 1.1),
          tht("S1", -2.5, -7.0, 2.0, 1.1), tht("S2", 2.5, -7.0, 2.0, 1.1),
          slot("MP", -5.7, 0, 2.4, 3.2, 1.9, 2.7), slot("MP", 5.7, 0, 2.4, 3.2, 1.9, 2.7),   # 0.25 mm ring
          rect(-6.25, -6.7, 6.25, 6.7, "F.Fab"), circle(0, 0, 3.0, "F.Fab"),
          line(-6.3, -6.75, -3.9, -6.75, "F.SilkS", 0.15), line(3.9, -6.75, 6.3, -6.75, "F.SilkS", 0.15),
          line(-6.3, 6.75, -3.9, 6.75, "F.SilkS", 0.15), line(3.9, 6.75, 6.3, 6.75, "F.SilkS", 0.15),
          line(-6.3, -6.75, -6.3, -2.0, "F.SilkS", 0.15), line(-6.3, 2.0, -6.3, 6.75, "F.SilkS", 0.15),
          line(6.3, -6.75, 6.3, -2.0, "F.SilkS", 0.15), line(6.3, 2.0, 6.3, 6.75, "F.SilkS", 0.15),
          rect(-7.25, -8.25, 7.25, 8.75, "F.CrtYd", 0.05),
          # LCSC model of C143790: its origin is midway between the pin rows, 0.25 below the tabs
          model("SW-TH_5P-L12.5-W13.4-P2.50-LS14.5.step", (0, -0.25, 0))]
save(footprint("RotaryEncoder_Bourns_PEC11R-4xxxF-Sxxxx_Vertical", "Bourns PEC11R-4xxxF-Sxxxx "
               "12 mm incremental encoder with push switch, vertical, hand-solder pads",
               ["through_hole"], items))

# --- male 2x4 header that plugs into the panel's H1 ------------------------------------------
# Guition schematic (support zip, "5-IO pin distribution/2.png"): H1 is a 2x4 female
# socket, 1 GND, 2 GND, 3 IO40 (relay 1), 4 U0RXD, 5 IO2 (relay 2), 6 U0TXD, 7 IO1
# (relay 3), 8 5V; pin 1 is the top of the column nearer the panel's centre.
# Our header faces the panel from the front, so the pads here are numbered like
# the H1 pin each one plugs into: seen from the front (KiCad's top view), the odd
# column is on the right (towards the panel's centre) and pin 1 at the top.
# Origin = header centre.
items = [text("Reference", "REF**", 0, -6.2, "F.SilkS"),
         text("Value", "Guition H1", 0, 6.2, "F.Fab"),
         text("Footprint", "", 0, 0, "F.Fab", hide=True),
         text("Datasheet", "", 0, 0, "F.Fab", hide=True)]
for n in range(1, 9):
    x = 1.27 if n % 2 else -1.27
    y = -3.81 + 2.54 * ((n - 1) // 2)
    items.append(tht(str(n), x, y, 1.7, 1.0, "rect" if n == 1 else "circle"))
items += [rect(-2.54, -5.08, 2.54, 5.08, "F.Fab"),
          rect(-2.6, -5.14, 2.6, 5.14, "F.SilkS", 0.15),
          line(2.9, -5.4, 2.9, -2.6, "F.SilkS", 0.15),           # pin-1 mark on the odd (right) side
          rect(-3.05, -5.6, 3.05, 5.6, "F.CrtYd", 0.05),
          ["model", Str("${KICAD10_3DMODEL_DIR}/Connector_PinHeader_2.54mm.3dshapes/"
                        "PinHeader_2x04_P2.54mm_Vertical.step"),
           ["offset", ["xyz", "-1.27", "3.81", "0"]], ["scale", ["xyz", "1", "1", "1"]],
           ["rotate", ["xyz", "0", "0", "0"]]]]
save(footprint("Guition_H1_2x04_P2.54mm_Mating", "Male 2x04 2.54 mm header that plugs into the "
               "Guition ESP32-S3-4848S040's H1 socket from the front; pads numbered as H1 "
               "(odd column towards the panel's centre)", ["through_hole"], items))

# --- mouse bites for the break-away radar piece --------------------------------------------------
# 0.5 mm non-plated holes on the board edge line across a 4 mm bridge. "_Traces" keeps
# only the two end holes, so up to five 0.2 mm tracks can cross between them; snap it
# after scoring the copper side with a knife.
for name, xs in (("MouseBite_4mm", [-1.6, -0.8, 0.0, 0.8, 1.6]), ("MouseBite_4mm_Traces", [-1.6, 1.6])):
    items = [text("Reference", "REF**", 0, -1.2, "F.Fab", hide=True),
             text("Value", name, 0, 1.2, "F.Fab", hide=True),
             text("Footprint", "", 0, 0, "F.Fab", hide=True),
             text("Datasheet", "", 0, 0, "F.Fab", hide=True)]
    items += [npth(x, 0, 0.5) for x in xs]
    save(footprint(name, "Break-away bridge, 4 mm: 0.5 mm holes on the board edge line", ["board_only",
                   "exclude_from_pos_files", "exclude_from_bom"], items))

# --- SHT40 with longer pads -----------------------------------------------------------------
# KiCad's Sensirion DFN-4 1.5 x 1.5 mm land pattern (pads 0.5 x 0.3 at x +-0.7) with each
# pad 0.5 mm longer outwards, so solder can be fed and heated from outside the package
# (hot air or a hot plate is still the easy way). On the board it is turned 90 deg, so
# the extensions run along the narrow U-tab.
tree = parse((STD / "Sensor_Humidity.pretty" / "Sensirion_DFN-4_1.5x1.5mm_P0.8mm_SHT4x_NoCentralPad.kicad_mod")
             .read_text(encoding="utf-8"))
tree[1] = Str("Sensirion_DFN-4_1.5x1.5mm_P0.8mm_SHT4x_HandSolder")
for prop in find_all(tree, "property"):
    if prop[1] == "Value":
        prop[2] = Str("Sensirion_DFN-4_1.5x1.5mm_P0.8mm_SHT4x_HandSolder")
for pad in find_all(tree, "pad"):
    at, size = find(pad, "at"), find(pad, "size")
    x = float(at[1])
    at[1] = f(x + (0.25 if x > 0 else -0.25))
    size[1] = f(float(size[1]) + 0.5)
for g in [c for c in tree if isinstance(c, list) and c and c[0] in ("fp_line", "fp_rect", "fp_poly")]:
    lay = find(g, "layer")
    if lay and lay[1] in ("F.CrtYd", "F.SilkS"):
        tree.remove(g)
model_at = next(i for i, c in enumerate(tree) if isinstance(c, list) and c and c[0] == "model")
# pin-1 dot past the end of pad 1, on its own row, so it stays on a narrow tab
tree[model_at:model_at] = [rect(-2.0, -0.9, 2.0, 0.9, "F.CrtYd", 0.05),
                           circle(-1.75, -0.4, 0.1, "F.SilkS", 0.15)]
save(tree)

# --- SOIC-16 with longer pads ---------------------------------------------------------
tree = parse((STD / "Package_SO.pretty" / "SOIC-16_3.9x9.9mm_P1.27mm.kicad_mod").read_text(encoding="utf-8"))
tree[1] = Str("SOIC-16_3.9x9.9mm_P1.27mm_HandSolder")
for prop in find_all(tree, "property"):
    if prop[1] == "Value":
        prop[2] = Str("SOIC-16_3.9x9.9mm_P1.27mm_HandSolder")
for pad in find_all(tree, "pad"):
    at, size = find(pad, "at"), find(pad, "size")
    x, w = float(at[1]), float(size[1])
    at[1] = f(x + (0.4 if x > 0 else -0.4))
    size[1] = f(w + 0.8)
for g in [c for c in tree if isinstance(c, list) and c and c[0] in ("fp_line", "fp_rect", "fp_poly")]:
    lay = find(g, "layer")
    if lay and lay[1] == "F.CrtYd":
        tree.remove(g)
model_at = next(i for i, c in enumerate(tree) if isinstance(c, list) and c and c[0] == "model")
tree[model_at:model_at] = [rect(-4.95, -5.2, 4.95, 5.2, "F.CrtYd", 0.05)]
save(tree)

# --- USB-C power-only receptacle ----------------------------------------------------------
# The opening is at +y (the body reaches y 4.63); its silkscreen there would sit on
# the board edge, so silk lines reaching past y 4.0 are dropped.
src = PRETTY / "TYPE-C-SMD_TYPE-C-6P_1.kicad_mod"
dst = PRETTY / "USB_C_Receptacle_SHOU-HAN_TYPE-C-6P.kicad_mod"
if src.exists() or dst.exists():
    tree = parse((src if src.exists() else dst).read_text(encoding="utf-8"))
    tree[1] = Str("USB_C_Receptacle_SHOU-HAN_TYPE-C-6P")
    for pad in find_all(tree, "pad"):
        if pad[1] == "7":
            pad[1] = Str("SH")
    for g in [c for c in tree if isinstance(c, list) and c and str(c[0]).startswith("fp_")]:
        lay = find(g, "layer")
        ys = [float(p[2]) for p in g if isinstance(p, list) and p and p[0] in ("start", "end", "mid", "center")]
        if lay and lay[1] == "F.SilkS" and ys and max(ys) > 4.0:
            tree.remove(g)
    save(tree)
    if src.exists():
        src.unlink()

# imported footprints this board doesn't use (their STEP models stay)
for stale in ("KEY-TH_CPG151101D21X", "SMD_KEYBOARD-SW", "SW-TH_5P-L12.5-W13.4-P2.50-LS14.5"):
    p = PRETTY / f"{stale}.kicad_mod"
    if p.exists():
        p.unlink()


# --- symbol library: only the radar (everything else is from KiCad's libraries) -----------
def pin(etype, num, name, y):
    return ["pin", etype, "line", ["at", "-10.16", f(y), "0"], ["length", "2.54"],
            ["name", Str(name), ["effects", ["font", ["size", "1.27", "1.27"]]]],
            ["number", Str(num), ["effects", ["font", ["size", "1.27", "1.27"]]]]]


def prop(key, val, y, hide=False):
    return ["property", Str(key), Str(val), ["at", "0", f(y), "0"],
            ["effects", ["font", ["size", "1.27", "1.27"]]] + ([["hide", "yes"]] if hide else [])]


types = {"1": "power_in", "2": "output", "3": "power_in", "4": "output", "5": "input"}
sym = ["symbol", Str("HLK-LD2402"), ["pin_names", ["offset", "1.016"]], ["exclude_from_sim", "no"],
       ["in_bom", "yes"], ["on_board", "yes"],
       prop("Reference", "U", 8.89), prop("Value", "HLK-LD2402", -8.89),
       prop("Footprint", "addon:HLK-LD2402", -11.43, hide=True),
       prop("Datasheet", "https://www.manualslib.com/manual/4392645/Hi-Link-Hlk-Ld2402.html", -13.97, hide=True),
       prop("Description", "Hi-Link HLK-LD2402 24 GHz human presence radar, 3.3 V, UART 115200", -16.51, hide=True),
       ["symbol", Str("HLK-LD2402_0_1"),
        ["rectangle", ["start", "-7.62", "7.62"], ["end", "7.62", "-7.62"],
         ["stroke", ["width", "0.254"], ["type", "default"]], ["fill", ["type", "background"]]]],
       ["symbol", Str("HLK-LD2402_1_1")] + [pin(types[n], n, LD_PINS[n], 5.08 - 2.54 * (int(n) - 1))
                                             for n in LD_PINS]]
lib = ["kicad_symbol_lib", ["version", "20241209"], ["generator", Str("addon_lib")],
       ["generator_version", Str("10.0")], sym]
(LIB / "addon.kicad_sym").write_text(dump(lib) + "\n", encoding="utf-8")
print("wrote addon.kicad_sym (HLK-LD2402)")
