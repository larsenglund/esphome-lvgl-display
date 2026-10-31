"""Route an add-on board from scratch: addon-keys or addon-encoders.

Run with plain Python from the repo root, once per board (after gen_addon.py):
    python hardware/addon/route_addon.py keys [tries]
    python hardware/addon/route_addon.py encoders [tries]

Freerouting's results vary from run to run, so it runs `tries` times (default 5),
each from a fresh place_addon.py board, and the run with the fewest open signal
connections wins, the shortest of those. GND stays out of it: the pours and the
vias from tools/fanout.py carry it. Then:
- tools/stitch.py ties the pours together,
- tools/finish_route.py routes what is still open,
- tools/autoroute.py --stubs clears the ends of hand-routed stubs that the router
  joined further along, and vias that routing cut off.
Check the result with DRC and by eye: a connection the finisher had to make can
take a long way round. See README.md for what DRC should say.
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
KICAD = pathlib.Path(r"C:\Program Files\KiCad\10.0\bin")
KPY, CLI = str(KICAD / "python.exe"), str(KICAD / "kicad-cli.exe")
TOOLS = ROOT / "hardware" / "tools"
TRACK_LENGTH = """
import pcbnew, sys
b = pcbnew.LoadBoard(sys.argv[1])
print(sum(pcbnew.ToMM(t.GetLength()) for t in b.GetTracks() if t.GetClass() != "PCB_VIA"))
"""


def run(*args):
    subprocess.run([KPY, *map(str, args)], check=True, cwd=ROOT, capture_output=True)


def drc(pcb):
    out = pathlib.Path(tempfile.gettempdir()) / f"{pcb.stem}.drc.json"
    subprocess.run([CLI, "pcb", "drc", "--format", "json", "--schematic-parity", "--severity-all", "-o", str(out), str(pcb)],
                   capture_output=True)
    d = json.loads(out.read_text(encoding="utf-8"))
    out.unlink()
    return d


def open_signals(pcb):
    """Open connections that aren't GND, and the nets involved (GND included)."""
    nets = [u["items"][0]["description"].split("[")[1].split("]")[0] for u in drc(pcb)["unconnected_items"]
            if "[" in u["items"][0]["description"]]
    return sum(n != "/GND" for n in nets), sorted(set(nets))


def length(pcb):
    r = subprocess.run([KPY, "-c", TRACK_LENGTH, str(pcb)], capture_output=True, text=True, cwd=ROOT)
    return float(r.stdout.split()[0])


def main(build, tries=5):
    pcb = ROOT / "hardware" / f"addon-{build}" / f"addon-{build}.kicad_pcb"
    keep = pathlib.Path(tempfile.gettempdir()) / f"{pcb.stem}.best"
    best = None
    for n in range(int(tries)):
        run(ROOT / "hardware" / "addon" / "place_addon.py", build)
        run(TOOLS / "autoroute.py", pcb, 60, "--planes=GND")
        n_open, nets = open_signals(pcb)
        mm = length(pcb)
        print(f"try {n + 1}: {n_open} signal connections open, {mm:.0f} mm of track {nets}", flush=True)
        if best is None or (n_open, mm) < best:
            best = (n_open, mm)
            shutil.copyfile(pcb, keep)
    shutil.copyfile(keep, pcb)
    keep.unlink()
    pcb.with_suffix(".route.log").unlink(missing_ok=True)
    run(TOOLS / "stitch.py", pcb)
    run(TOOLS / "finish_route.py", pcb, "F.Cu,B.Cu", 3)
    run(TOOLS / "autoroute.py", pcb, 0, "--stubs")
    d = drc(pcb)
    types = {}
    for v in d["violations"]:
        types[v["type"]] = types.get(v["type"], 0) + 1
    print(f"{pcb.name}: {len(d['unconnected_items'])} unconnected, {len(d.get('schematic_parity', []))} parity issues, "
          f"violations {types}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("keys", "encoders"):
        sys.exit("usage: route_addon.py keys|encoders [tries]")
    main(*sys.argv[1:])
