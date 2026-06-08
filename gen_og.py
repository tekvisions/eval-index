#!/usr/bin/env python3
"""Render og.png (1200x630) for The Eval Index — dark scoreboard card. Pillow only;
falls back gracefully if a font is missing so CI never breaks on fonts."""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _font(paths, size):
    from PIL import ImageFont
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def main() -> int:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        print("Pillow not available — skipping og.png")
        return 0
    try:
        data = json.load(open(os.path.join(HERE, "data.json"), encoding="utf-8"))
        count, cats = data.get("count", 0), len(data.get("categories", []))
    except Exception:
        count, cats = 0, 0

    W, H = 1200, 630
    bg, ink, lime, muted = (10, 12, 17), (233, 237, 245), (184, 255, 58), (139, 147, 167)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    # grid texture
    for x in range(0, W, 44):
        d.line([(x, 0), (x, H)], fill=(20, 24, 32), width=1)
    for y in range(0, H, 44):
        d.line([(0, y), (W, y)], fill=(20, 24, 32), width=1)

    bold = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf"]
    mono = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf"]
    f_kick = _font(mono, 24)
    f_h1 = _font(bold, 92)
    f_stat = _font(mono, 30)

    d.rectangle([54, 70, 74, 90], fill=lime)
    d.text((90, 68), "EVAL / INDEX", font=f_kick, fill=lime)
    d.text((64, 170), "How do you", font=f_h1, fill=ink)
    d.text((64, 270), "measure", font=f_h1, fill=lime)
    w = d.textlength("measure", font=f_h1)
    d.text((64 + w, 270), " an AI?", font=f_h1, fill=ink)

    d.line([64, 430, W - 64, 430], fill=(42, 49, 66), width=2)
    d.text((64, 458), f"{count} eval tools  ·  {cats} categories  ·  ranked daily by GitHub momentum",
           font=f_stat, fill=muted)
    img.save(os.path.join(HERE, "og.png"))
    print(f"wrote og.png ({count} tools)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
