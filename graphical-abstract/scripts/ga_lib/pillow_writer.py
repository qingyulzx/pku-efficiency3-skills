"""Pillow fallback rasterizer (used only when matplotlib is unavailable).

Draws the scene at `scale` resolution then downsamples with Lanczos, so the
result is anti-aliased without any external dependency.
"""
from __future__ import annotations

from .helv import wrap_text
from .scene import Scene, Rect, Ellipse, Line, Arrow, Polyline, Polygon, Circle, Text


def _rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else (0, 0, 0)


def _font(size: float, bold: bool):
    from PIL import ImageFont
    px = max(8, int(round(size)))
    try:
        return ImageFont.load_default(size=px)
    except TypeError:
        return ImageFont.load_default()


def write_png_pil(scene: Scene, path: str, scale: float = 2.0) -> dict:
    from PIL import Image, ImageDraw

    W, H = int(scene.width * scale), int(scene.height * scale)
    img = Image.new("RGB", (W, H), _rgb(scene.background or "#FFFFFF"))
    dr = ImageDraw.Draw(img)

    def S(v: float) -> int:
        return int(round(v * scale))

    import math
    for lay in scene.layers:
        for it in lay.items:
            if isinstance(it, Rect):
                dr.rounded_rectangle(
                    [S(it.x), S(it.y), S(it.x + it.w), S(it.y + it.h)],
                    radius=S(it.rx) if it.rx else 0,
                    fill=_rgb(it.fill) if it.fill != "none" else None,
                    outline=_rgb(it.stroke) if it.stroke != "none" else None,
                    width=max(1, S(it.stroke_w)) if it.stroke != "none" else 0)
            elif isinstance(it, Ellipse):
                dr.ellipse([S(it.cx - it.rx), S(it.cy - it.ry),
                            S(it.cx + it.rx), S(it.cy + it.ry)],
                           fill=_rgb(it.fill) if it.fill != "none" else None,
                           outline=_rgb(it.stroke) if it.stroke != "none" else None,
                           width=max(1, S(it.stroke_w)) if it.stroke != "none" else 0)
            elif isinstance(it, Circle):
                dr.ellipse([S(it.cx - it.r), S(it.cy - it.r),
                            S(it.cx + it.r), S(it.cy + it.r)],
                           fill=_rgb(it.fill) if it.fill != "none" else None,
                           outline=_rgb(it.stroke) if it.stroke != "none" else None,
                           width=max(1, S(it.stroke_w)) if it.stroke != "none" else 0)
            elif isinstance(it, (Line, Arrow)):
                dr.line([S(it.x1), S(it.y1), S(it.x2), S(it.y2)],
                        fill=_rgb(it.stroke), width=max(1, S(it.stroke_w)))
                if isinstance(it, Arrow):
                    ang = math.atan2(it.y2 - it.y1, it.x2 - it.x1)
                    h = it.head
                    bx, by = it.x2 - h * 1.6 * math.cos(ang), it.y2 - h * 1.6 * math.sin(ang)
                    dr.polygon([(S(it.x2), S(it.y2)),
                                (S(bx - h * 0.6 * math.sin(-ang)), S(by - h * 0.6 * math.cos(-ang))),
                                (S(bx + h * 0.6 * math.sin(-ang)), S(by + h * 0.6 * math.cos(-ang)))],
                               fill=_rgb(it.stroke))
            elif isinstance(it, (Polyline, Polygon)):
                pts = [(S(x), S(y)) for x, y in it.pts]
                if isinstance(it, Polygon):
                    dr.polygon(pts, fill=_rgb(it.fill) if it.fill != "none" else None)
                else:
                    dr.line(pts, fill=_rgb(it.stroke), width=max(1, S(it.stroke_w)),
                            joint="curve")
            elif isinstance(it, Text):
                f = _font(it.size * scale, it.bold)
                mw = it.meta.get("max_width")
                lines = wrap_text(it.text, it.size, mw, it.bold) if mw else it.text.split("\n")
                y = S(it.y)
                lh = it.size * 1.28 * scale
                for ln in lines:
                    wpx = dr.textlength(ln, font=f)
                    x = S(it.x)
                    if it.align == "center":
                        x = S(it.x) - wpx / 2
                    elif it.align == "right":
                        x = S(it.x) - wpx
                    dr.text((x, y), ln, font=f, fill=_rgb(it.color))
                    y += lh

    if scale > 1.05:
        img = img.resize((int(scene.width), int(scene.height)), Image.LANCZOS)
    img.save(path, "PNG")
    return {"backend": "pillow", "scale": scale, "pixels": img.size}
