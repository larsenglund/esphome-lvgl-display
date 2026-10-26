"""Sanity checks on a schematic's netlist and ERC report.

Usage: python tools/netcheck.py hardware/<board>/<board>.kicad_sch

- exports the netlist with kicad-cli and lists nets with a single connection
- summarises ERC findings, hiding the library-configuration noise that
  kicad-cli reports when no global library tables are set up
"""
import collections
import pathlib
import re
import subprocess
import sys
import tempfile

KICAD_CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
NOISE = ("lib_symbol_issues", "footprint_link_issues", "lib_symbol_mismatch")


def netlist(sch):
    out = pathlib.Path(tempfile.gettempdir()) / (sch.stem + ".net")
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", str(sch), "-o", str(out)],
                   check=True, capture_output=True)
    text = out.read_text(encoding="utf-8")
    nets = {}
    for m in re.finditer(r'\(net\s+\(code "?\d+"?\)\s+\(name "([^"]*)"\)(.*?)(?=\(net\s|\Z)', text, re.S):
        nodes = re.findall(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"', m.group(2))
        nets[m.group(1)] = nodes
    return nets


def erc(sch):
    out = pathlib.Path(tempfile.gettempdir()) / (sch.stem + ".erc.rpt")
    subprocess.run([KICAD_CLI, "sch", "erc", str(sch), "-o", str(out)], capture_output=True)
    items = collections.Counter()
    for line in out.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\[(\w+)\]: (.*)", line)
        if m and m.group(1) not in NOISE:
            items[f"{m.group(1)}: {m.group(2)}"] += 1
    return items


def main(path):
    sch = pathlib.Path(path)
    nets = netlist(sch)
    single = {n: v for n, v in nets.items() if len(v) == 1 and not n.startswith("unconnected-")}
    print(f"{sch.name}: {len(nets)} nets")
    for n, v in sorted(single.items()):
        print(f"  single-connection net {n}: {v}")
    for item, count in erc(sch).most_common():
        print(f"  ERC x{count} {item}")


if __name__ == "__main__":
    main(sys.argv[1])
