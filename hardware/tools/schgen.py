"""Generate KiCad schematics from Python netlists.

Each part is placed on a grid; every connected pin gets a short wire stub
ending in a local net label, so the drawing stays readable without routed
wires. Every visible pin must be either connected or listed in `nc` (which
draws a no-connect flag); anything else raises an error.

Typical use (see hardware/addon/gen_addon.py):

    sch = Schematic("node", paper="A2")
    r = sch.add("Device:R_Small", "R", "10k", at=(50, 50),
                fp="Resistor_SMD:R_0402_1005Metric", lcsc="C25744",
                pins={"1": "+3V3", "2": "EN"})
    sch.save("hardware/node/node.kicad_sch")

Then run `kicad-cli sch upgrade` to normalise the file to the current format.
"""
import pathlib
import re
import uuid as _uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
KICAD_SYMBOLS = pathlib.Path(r"C:\Program Files\KiCad\10.0\share\kicad\symbols")
LOCAL_LIBS = {"addon": ROOT / "hardware" / "lib" / "addon.kicad_sym"}
KICAD_FOOTPRINTS = KICAD_SYMBOLS.parent / "footprints"


def fp_excluded_from_bom(fp):
    """True if the footprint itself is marked "exclude from BOM" (solder
    jumpers, test points). The symbol must agree, or DRC's schematic parity
    check complains."""
    if ":" not in fp:
        return False
    lib, name = fp.split(":", 1)
    d = ROOT / "hardware" / "lib" / f"{lib}.pretty" if lib == "addon" else KICAD_FOOTPRINTS / f"{lib}.pretty"
    f = d / f"{name}.kicad_mod"
    if not f.exists():
        return False
    m = re.search(r"\(attr ([^)]*)\)", f.read_text(encoding="utf-8"))
    return bool(m and "exclude_from_bom" in m.group(1).split())
GRID = 2.54
STUB = 2.54


# --- S-expressions -------------------------------------------------------

class Str(str):
    """A quoted string token."""


def parse(text):
    tokens = re.findall(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()"]+', text)
    stack = [[]]
    for tok in tokens:
        if tok == "(":
            stack.append([])
        elif tok == ")":
            done = stack.pop()
            stack[-1].append(done)
        elif tok.startswith('"'):
            stack[-1].append(Str(tok[1:-1].replace('\\"', '"').replace("\\\\", "\\")))
        else:
            stack[-1].append(tok)
    return stack[0][0]


def dump(node, indent=0):
    pad = "\t" * indent
    if not isinstance(node, list):
        if isinstance(node, Str):   # KiCad wants line breaks in strings as \n
            return '"' + node.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
        return str(node)
    if all(not isinstance(c, list) for c in node):
        return pad + "(" + " ".join(dump(c) for c in node) + ")"
    head = [dump(c) for c in node if not isinstance(c, list)]
    out = pad + "(" + " ".join(head)
    for c in node:
        if isinstance(c, list):
            out += "\n" + dump(c, indent + 1)
    return out + "\n" + pad + ")"


def find(node, key):
    return next((c for c in node if isinstance(c, list) and c and c[0] == key), None)


def find_all(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def uid(key=None):
    """Random UUID, or a stable one derived from `key` (symbols and the root
    sheet keep the same UUID between runs, so the PCB stays linked)."""
    if key is None:
        return str(_uuid.uuid4())
    return str(_uuid.uuid5(_uuid.NAMESPACE_URL, "addon/" + key))


def fmt(v):
    v = round(v, 4)
    return str(int(v)) if v == int(v) else str(v)


# --- Symbol libraries ------------------------------------------------------

class Libraries:
    def __init__(self):
        self._libs = {}

    def _lib(self, name):
        if name not in self._libs:
            path = LOCAL_LIBS.get(name, KICAD_SYMBOLS / f"{name}.kicad_sym")
            tree = parse(path.read_text(encoding="utf-8"))
            self._libs[name] = {s[1]: s for s in find_all(tree, "symbol")}
        return self._libs[name]

    def symbol(self, lib_id):
        """Return a flattened copy of the symbol, named 'Lib:Name'."""
        lib, name = lib_id.split(":", 1)
        syms = self._lib(lib)
        sym = syms[name]
        ext = find(sym, "extends")
        if ext:
            parent = syms[ext[1]]
            props = {p[1]: p for p in find_all(sym, "property")}
            body = [c for c in parent[2:]
                    if not (isinstance(c, list) and c[0] == "property")]
            units = []
            for c in body:
                if isinstance(c, list) and c[0] == "symbol":
                    c = [c[0], Str(c[1].replace(ext[1], name, 1))] + c[2:]
                units.append(c)
            sym = ["symbol", Str(name)] + list(props.values()) + units
        return ["symbol", Str(lib_id)] + [c for c in sym[2:]]


def pins_of(sym, unit=1):
    """Yield (number, name, etype, x, y, angle, hidden) for a unit (plus common unit 0)."""
    for sub in find_all(sym, "symbol"):
        m = re.search(r"_(\d+)_(\d+)$", sub[1])
        if not m or int(m.group(1)) not in (0, unit):
            continue
        for p in find_all(sub, "pin"):
            at = find(p, "at")
            name = find(p, "name")[1]
            number = find(p, "number")[1]
            hidden = "hide" in p or any(
                isinstance(c, list) and c[0] == "hide" and c[1:] == ["yes"] for c in p)
            yield (str(number), str(name), p[1], float(at[1]), float(at[2]),
                   int(float(at[3])), hidden)


# --- Schematic -------------------------------------------------------------

class Part:
    def __init__(self, sch, lib_id, ref, value, at, fp, lcsc, pins, nc, dnp, unit, fields):
        self.sch, self.lib_id, self.ref, self.value = sch, lib_id, ref, value
        self.at, self.fp, self.lcsc, self.dnp, self.unit = at, fp, lcsc, dnp, unit
        self.pins = dict(pins or {})
        self.nc = set(nc or [])
        self.fields = fields or {}


class Schematic:
    def __init__(self, project, paper="A3", title=""):
        self.project, self.paper, self.title = project, paper, title
        self.libs = Libraries()
        self.parts = []
        self.texts = []
        self.root = uid(f"{project}/root")
        self._counters = {}

    def next_ref(self, prefix):
        taken = {p.ref for p in self.parts}
        n = self._counters.get(prefix, 0)
        while True:
            n += 1
            if f"{prefix}{n}" not in taken:
                break
        self._counters[prefix] = n
        return f"{prefix}{n}"

    def add(self, lib_id, ref, value, at, fp="", lcsc="", pins=None, nc=None,
            dnp=False, unit=1, fields=None):
        """ref may be a prefix ('R') to auto-number, or a full reference ('U1')."""
        if not re.search(r"\d", ref):
            ref = self.next_ref(ref)
        at = tuple(round(v / 1.27) * 1.27 for v in at)  # keep pins on the connection grid
        part = Part(self, lib_id, ref, value, at, fp, lcsc, pins, nc, dnp, unit, fields)
        self.parts.append(part)
        return part

    def text(self, s, at, size=2.0):
        self.texts.append((s, at, size))

    # -- output --
    def _pin_nodes(self, part, sym):
        out = []
        by_num = {}
        for num, name, etype, px, py, ang, hidden in pins_of(sym, part.unit):
            by_num.setdefault(num, (name, etype, px, py, ang, hidden))
        used = set()
        unassigned = []
        wires, labels, ncs = [], [], []
        for num, (name, etype, px, py, ang, hidden) in by_num.items():
            net = part.pins.get(num)
            if net is None and name in part.pins:
                net = part.pins[name]
                used.add(name)
            elif net is not None:
                used.add(num)
            x = part.at[0] + px
            y = part.at[1] - py
            if net is None:
                if hidden or etype == "no_connect":
                    part.nc.discard(num)  # already marked on the symbol
                    part.nc.discard(name)
                    continue
                if num in part.nc or name in part.nc:
                    ncs.append((x, y))
                    used.add(num if num in part.nc else name)
                    continue
                unassigned.append(f"{num}:{name}")
                continue
            # stub points away from the body
            dx, dy = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}[ang]
            ex, ey = x + dx * STUB, y + dy * STUB
            wires.append(((x, y), (ex, ey)))
            label_ang = {(-1, 0): 180, (1, 0): 0, (0, 1): 270, (0, -1): 90}[(dx, dy)]
            labels.append((net, ex, ey, label_ang))
        missing = (set(part.pins) | part.nc) - used
        if missing:
            raise ValueError(f"{part.ref} ({part.lib_id}): unknown pins {sorted(missing)}")
        if unassigned:
            raise ValueError(f"{part.ref} ({part.lib_id}): unassigned pins {unassigned}")
        return wires, labels, ncs

    def save(self, path):
        path = pathlib.Path(path)
        lib_symbols = {}
        body = []
        for part in self.parts:
            if part.lib_id not in lib_symbols:
                lib_symbols[part.lib_id] = self.libs.symbol(part.lib_id)
            sym = lib_symbols[part.lib_id]
            wires, labels, ncs = self._pin_nodes(part, sym)
            body.append(self._instance(part, sym))
            for (a, b) in wires:
                body.append(["wire", ["pts", ["xy", fmt(a[0]), fmt(a[1])], ["xy", fmt(b[0]), fmt(b[1])]],
                             ["stroke", ["width", "0"], ["type", "default"]], ["uuid", Str(uid())]])
            for net, x, y, ang in labels:
                just = "right" if ang in (180, 270) else "left"
                body.append(["label", Str(net), ["at", fmt(x), fmt(y), str(ang)],
                             ["effects", ["font", ["size", "1.27", "1.27"]], ["justify", just, "bottom"]],
                             ["uuid", Str(uid())]])
            for x, y in ncs:
                body.append(["no_connect", ["at", fmt(x), fmt(y)], ["uuid", Str(uid())]])
        for s, (x, y), size in self.texts:
            body.append(["text", Str(s), ["exclude_from_sim", "no"], ["at", fmt(x), fmt(y), "0"],
                         ["effects", ["font", ["size", fmt(size), fmt(size)]], ["justify", "left", "bottom"]],
                         ["uuid", Str(uid())]])
        tree = ["kicad_sch", ["version", "20260306"], ["generator", Str("eeschema")],
                ["generator_version", Str("10.0")], ["uuid", Str(self.root)],
                ["paper", Str(self.paper)],
                ["title_block", ["title", Str(self.title)]],
                ["lib_symbols"] + list(lib_symbols.values())] + body + [
                ["sheet_instances", ["path", Str("/"), ["page", Str("1")]]],
                ["embedded_fonts", "no"]]
        path.write_text(dump(tree) + "\n", encoding="utf-8")

    def _instance(self, part, sym):
        x, y = part.at
        props = {p[1]: p for p in find_all(sym, "property")}
        values = {"Reference": part.ref, "Value": part.value, "Footprint": part.fp}
        if part.lcsc:
            values["LCSC"] = part.lcsc
        values.update(part.fields)
        in_bom = find(sym, "in_bom")      # e.g. solder jumpers are "no" in the library
        in_bom = str(in_bom[1]) if in_bom else "yes"
        if fp_excluded_from_bom(part.fp):   # e.g. test points: bare pads, no BOM line
            in_bom = "no"
        out = ["symbol", ["lib_id", Str(part.lib_id)], ["at", fmt(x), fmt(y), "0"],
               ["unit", str(part.unit)], ["exclude_from_sim", "no"], ["in_bom", in_bom],
               ["on_board", "yes"], ["dnp", "yes" if part.dnp else "no"],
               ["uuid", Str(uid(f"{self.project}/{part.ref}"))]]
        for key, val in values.items():
            lp = props.get(key)
            if lp is not None:
                at = find(lp, "at")
                px, py, rot = float(at[1]), float(at[2]), at[3]
                hide = key not in ("Reference", "Value")
            else:
                px, py, rot, hide = 0.0, 0.0, "0", True
            prop = ["property", Str(key), Str(val), ["at", fmt(x + px), fmt(y - py), rot],
                    ["effects", ["font", ["size", "1.27", "1.27"]]] + ([["hide", "yes"]] if hide else [])]
            out.append(prop)
        for num, *_ in pins_of(sym, part.unit):
            out.append(["pin", Str(num), ["uuid", Str(uid())]])
        out.append(["instances", ["project", Str(self.project),
                                  ["path", Str("/" + self.root), ["reference", Str(part.ref)],
                                   ["unit", str(part.unit)]]]])
        return out
