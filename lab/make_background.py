"""Draws the 480x480 background for the Christmas lab display (lab/lab_background.png).

A dark green brick lab wall with a glow behind the tubes, candy-cane pipes down the sides,
the wire for the twinkling bulbs, the wooden stand the tubes rest on, and snow with presents.
The tubes, bulbs, labels and buttons are LVGL widgets drawn on top (see lab/lab_tubes.h);
the positions here must match the constants there.

Run: .venv\\Scripts\\python.exe lab\\make_background.py
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

W = H = 480
random.seed(24)

# Shared with lab_tubes.h
TUBE_X = [66, 182, 298, 414]  # centres
TUBE_W = 64
TUBE_TOP = 118
TUBE_BOTTOM = 410
BULB_X = [130, 165, 200, 240, 280, 315, 350]


def wire_y(x):
    return 6 + 20 * math.sin(math.pi * x / W)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


img = Image.new("RGB", (W, H))
px = img.load()

# Wall: vertical gradient with a green glow behind the tubes
top, bottom = (14, 34, 24), (6, 14, 10)
for y in range(H):
    base = lerp(top, bottom, y / H)
    for x in range(W):
        d = math.hypot((x - 240) / 260, (y - 270) / 220)
        glow = max(0.0, 1 - d) ** 2
        px[x, y] = lerp(base, (40, 110, 45), glow * 0.55)

# Bricks
wall = ImageDraw.Draw(img, "RGBA")
bw, bh = 48, 22
for row in range(0, H // bh + 1):
    offset = (row % 2) * bw // 2
    for col in range(-1, W // bw + 2):
        x0 = col * bw - offset
        y0 = row * bh
        shade = random.randint(-6, 8)
        wall.rectangle([x0 + 2, y0 + 2, x0 + bw - 2, y0 + bh - 2], fill=(30 + shade, 60 + shade, 40 + shade, 34))
        wall.line([x0, y0, x0 + bw, y0], fill=(0, 0, 0, 70), width=2)
        wall.line([x0, y0, x0, y0 + bh], fill=(0, 0, 0, 70), width=2)

# Vignette
vig = Image.new("L", (W, H), 0)
vd = ImageDraw.Draw(vig)
for i in range(60):
    vd.rectangle([i, i, W - 1 - i, H - 1 - i], outline=int(150 * (1 - i / 60) ** 2))
img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, vig)
draw = ImageDraw.Draw(img, "RGBA")

# Faint snowflakes on the wall
for _ in range(45):
    x, y = random.randint(10, W - 10), random.randint(40, 420)
    r = random.choice([1, 1, 2, 3])
    a = random.randint(40, 110)
    if r < 3:
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(220, 240, 255, a))
    else:
        for ang in range(0, 180, 60):
            dx, dy = 5 * math.cos(math.radians(ang)), 5 * math.sin(math.radians(ang))
            draw.line([x - dx, y - dy, x + dx, y + dy], fill=(220, 240, 255, a), width=1)


# Candy-cane pipes down both sides
def candy_pipe(x0, x1, y0, y1):
    pipe = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pipe)
    w = x1 - x0
    for y in range(-w, y1 - y0 + w, 18):
        pd.polygon([(0, y), (w, y - 8), (w, y + 1), (0, y + 9)], fill=(214, 30, 40, 255))
    # Rounded shading across the pipe
    shade = Image.new("RGBA", pipe.size, (0, 0, 0, 0))
    for x in range(w):
        t = abs((x - w * 0.35) / w)
        sd = ImageDraw.Draw(shade)
        sd.line([(x, 0), (x, pipe.size[1])], fill=(0, 0, 0, int(160 * t)))
    body = Image.new("RGBA", pipe.size, (245, 245, 240, 255))
    body.alpha_composite(pipe)
    body.alpha_composite(shade)
    img.paste(body.convert("RGB"), (x0, y0))
    # Brass collars
    for cy in (y0 + 70, y0 + 230):
        draw.rectangle([x0 - 2, cy, x1 + 1, cy + 8], fill=(190, 150, 60, 255))
        draw.line([x0 - 2, cy + 1, x1 + 1, cy + 1], fill=(250, 220, 130, 255))


candy_pipe(4, 18, 30, 432)
candy_pipe(W - 18, W - 4, 30, 432)

# Bulb wire and sockets
pts = [(x, wire_y(x)) for x in range(0, W + 1, 4)]
draw.line(pts, fill=(10, 40, 18, 255), width=4)
draw.line([(x, y - 1) for x, y in pts], fill=(40, 90, 50, 255), width=1)
for bx in BULB_X:
    by = wire_y(bx)
    draw.rectangle([bx - 4, by, bx + 4, by + 8], fill=(20, 60, 30, 255))

# Wooden stand the tubes rest on
stand_top = TUBE_BOTTOM - 8
draw.rectangle([24, stand_top, W - 24, stand_top + 20], fill=(110, 62, 28, 255))
for i in range(6):
    y = stand_top + 3 + i * 3
    draw.line([(24, y), (W - 24, y + random.randint(-1, 1))], fill=(90, 48, 20, 160), width=1)
draw.line([(24, stand_top), (W - 24, stand_top)], fill=(170, 110, 60, 255), width=2)
draw.rectangle([24, stand_top + 18, W - 24, stand_top + 21], fill=(60, 30, 12, 255))

# Snowdrift
snow = Image.new("L", (W, H), 0)
sd = ImageDraw.Draw(snow)
poly = [(0, H)]
for x in range(0, W + 1, 6):
    y = 436 + 6 * math.sin(x / 37) + 4 * math.sin(x / 13 + 1)
    poly.append((x, y))
poly.append((W, H))
sd.polygon(poly, fill=255)
snow = snow.filter(ImageFilter.GaussianBlur(1))
snow_col = Image.new("RGB", (W, H), (235, 244, 255))
img = Image.composite(snow_col, img, snow)
draw = ImageDraw.Draw(img, "RGBA")
for x in range(0, W, 3):
    y = 436 + 6 * math.sin(x / 37) + 4 * math.sin(x / 13 + 1)
    draw.line([(x, y + 6), (x, y + 18)], fill=(160, 190, 225, 60), width=3)
for _ in range(40):
    x, y = random.randint(0, W), random.randint(448, H - 2)
    draw.point((x, y), fill=(255, 255, 255, 255))
    draw.point((x + 1, y), fill=(190, 215, 255, 255))


# Presents in the snow, left and right of the power button
def present(x, y, w, h, box, ribbon):
    draw.rectangle([x, y, x + w, y + h], fill=box)
    draw.rectangle([x, y, x + w, y + 3], fill=tuple(min(255, c + 40) for c in box))
    cx = x + w // 2
    draw.rectangle([cx - 2, y, cx + 2, y + h], fill=ribbon)
    draw.rectangle([x, y + h // 2 - 2, x + w, y + h // 2 + 2], fill=ribbon)
    draw.ellipse([cx - 9, y - 7, cx - 1, y + 1], outline=ribbon, width=2)
    draw.ellipse([cx + 1, y - 7, cx + 9, y + 1], outline=ribbon, width=2)


present(30, 448, 30, 24, (200, 30, 40), (250, 215, 90))
present(66, 456, 22, 18, (40, 140, 60), (240, 240, 240))
present(W - 62, 448, 30, 24, (40, 140, 60), (250, 215, 90))
present(W - 90, 456, 22, 18, (30, 80, 190), (240, 240, 240))

out = Path(__file__).with_name("lab_background.png")
img.save(out)
print(f"Wrote {out}")
