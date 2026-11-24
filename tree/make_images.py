"""Draws the images for the Christmas tree display (Tuva's room) and writes tree/tree_layout.h.

- background.png: night sky with northern lights, snowy hills, the tree with its light strings,
  presents and snow. 480x480, no transparency.
- star_on.png / star_off.png: the star on top (the ceiling light), shining or dull.
- ornament_N_on.png / ornament_N_off.png: the big baubles (one light each), with a glow when on.
  They hang from the top of the loop and sway sideways when tapped.
- sparkle.png: a little four-pointed glint that flashes around whatever is lit.

The twinkling bulbs, the snow and the images above are placed by tree/tree_fx.h from the
positions written to tree/tree_layout.h, so the two always agree.

Run: .venv\\Scripts\\python.exe tree\\make_images.py
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
ROOT = HERE.parent
W = H = 480
random.seed(1224)

# --- Layout (screen px) ------------------------------------------------------------------------
STAR_SIZE = 136                # square image, star in the middle
STAR_C = (240, 66)             # centre of the star on screen
STAR_R = 46                    # tip radius

ORN_W, ORN_H = 132, 146        # ornament image, with room for the glow
ORN_CX, ORN_CY, ORN_R = 66, 82, 44  # ball inside the image
PIVOT = (66, 13)               # top of the loop it hangs from

RED = (212, 22, 34)
# name, ball centre on screen, colour, MDI icon
ORNAMENTS = [
    ("Sängslingor", (240, 216), RED, 0xF02E3),     # mdi_bed
    ("Hörnslingor", (160, 334), RED, 0xF12BA),     # mdi_string_lights
    ("Skrivbord", (320, 334), RED, 0xF095F),       # mdi_desk_lamp
]

TREE_TOP, TREE_BASE, TREE_HALF = 94, 414, 208  # outline of the tree: apex, bottom, half width
TRUNK = (226, 400, 254, 444)
SNOW_Y = 438                   # top of the snow on the ground, roughly

# Light strings across the tree: start, end, sag (px down in the middle)
STRINGS = [
    ((200, 160), (282, 170), 12),
    ((132, 262), (350, 276), 22),
    ((90, 358), (394, 370), 16),
]
BULB_COLORS = [0xFF3B3B, 0xFFC531, 0x48E05A, 0x4A9BFF, 0xFF7AD9]

S = 3  # supersampling for the separate images


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(len(a)))


def clamp(v):
    return max(0, min(255, int(round(v))))


def mdi_font(size):
    for path in sorted((ROOT / ".esphome" / "font").glob("*/font.ttf")):
        font = ImageFont.truetype(str(path), size)
        if font.getname()[0] == "Material Design Icons":
            return font
    raise SystemExit("Material Design Icons not found in .esphome/font: compile any display once first")


def string_point(s, t):
    (x0, y0), (x1, y1), sag = s
    return x0 + (x1 - x0) * t, y0 + (y1 - y0) * t + sag * 4 * t * (1 - t)


def behind_text(x, y, margin=2):
    """Under the clock (top left) or the outdoor temperature (top right)."""
    return y < 116 + margin and (x < 108 + margin or x > 372 - margin)


# --- Background -------------------------------------------------------------------------------
def background():
    B = 2  # drawn at 2x, scaled down at the end
    img = Image.new("RGB", (W * B, H * B))
    px = img.load()
    top, horizon = (6, 12, 36), (36, 48, 104)
    for y in range(H * B):
        t = min(1.0, y / (380 * B))
        base = lerp(top, horizon, t ** 1.3)
        for x in range(W * B):
            xs, ys = x / B, y / B
            # Northern lights: a soft green ribbon that wavers across the sky
            mid = 120 + 26 * math.sin(xs / 68) + 10 * math.sin(xs / 23 + 1.3)
            band = math.exp(-(((ys - mid) / 26) ** 2)) * (0.55 + 0.45 * math.sin(xs / 41 + 0.7))
            curtain = math.exp(-(((ys - mid + 28) / 60) ** 2)) * 0.35 * (0.5 + 0.5 * math.sin(xs / 9))
            a = max(0.0, band * 0.38 + curtain * 0.12)
            px[x, y] = lerp(base, (70, 230, 160), a)
    d = ImageDraw.Draw(img, "RGBA")

    # Stars in the sky
    for _ in range(90):
        x, y = random.uniform(4, W - 4), random.uniform(4, 330)
        if behind_text(x, y):
            continue
        r = random.choice([0.6, 0.8, 1.0, 1.0, 1.4])
        a = random.randint(90, 230)
        d.ellipse([(x - r) * B, (y - r) * B, (x + r) * B, (y + r) * B], fill=(235, 240, 255, a))
    for _ in range(6):  # a few that glint
        x, y = random.uniform(20, W - 20), random.uniform(20, 300)
        if behind_text(x, y, 8):
            continue
        for dx, dy in ((5, 0), (0, 5)):
            d.line([(x - dx) * B, (y - dy) * B, (x + dx) * B, (y + dy) * B], fill=(235, 240, 255, 150), width=B)

    # Far hills, with little pines and a cottage
    far = [(0, 372)] + [(x, 352 + 14 * math.sin(x / 55) + 8 * math.sin(x / 21)) for x in range(0, W + 1, 6)] + [(W, 372), (W, H), (0, H)]
    d.polygon([(x * B, y * B) for x, y in far], fill=(120, 140, 190))
    for x in list(range(8, 90, 17)) + list(range(392, 476, 15)):
        y = 352 + 14 * math.sin(x / 55) + 8 * math.sin(x / 21) + 4
        h = random.uniform(16, 26)
        d.polygon([(x * B, (y - h) * B), ((x - h * 0.35) * B, y * B), ((x + h * 0.35) * B, y * B)], fill=(26, 46, 70))
        d.polygon([(x * B, (y - h) * B), ((x - h * 0.12) * B, (y - h * 0.6) * B), ((x + h * 0.12) * B, (y - h * 0.6) * B)], fill=(210, 225, 245, 160))
    cx, cy = 56, 352  # cottage
    d.rectangle([(cx - 14) * B, (cy - 10) * B, (cx + 14) * B, (cy + 8) * B], fill=(92, 44, 36))
    d.polygon([((cx - 18) * B, (cy - 9) * B), (cx * B, (cy - 24) * B), ((cx + 18) * B, (cy - 9) * B)], fill=(236, 242, 255))
    d.rectangle([(cx - 8) * B, (cy - 4) * B, (cx - 1) * B, (cy + 3) * B], fill=(255, 204, 90))
    d.rectangle([(cx + 4) * B, (cy - 4) * B, (cx + 10) * B, (cy + 8) * B], fill=(60, 28, 22))
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([(cx - 16) * B, (cy - 12) * B, (cx + 6) * B, (cy + 10) * B], fill=(255, 200, 90, 70))
    img.paste(glow.filter(ImageFilter.GaussianBlur(6 * B)), (0, 0), glow.filter(ImageFilter.GaussianBlur(6 * B)))
    d = ImageDraw.Draw(img, "RGBA")

    # Soft light from the tree onto the snow
    halo = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse([120 * B, 380 * B, 360 * B, 470 * B], fill=(255, 210, 120, 50))
    halo = halo.filter(ImageFilter.GaussianBlur(20 * B))
    img.paste(halo, (0, 0), halo)
    d = ImageDraw.Draw(img, "RGBA")

    # Trunk, mostly hidden under the lowest branches
    for x in range(TRUNK[0] * B, TRUNK[2] * B):
        t = (x - TRUNK[0] * B) / ((TRUNK[2] - TRUNK[0]) * B)
        shade = 0.55 + 0.45 * math.cos((t - 0.3) * math.pi)
        d.line([x, TRUNK[1] * B, x, TRUNK[3] * B], fill=lerp((40, 24, 14), (112, 74, 46), shade))
    for _ in range(40):  # bark
        x = random.uniform(TRUNK[0] + 2, TRUNK[2] - 2)
        y = random.uniform(TRUNK[1], TRUNK[3] - 6)
        d.line([x * B, y * B, (x + random.uniform(-1, 1)) * B, (y + random.uniform(4, 10)) * B], fill=(30, 18, 10, 160), width=B)

    tree = fir_tree(B)
    img.paste(tree, (0, 0), tree)
    d = ImageDraw.Draw(img, "RGBA")

    # Gold bead garlands, just under the light strings
    for s in STRINGS[1:]:
        (x0, y0), (x1, y1), sag = s
        g = ((x0 + 12, y0 + 30), (x1 - 12, y1 + 30), sag + 6)
        for k in range(0, 90):
            x, y = string_point(g, k / 89)
            d.ellipse([(x - 1.6) * B, (y - 1.6) * B, (x + 1.6) * B, (y + 1.6) * B], fill=(176, 128, 40, 235))
            d.ellipse([(x - 1.0) * B, (y - 1.2) * B, (x + 0.3) * B, (y + 0.1) * B], fill=(255, 226, 140, 235))

    # Wire for the light strings, partly lost among the needles
    for s in STRINGS:
        pts = [string_point(s, k / 80) for k in range(81)]
        for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
            if random.random() < 0.8:
                d.line([xa * B, ya * B, xb * B, yb * B], fill=(10, 20, 12, 200), width=B + 1)

    # Warm light from each bulb on the needles around it
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for x, y, c in bulbs():
        col = ((c >> 16) & 255, (c >> 8) & 255, c & 255)
        gd.ellipse([(x - 11) * B, (y - 11) * B, (x + 11) * B, (y + 11) * B], fill=lerp(col, (255, 230, 170), 0.4) + (80,))
    glow = glow.filter(ImageFilter.GaussianBlur(6 * B))
    img.paste(glow, (0, 0), glow)
    d = ImageDraw.Draw(img, "RGBA")

    # Snow on the ground: blue in the shade, a warm hint near the tree, glitter
    snow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sp = snow.load()
    for y in range((SNOW_Y - 12) * B, H * B):
        for x in range(W * B):
            xs, ys = x / B, y / B
            top = SNOW_Y + 6 * math.sin(xs / 40) + 4 * math.sin(xs / 13 + 1)
            if ys < top:
                continue
            depth = min(1.0, (ys - top) / 30)
            c = lerp((236, 242, 252), (176, 194, 228), 0.25 + 0.5 * depth)
            warm = math.exp(-(((xs - 240) / 120) ** 2 + ((ys - 446) / 26) ** 2))
            c = lerp(c, (255, 228, 190), warm * 0.35)
            sp[x, y] = c + (255,)
    img.paste(snow, (0, 0), snow)
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(160):
        x, y = random.uniform(0, W), random.uniform(SNOW_Y + 4, H - 2)
        d.point([x * B, y * B], fill=(255, 255, 255, random.randint(150, 255)))

    # Presents round the trunk, back ones first
    present(img, 118, 412, 50, 36, 16, (178, 22, 34), "stripes", (232, 196, 96), B)
    present(img, 286, 414, 44, 32, 14, (24, 86, 60), "dots", (196, 30, 40), B)
    present(img, 170, 428, 36, 24, 12, (236, 232, 222), "dots", (190, 28, 38), B)
    present(img, 320, 424, 52, 30, 16, (30, 70, 150), "stars", (236, 236, 244), B)
    present(img, 258, 436, 30, 20, 10, (212, 168, 60), "stripes", (150, 22, 34), B)

    return img.resize((W, H), Image.LANCZOS)


def tree_half(y):
    """Half width of the tree's outline at screen y."""
    t = (y - TREE_TOP) / (TREE_BASE - TREE_TOP)
    return TREE_HALF * max(0.0, t) ** 0.9


def fir_tree(B):
    """A spruce made of drooping branches covered in needles, back branches darker (RGBA)."""
    layer = Image.new("RGBA", (W * B, H * B), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")

    # Deep shade inside the tree, so gaps between branches look dark rather than show the sky
    core = [(240 * B, (TREE_TOP + 14) * B)]
    core += [((240 + tree_half(y) * 0.78) * B, y * B) for y in range(TREE_TOP + 14, TREE_BASE - 6, 3)]
    core += [((240 - tree_half(y) * 0.78) * B, y * B) for y in range(TREE_BASE - 7, TREE_TOP + 14, -3)]
    d.polygon(core, fill=(6, 20, 12, 255))

    deep, mid, light, tip = (10, 34, 20), (26, 70, 38), (58, 112, 56), (112, 156, 84)
    branches = []
    y = TREE_BASE
    while y > TREE_TOP + 3:
        hw = tree_half(y)
        n = max(5, int(hw / 8))
        off = random.random() * 6.283
        for k in range(n):
            branches.append((y, off + 6.283 * (k + random.uniform(-0.3, 0.3)) / n, hw))
        y -= 3 + 4 * (y - TREE_TOP) / (TREE_BASE - TREE_TOP)
    branches.sort(key=lambda b: math.cos(b[1]))  # back of the tree first

    for y0, th, hw in branches:
        z, sx = math.cos(th), math.sin(th)       # z: towards us, sx: left/right
        length = hw * random.uniform(0.82, 1.1)
        ay = max(TREE_TOP, y0 - length * 0.34)   # attaches higher up and droops down
        ex = 240 + length * sx
        ey = y0 + length * 0.3 * max(0.0, z) + random.uniform(-3, 3)
        cx, cy = 240 + (ex - 240) * 0.55, ay + (ey - ay) * 0.15
        top_t = 1 - (y0 - TREE_TOP) / (TREE_BASE - TREE_TOP)
        lit = 0.25 + 0.55 * (z + 1) / 2 - 0.18 * sx + 0.12 * top_t
        steps = max(8, int(length * 1.4))
        prev = None
        for k in range(steps + 1):
            t = k / steps
            x = (1 - t) ** 2 * 240 + 2 * (1 - t) * t * cx + t * t * ex
            y = (1 - t) ** 2 * ay + 2 * (1 - t) * t * cy + t * t * ey
            if prev is not None and t > 0.2:
                tx, ty = x - prev[0], y - prev[1]
                ang = math.atan2(ty, tx)
                for side in (-1, 1):
                    if random.random() < 0.15:
                        continue
                    a = ang + side * math.radians(random.uniform(35, 75)) + math.radians(14)
                    nl = random.uniform(3.0, 6.5) * (0.55 + 0.45 * t)
                    shade = max(0.0, min(1.0, lit + random.uniform(-0.18, 0.18)))
                    col = lerp(deep, mid, shade * 1.6) if shade < 0.62 else lerp(mid, light, (shade - 0.62) / 0.38)
                    if t > 0.85 and random.random() < 0.5:  # fresh growth at the tips
                        col = lerp(col, tip, 0.5)
                    d.line([x * B, y * B, (x + nl * math.cos(a)) * B, (y + nl * math.sin(a)) * B], fill=col + (235,), width=B)
                # A dusting of snow on top of the branches facing us
                if z > 0.2 and random.random() < 0.05 * z:
                    d.line([x * B, (y - 1.5) * B, (x + tx * 3) * B, (y - 1.5 + ty * 3) * B], fill=(214, 226, 240, 110), width=B)
            prev = (x, y)

    # Soft shading: darker towards the lower right, away from the light
    shade = Image.new("L", layer.size, 0)
    ImageDraw.Draw(shade).ellipse([300 * B, 180 * B, 620 * B, 560 * B], fill=110)
    shade = shade.filter(ImageFilter.GaussianBlur(50 * B))
    dark = Image.new("RGBA", layer.size, (0, 8, 4, 255))
    dark.putalpha(Image.composite(shade, Image.new("L", layer.size, 0), layer.getchannel("A")))
    return Image.alpha_composite(layer, dark)


def present(img, x, y, w, h, depth, paper, pattern, ribbon, B):
    """A wrapped box seen a little from above and to the left: front, right side and top."""
    dx, dy = depth * 0.7, -depth * 0.55

    def S2(pts):
        return [(px * B, py * B) for px, py in pts]

    front = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    side = [(x + w, y), (x + w + dx, y + dy), (x + w + dx, y + h + dy), (x + w, y + h)]
    top = [(x, y), (x + dx, y + dy), (x + w + dx, y + dy), (x + w, y)]

    # Contact shadow on the snow
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([(x - 4) * B, (y + h - 5) * B, (x + w + dx + 10) * B, (y + h + 6) * B], fill=(30, 40, 70, 120))
    sh = sh.filter(ImageFilter.GaussianBlur(3 * B))
    img.paste(sh, (0, 0), sh)

    light_paper = tuple(clamp(c * 1.18 + 12) for c in paper)
    dark_paper = tuple(clamp(c * 0.6) for c in paper)
    motif = tuple(clamp(c * 0.5 + 120) for c in ribbon)
    for face, base, k in ((front, paper, 1.0), (side, dark_paper, 0.62), (top, light_paper, 1.15)):
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).polygon(S2(face), fill=255)
        layer = Image.new("RGB", img.size, base)  # RGB, so the RGBA drawing below blends
        ld = ImageDraw.Draw(layer, "RGBA")
        mcol = tuple(clamp(c * k) for c in motif) + (150,)
        if pattern == "stripes":
            for sx in range(int(x - h), int(x + w + dx + 4), 9):
                ld.line([sx * B, (y + h) * B, (sx + h + 8) * B, (y + dy - 8) * B], fill=mcol, width=2 * B)
        elif pattern == "dots":
            for yy in range(int(y + dy), int(y + h), 7):
                for xx in range(int(x) + (yy % 2) * 3, int(x + w + dx), 7):
                    ld.ellipse([(xx - 1.3) * B, (yy - 1.3) * B, (xx + 1.3) * B, (yy + 1.3) * B], fill=mcol)
        else:  # little stars
            for yy in range(int(y + dy) + 3, int(y + h), 10):
                for xx in range(int(x) + (yy % 3) * 3, int(x + w + dx), 10):
                    for a in range(5):
                        r = math.radians(-90 + 72 * a)
                        ld.line([xx * B, yy * B, (xx + 2.2 * math.cos(r)) * B, (yy + 2.2 * math.sin(r)) * B], fill=mcol, width=B)
        # Paper shading: a little darker towards the bottom
        for yy in range(int((y + dy - 2) * B), int((y + h + 2) * B)):
            t = (yy / B - y) / h
            ld.line([x * B, yy, (x + w + dx + 2) * B, yy], fill=(0, 0, 0, clamp(max(0.0, t) * 50)))
        img.paste(layer, (0, 0), mask)
    d = ImageDraw.Draw(img, "RGBA")

    # Ribbon across the front, the side and over the top
    rw = max(4, w * 0.13)
    cx = x + w / 2
    shades = (ribbon, tuple(clamp(c * 0.62) for c in ribbon), tuple(clamp(c * 1.15 + 10) for c in ribbon))
    d.polygon(S2([(cx - rw / 2, y), (cx + rw / 2, y), (cx + rw / 2, y + h), (cx - rw / 2, y + h)]), fill=shades[0])
    d.line(S2([(cx - rw / 6, y), (cx - rw / 6, y + h)]), fill=shades[2] + (200,), width=B)
    my = y + h / 2
    d.polygon(S2([(x + w, my - rw / 2), (x + w + dx, my - rw / 2 + dy), (x + w + dx, my + rw / 2 + dy), (x + w, my + rw / 2)]), fill=shades[1])
    d.polygon(S2([(cx - rw / 2, y), (cx + rw / 2, y), (cx + rw / 2 + dx, y + dy), (cx - rw / 2 + dx, y + dy)]), fill=shades[2])
    q = rw * 0.25
    d.polygon(S2([(x + dx / 2, y + dy / 2 - q), (x + w + dx / 2, y + dy / 2 - q),
                  (x + w + dx / 2, y + dy / 2 + q), (x + dx / 2, y + dy / 2 + q)]), fill=shades[2])
    # Edges
    d.line(S2([(x, y), (x + w, y), (x + w + dx, y + dy)]), fill=tuple(clamp(c * 1.3 + 30) for c in paper) + (160,), width=B)
    d.line(S2([(x + w, y), (x + w, y + h)]), fill=(0, 0, 0, 70), width=B)

    # Bow: two loops and two tails, with a knot in the middle of the top
    bx, by = cx + dx / 2, y + dy / 2
    lw = max(8, w * 0.24)
    for sd in (-1, 1):
        loop = [(bx, by)]
        for k in range(19):
            a = math.radians(-90 + 180 * k / 18)
            loop.append((bx + sd * lw * (0.5 + 0.5 * math.cos(a)), by - lw * 0.6 + lw * 0.42 * math.sin(a)))
        d.polygon(S2(loop), fill=shades[0])
        d.polygon(S2([(bx + sd * lw * 0.25, by - lw * 0.32), (bx + sd * lw * 0.75, by - lw * 0.5),
                      (bx + sd * lw * 0.7, by - lw * 0.25)]), fill=shades[1])
        d.line(S2([(bx + sd * lw * 0.3, by - lw * 0.86), (bx + sd * lw * 0.8, by - lw * 0.8)]), fill=shades[2] + (220,), width=B)
        d.polygon(S2([(bx, by), (bx + sd * lw * 0.55, by + lw * 0.55), (bx + sd * lw * 0.38, by + lw * 0.62)]), fill=shades[1])
    d.ellipse(S2([(bx - lw * 0.16, by - lw * 0.3), (bx + lw * 0.16, by + lw * 0.02)]), fill=shades[2])


# --- Star -------------------------------------------------------------------------------------
def star(on):
    n = STAR_SIZE * S
    c = n / 2
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    R, r = STAR_R * S, STAR_R * 0.44 * S
    pts = []
    for k in range(10):
        ang = math.radians(-90 + 36 * k)
        rad = R if k % 2 == 0 else r
        pts.append((c + rad * math.cos(ang), c + rad * math.sin(ang)))

    if on:
        glow = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        for k in range(30, 0, -1):
            rad = R * 0.4 + (n / 2 - R * 0.4) * k / 30
            a = int(130 * (1 - k / 30) ** 1.6)
            gd.ellipse([c - rad, c - rad, c + rad, c + rad], fill=(255, 214, 90, a))
        for k in range(8):  # rays
            ang = math.radians(-90 + 22.5 + 45 * k)
            tip = n / 2 - 2
            w = math.radians(2.2)
            gd.polygon([(c, c), (c + tip * math.cos(ang - w), c + tip * math.sin(ang - w)),
                        (c + tip * math.cos(ang + w), c + tip * math.sin(ang + w))], fill=(255, 236, 150, 70))
        img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(S * 2)))

    d = ImageDraw.Draw(img, "RGBA")
    light_dir = (-0.6, -0.8)
    for k in range(10):
        a, b = pts[k], pts[(k + 1) % 10]
        mx, my = (a[0] + b[0]) / 2 - c, (a[1] + b[1]) / 2 - c
        ln = math.hypot(mx, my)
        facing = (mx * light_dir[0] + my * light_dir[1]) / ln
        lit = 0.5 + 0.5 * facing
        lit = lit * 0.6 + (0.4 if k % 2 == 0 else 0.0)  # tips' left facets catch more light
        if on:
            col = lerp((222, 140, 14), (255, 246, 170), lit)
        else:
            col = lerp((110, 78, 22), (196, 150, 60), lit)
        d.polygon([(c, c), a, b], fill=col + (255,))
    d.polygon(pts, outline=(255, 250, 210, 255) if on else (92, 64, 18, 255), width=S)
    if on:  # hot white centre
        core = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        ImageDraw.Draw(core).ellipse([c - R * 0.32, c - R * 0.32, c + R * 0.32, c + R * 0.32], fill=(255, 255, 235, 200))
        img = Image.alpha_composite(img, core.filter(ImageFilter.GaussianBlur(S * 3)))
    return img.resize((STAR_SIZE, STAR_SIZE), Image.LANCZOS)


# --- Ornaments --------------------------------------------------------------------------------
def ornament(color, icon, on):
    w, h = ORN_W * S, ORN_H * S
    cx, cy, R = ORN_CX * S, ORN_CY * S, ORN_R * S
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    if on:  # glow around the ball
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gcol = lerp(color, (255, 255, 255), 0.35)
        outer = min(cx, h - cy) - 2 * S
        for k in range(28, 0, -1):
            rad = R + (outer - R) * k / 28
            gd.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=gcol + (int(150 * (1 - k / 28) ** 1.8),))
        img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(S * 3)))

    # Ball: lit from the upper left
    base = color if on else lerp(lerp(color, (110, 100, 100), 0.3), (0, 0, 0), 0.4)
    body = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    spec = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bp, sp = body.load(), spec.load()
    L = (-0.45, -0.62, 0.64)
    ln = math.sqrt(sum(v * v for v in L))
    L = tuple(v / ln for v in L)
    Hh = (L[0], L[1], L[2] + 1)
    ln = math.sqrt(sum(v * v for v in Hh))
    Hh = tuple(v / ln for v in Hh)
    for y in range(cy - R, cy + R + 1):
        for x in range(cx - R, cx + R + 1):
            nx, ny = (x - cx) / R, (y - cy) / R
            q = nx * nx + ny * ny
            if q > 1:
                continue
            nz = math.sqrt(1 - q)
            diff = max(0.0, nx * L[0] + ny * L[1] + nz * L[2])
            rim = (1 - nz) ** 3
            if on:
                k = 0.22 + 0.9 * diff
                col = [base[i] * k + 90 * rim for i in range(3)]
                # warm reflection of the other lights at the lower right
                warm = math.exp(-(((nx - 0.45) / 0.22) ** 2 + ((ny - 0.55) / 0.16) ** 2))
                col = [col[i] + warm * (255, 220, 160)[i] * 0.45 for i in range(3)]
                s = max(0.0, nx * Hh[0] + ny * Hh[1] + nz * Hh[2]) ** 60
                sp[x, y] = (255, 255, 255, clamp(255 * min(1.0, s * 1.6)))
            else:
                k = 0.5 + 0.45 * diff
                col = [base[i] * k for i in range(3)]
                s = max(0.0, nx * Hh[0] + ny * Hh[1] + nz * Hh[2]) ** 5
                sp[x, y] = (255, 255, 255, clamp(40 * s))
            bp[x, y] = tuple(clamp(v) for v in col) + (255,)
    img = Image.alpha_composite(img, body)

    # Icon on the ball
    font = mdi_font(44 * S)
    glyph = chr(icon)
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    bx = md.textbbox((0, 0), glyph, font=font)
    gx = cx - (bx[0] + bx[2]) / 2
    gy = cy + 3 * S - (bx[1] + bx[3]) / 2
    md.text((gx, gy), glyph, font=font, fill=255)
    if on:
        shadow = mask.filter(ImageFilter.GaussianBlur(S * 2))
        img.paste(Image.new("RGBA", (w, h), lerp(color, (0, 0, 0), 0.6) + (150,)), (0, 0), shadow)
        img.paste(Image.new("RGBA", (w, h), (255, 250, 236, 255)), (0, 0), mask)
    else:
        img.paste(Image.new("RGBA", (w, h), lerp(base, (230, 230, 230), 0.3) + (200,)), (0, 0), mask)
    img = Image.alpha_composite(img, spec.filter(ImageFilter.GaussianBlur(S * 1.5)))

    # Cap and loop
    d = ImageDraw.Draw(img, "RGBA")
    cap_top, cap_bot = cy - R - 9 * S, cy - R + 5 * S
    for x in range(cx - 13 * S, cx + 13 * S + 1):
        t = (x - (cx - 13 * S)) / (26 * S)
        shine = 0.5 + 0.5 * math.cos((t - 0.32) * math.pi * 1.6)
        col = lerp((150, 104, 28), (255, 236, 160), shine) if on else lerp((70, 64, 52), (138, 128, 104), shine)
        d.line([x, cap_top, x, cap_bot], fill=col + (255,))
    for k in range(1, 4):  # ridges
        y = cap_top + k * (cap_bot - cap_top) / 4
        d.line([cx - 13 * S, y, cx + 13 * S, y], fill=(0, 0, 0, 60), width=S)
    lc = (255, 222, 120) if on else (120, 110, 88)
    ly = PIVOT[1] * S
    d.ellipse([cx - 6 * S, ly, cx + 6 * S, cap_top + 4 * S], outline=lc + (255,), width=int(2.4 * S))
    return img.resize((ORN_W, ORN_H), Image.LANCZOS)


def sparkle():
    n = 24 * S
    c = n / 2
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for rx, ry in ((c - 1, 1.6 * S), (1.6 * S, c - 1)):
        d.polygon([(c - rx, c), (c, c - ry), (c + rx, c), (c, c + ry)], fill=(255, 255, 240, 255))
    d.ellipse([c - 3 * S, c - 3 * S, c + 3 * S, c + 3 * S], fill=(255, 255, 255, 255))
    halo = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse([c - 7 * S, c - 7 * S, c + 7 * S, c + 7 * S], fill=(255, 240, 180, 110))
    img = Image.alpha_composite(halo.filter(ImageFilter.GaussianBlur(3 * S)), img)
    return img.resize((24, 24), Image.LANCZOS)


# --- Bulbs on the light strings ---------------------------------------------------------------
def bulbs():
    out = []
    for s in STRINGS:
        (x0, _), (x1, _), _ = s
        count = int(abs(x1 - x0) / 23)
        for k in range(count + 1):
            x, y = string_point(s, (k + 0.5) / (count + 1))
            if any(math.hypot(x - ox, y - oy) < ORN_R + 10 for _, (ox, oy), _, _ in ORNAMENTS):
                continue
            out.append((int(round(x)), int(round(y)) + 5, BULB_COLORS[len(out) % len(BULB_COLORS)]))
    return out


def layout_header(bulb_list):
    lines = [
        "// Generated by tree/make_images.py, do not edit: change the layout there and run it again.",
        "#pragma once",
        "",
        "#include <cstdint>",
        "",
        "namespace tree {",
        "",
        f"constexpr int STAR_X = {STAR_C[0] - STAR_SIZE // 2}, STAR_Y = {STAR_C[1] - STAR_SIZE // 2}, STAR_SIZE = {STAR_SIZE}, STAR_R = {STAR_R};",
        f"constexpr int ORNAMENTS = {len(ORNAMENTS)};",
        f"constexpr int ORN_W = {ORN_W}, ORN_H = {ORN_H}, ORN_CX = {ORN_CX}, ORN_CY = {ORN_CY}, ORN_R = {ORN_R};",
        f"constexpr int PIVOT_X = {PIVOT[0]}, PIVOT_Y = {PIVOT[1]};",
        "// Top left of each ornament image: " + ", ".join(n for n, _, _, _ in ORNAMENTS),
        "constexpr int ORN_X[ORNAMENTS] = {" + ", ".join(str(c[0] - ORN_CX) for _, c, _, _ in ORNAMENTS) + "};",
        "constexpr int ORN_Y[ORNAMENTS] = {" + ", ".join(str(c[1] - ORN_CY) for _, c, _, _ in ORNAMENTS) + "};",
        "constexpr uint32_t ORN_COLOR[ORNAMENTS] = {" + ", ".join("0x%02X%02X%02X" % col for _, _, col, _ in ORNAMENTS) + "};",
        f"constexpr int SNOW_Y = {SNOW_Y};",
        "",
        "// Twinkling bulbs on the light strings: centre x, y and colour",
        f"constexpr int BULBS = {len(bulb_list)};",
        "constexpr int16_t BULB_POS[BULBS][2] = {" + ", ".join("{%d, %d}" % (x, y) for x, y, _ in bulb_list) + "};",
        "constexpr uint32_t BULB_COLOR[BULBS] = {" + ", ".join("0x%06X" % c for _, _, c in bulb_list) + "};",
        "",
        "}  // namespace tree",
        "",
    ]
    (HERE / "tree_layout.h").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    background().save(HERE / "background.png")
    star(True).save(HERE / "star_on.png")
    star(False).save(HERE / "star_off.png")
    for i, (_, _, col, icon) in enumerate(ORNAMENTS, start=1):
        ornament(col, icon, True).save(HERE / f"ornament_{i}_on.png")
        ornament(col, icon, False).save(HERE / f"ornament_{i}_off.png")
    sparkle().save(HERE / "sparkle.png")
    bl = bulbs()
    layout_header(bl)

    # Preview with everything on (left) and off (right), for checking without a display
    bg = Image.open(HERE / "background.png").convert("RGBA")
    prev = Image.new("RGBA", (2 * W + 10, H), (0, 0, 0, 255))
    for col, state in enumerate(("on", "off")):
        p = bg.copy()
        for i, (_, (x, y), _, _) in enumerate(ORNAMENTS, start=1):
            p.alpha_composite(Image.open(HERE / f"ornament_{i}_{state}.png"), (x - ORN_CX, y - ORN_CY))
        p.alpha_composite(Image.open(HERE / f"star_{state}.png"), (STAR_C[0] - STAR_SIZE // 2, STAR_C[1] - STAR_SIZE // 2))
        pd = ImageDraw.Draw(p)
        for x, y, c in bl:
            pd.ellipse([x - 4, y - 5, x + 4, y + 5], fill=((c >> 16) & 255, (c >> 8) & 255, c & 255))
        prev.paste(p, (col * (W + 10), 0))
    out = Path(__import__("tempfile").gettempdir()) / "tree_preview.png"
    prev.convert("RGB").save(out)
    print(f"{len(bl)} bulbs, preview in", out)
