# -*- coding: utf-8 -*-
"""안아수달 캐릭터 애니메이션 GIF
   대기(둥둥) → 잠수 → 수중 헤엄 → 부상 → 대기  루프
   레이어: 배경 → 수달 → 수중 틴트 → 물결 → 기포
"""
import math, os
from PIL import Image, ImageDraw

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(BASE, "안아수달_수달.gif")

W, H = 420, 430
SS = 3
BG = (247, 245, 240)
BODY = (45, 107, 93)
PAW_L = (126, 198, 184)
WATER = (35, 96, 84)
TINT = (223, 236, 231, 78)       # 수면 아래 덮는 반투명 물빛 (은은하게)
WHITE = (253, 252, 249)
DARK = (26, 62, 54)

SURF = 188                        # 수면 y
DEPTH = 176                       # 잠수 깊이 (완전히 잠기도록)
FPS = 20


def ease(t):
    return 4 * t ** 3 if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2


def S(box):
    return [c * SS for c in box]


def rr(d, box, r, fill):
    d.rounded_rectangle(S(box), radius=r * SS, fill=fill)


def ell(d, box, fill=None, outline=None, w=1):
    d.ellipse(S(box), fill=fill, outline=outline, width=int(w * SS))


def otter(d, cx, cy, squash=0.0, blink=False, tilt=0.0, paws=True, sc=1.0):
    """수달 상반신. cy = 몸통 아랫변"""
    bw = 172 * sc * (1 + squash * 0.11)
    bh = 128 * sc * (1 - squash * 0.15)
    skirt = 30 * sc
    x0, x1 = cx - bw / 2, cx + bw / 2
    top = cy - bh

    # 귀 — 몸통 위로 확실히 튀어나오게
    er = 27 * sc
    for sx in (-1, 1):
        ex = cx + sx * (bw * 0.33) + tilt * 5
        ell(d, (ex - er / 2, top - er * 0.34, ex + er / 2, top + er * 0.66), fill=BODY)

    # 몸통 — 위가 둥근 돔
    rr(d, (x0, top, x1, cy + skirt), 62, BODY)
    d.rectangle(S((x0, cy - 10, x1, cy + skirt)), fill=BODY)

    # 눈
    ew, eh = 29 * sc, 32 * sc
    for sx in (-1, 1):
        ex = cx + sx * (bw * 0.185) + tilt * 4
        ey = top + bh * 0.42
        if blink:
            rr(d, (ex - ew / 2 + 2, ey - 2.6, ex + ew / 2 - 2, ey + 2.6), 2.6, DARK)
        else:
            ell(d, (ex - ew / 2, ey - eh / 2, ex + ew / 2, ey + eh / 2), fill=WHITE)
            pr, px, py = 10.0 * sc, ex + sx * 1.2 + tilt * 3, ey + 1.5
            ell(d, (px - pr, py - pr, px + pr, py + pr), fill=DARK)
            ell(d, (px - 0.2 * sc, py - 6.4 * sc, px + 6.2 * sc, py - 0.2 * sc), fill=WHITE)

    # 코 + 입 (w 모양)
    nx = cx + tilt * 4
    ny = top + bh * 0.635
    rr(d, (nx - 12 * sc, ny, nx + 12 * sc, ny + 10 * sc), 5 * sc, DARK)
    for sx in (-1, 1):
        box = (nx + sx * 16 * sc - 16 * sc, ny + 5 * sc,
               nx + sx * 16 * sc + 16 * sc, ny + 31 * sc)
        st, en = (290, 358) if sx < 0 else (182, 250)
        d.arc(S(box), st, en, fill=DARK, width=int(max(2, 4.0 * sc) * SS))

    # 앞발
    if paws:
        for sx in (-1, 1):
            px = cx + sx * (bw * 0.415)
            rr(d, (px - 27 * sc, cy - 18 * sc, px + 27 * sc, cy + 12 * sc), 14 * sc, BODY)
            rr(d, (px - 23 * sc, cy + 3 * sc, px + 23 * sc, cy + 11 * sc), 4 * sc, PAW_L)


def water_dashes(d, phase):
    rows = [
        (SURF - 10, [(30, 28), (306, 24), (358, 18)]),
        (SURF + 16, [(14, 32), (92, 22), (292, 30), (352, 22)]),
        (SURF + 44, [(44, 28), (120, 20), (242, 32), (326, 22)]),
        (SURF + 72, [(26, 24), (172, 30), (268, 22)]),
        (SURF + 100, [(60, 26), (206, 20), (300, 28)]),
    ]
    for ri, (y, segs) in enumerate(rows):
        drift = math.sin(phase * 2 * math.pi + ri * 0.85) * 5
        for x, w in segs:
            rr(d, (x + drift, y, x + drift + w, y + 7), 3.5, WATER)


def ripple(d, cx, y, r, w):
    """수면에 낮게 퍼지는 파문. 캐릭터 위를 가로지르지 않도록 좌우 호만 그린다."""
    if r <= 3 or w < 1:
        return
    for k in (0, 1):
        rad = r + k * 16
        box = (cx - rad, y - rad * 0.20, cx + rad, y + rad * 0.20)
        for st, en in ((158, 196), (344, 382)):
            d.arc(S(box), st, en, fill=WATER, width=int(max(1, w - k * 1.4) * SS))


def bubbles(d, t, x0, y0, n=3):
    for i in range(n):
        p = (t + i / n) % 1.0
        y = y0 - p * 124
        r = (8.0 - i * 1.5) * (1.0 - p * 0.42)
        x = x0 + math.sin(p * 5.0 + i * 1.3) * 10 + i * 14
        if r > 0.9:
            ell(d, (x - r, y - r, x + r, y + r), outline=WATER, w=2.8)


def frame(i, n):
    t = i / n
    cx, cy = W / 2, SURF
    squash = tilt = 0.0
    blink = False
    dive = 0.0

    if t < 0.32:                                   # 대기
        p = t / 0.32
        cy = SURF + math.sin(p * 2 * math.pi * 2) * 5
        blink = 0.46 < p < 0.53
    elif t < 0.48:                                 # 잠수
        p = ease((t - 0.32) / 0.16)
        cy = SURF + p * DEPTH
        squash = math.sin(p * math.pi) * 0.5
        dive, blink = p, p > 0.3
    elif t < 0.72:                                 # 수중 헤엄
        p = (t - 0.48) / 0.24
        cy = SURF + DEPTH - math.sin(p * math.pi) * 10
        cx = W / 2 + math.sin(p * 2 * math.pi) * 52
        tilt = math.cos(p * 2 * math.pi)
        blink, dive = True, 1.0
    elif t < 0.86:                                 # 부상
        p = ease((t - 0.72) / 0.14)
        cy = SURF + DEPTH * (1 - p)
        squash = -math.sin(p * math.pi) * 0.30
        blink, dive = p < 0.32, 1 - p
    else:                                          # 대기 복귀
        p = (t - 0.86) / 0.14
        cy = SURF + math.sin(p * 2 * math.pi) * 4

    img = Image.new("RGBA", (W * SS, H * SS), BG + (255,))

    # 1) 수달
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sc = 1.0 - 0.22 * min(1.0, max(0.0, (cy - SURF) / DEPTH))
    otter(ImageDraw.Draw(lay), cx, cy, squash, blink, tilt,
          paws=(dive < 0.25), sc=sc)
    img.alpha_composite(lay)

    # 2) 수면 아래 물빛으로 덮기 — 잠길수록 가라앉아 보인다
    if cy > SURF + 4:
        tint = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(tint).rectangle(S((0, SURF + 2, W, H)), fill=TINT)
        img.alpha_composite(tint)

    d = ImageDraw.Draw(img)
    # 3) 물결
    water_dashes(d, t)
    if dive > 0.05:
        ripple(d, W / 2, SURF + 4, 74 + dive * 52, 4.2 * (1 - dive * 0.45))
    # 4) 기포
    if 0.38 < t < 0.84:
        bubbles(d, (t - 0.38) / 0.46 * 1.9, cx + 56, SURF - 8, n=3)

    return img.convert("RGB").resize((W, H), Image.LANCZOS)


def main():
    n = 76
    frames = [frame(i, n) for i in range(n)]
    frames[0].save(OUT, save_all=True, append_images=frames[1:],
                   duration=int(1000 / FPS), loop=0, optimize=True, disposal=2)
    print("저장: %s" % os.path.basename(OUT))
    print("%d프레임 / %dfps / %.1f초 / %.0fKB"
          % (n, FPS, n / FPS, os.path.getsize(OUT) / 1024))


if __name__ == "__main__":
    main()
