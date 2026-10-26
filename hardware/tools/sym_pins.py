"""Print the pins of a symbol in a .kicad_sym library.

Usage: python tools/sym_pins.py <library.kicad_sym> <symbol name>
"""
import re
import sys


def symbol_block(text, name):
    start = text.find(f'(symbol "{name}"')
    if start < 0:
        sys.exit(f"symbol {name!r} not found")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]


def main(lib, name):
    block = symbol_block(open(lib, encoding="utf-8").read(), name)
    ext = re.search(r'\(extends "([^"]+)"', block)
    if ext:
        print(f"(extends {ext.group(1)})")
        block = symbol_block(open(lib, encoding="utf-8").read(), ext.group(1))
    pins = re.findall(
        r'\(pin (\w+) \w+\s*\(at ([-\d.]+) ([-\d.]+) (\d+)\).*?\(name "([^"]*)".*?\(number "([^"]*)"',
        block, re.S)
    for etype, x, y, rot, pname, num in sorted(pins, key=lambda p: (len(p[5]), p[5])):
        print(f"{num:>4}  {pname:<14} {etype:<14} ({x}, {y}) r{rot}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
