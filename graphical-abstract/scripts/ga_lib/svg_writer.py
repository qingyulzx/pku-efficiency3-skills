"""SVG writer: the editable source of truth.

- layers become <g id="layer-..."> groups (toggling/editing by layer works
  in Inkscape / Illustrator / any text editor);
- every primitive keeps its model id as the SVG id and its provenance as a
  <desc> child, so any element can be traced back to the source material;
- text is real <text> (never outlined), wrapped into explicit tspans.
"""
from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from .helv import wrap_text
from .scene import Scene, Rect, Ellipse, Line, Arrow, Polyline, Polygon, Circle, Text

FONT_STACK = "Helvetica, Arial, 'Noto Sans', 'DejaVu Sans', sans-serif"


def _fmt(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _desc(child_indent: str, d: str) -> str:
    if not d:
        return ""
    return f"\n{child_indent}<desc>{escape(d)}</desc>"


def write_svg(scene: Scene, path: str) -> dict:
    """Serialize scene to `path`. Returns {bytes, elements, layers}."""
    parts: list[str] = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_fmt(scene.width)}" '
        f'height="{_fmt(scene.height)}" viewBox="0 0 {_fmt(scene.width)} {_fmt(scene.height)}">'
    )
    parts.append(f"<title>{escape(scene.title or 'Graphical abstract')}</title>")
    if scene.desc:
        parts.append(f"<desc>{escape(scene.desc)}</desc>")
    # arrowhead markers, one per colour actually used
    colors = sorted({a.stroke for _, a in ((l, i) for l in scene.layers for i in l.items)
                     if isinstance(a, Arrow)}, key=str)
    if colors:
        parts.append("<defs>")
        for c in colors:
            cid = "arrow-" + c.lstrip("#").lower()
            parts.append(
                f'<marker id="{cid}" viewBox="0 0 10 10" refX="9" refY="5" '
                f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{c}"/></marker>'
            )
        parts.append("</defs>")
    if scene.background and scene.background != "none":
        parts.append(
            f'<rect id="canvas-background" x="0" y="0" width="{_fmt(scene.width)}" '
            f'height="{_fmt(scene.height)}" fill="{scene.background}"/>'
        )

    n_elem = 0
    for lay in scene.layers:
        title_attr = f" data-title={quoteattr(lay.title)}" if lay.title else ""
        parts.append(f'<g id="layer-{lay.lid}"{title_attr}>')
        for it in lay.items:
            n_elem += 1
            d = _desc("    ", it.desc)
            if isinstance(it, Rect):
                rx = f' rx="{_fmt(it.rx)}"' if it.rx else ""
                dash = f' stroke-dasharray="{it.dash}"' if it.dash else ""
                parts.append(
                    f'  <rect id="{it.pid}" x="{_fmt(it.x)}" y="{_fmt(it.y)}" '
                    f'width="{_fmt(it.w)}" height="{_fmt(it.h)}" fill="{it.fill}" '
                    f'stroke="{it.stroke}" stroke-width="{_fmt(it.stroke_w)}"{rx}{dash}>{d}</rect>'
                )
            elif isinstance(it, Ellipse):
                parts.append(
                    f'  <ellipse id="{it.pid}" cx="{_fmt(it.cx)}" cy="{_fmt(it.cy)}" '
                    f'rx="{_fmt(it.rx)}" ry="{_fmt(it.ry)}" fill="{it.fill}" '
                    f'stroke="{it.stroke}" stroke-width="{_fmt(it.stroke_w)}">{d}</ellipse>'
                )
            elif isinstance(it, Circle):
                parts.append(
                    f'  <circle id="{it.pid}" cx="{_fmt(it.cx)}" cy="{_fmt(it.cy)}" '
                    f'r="{_fmt(it.r)}" fill="{it.fill}" stroke="{it.stroke}" '
                    f'stroke-width="{_fmt(it.stroke_w)}">{d}</circle>'
                )
            elif isinstance(it, Line):
                dash = f' stroke-dasharray="{it.dash}"' if it.dash else ""
                parts.append(
                    f'  <line id="{it.pid}" x1="{_fmt(it.x1)}" y1="{_fmt(it.y1)}" '
                    f'x2="{_fmt(it.x2)}" y2="{_fmt(it.y2)}" stroke="{it.stroke}" '
                    f'stroke-width="{_fmt(it.stroke_w)}"{dash}/>'
                )
            elif isinstance(it, Arrow):
                dash = f' stroke-dasharray="{it.dash}"' if it.dash else ""
                marker = f' marker-end="url(#arrow-{it.stroke.lstrip("#").lower()})"'
                parts.append(
                    f'  <line id="{it.pid}" x1="{_fmt(it.x1)}" y1="{_fmt(it.y1)}" '
                    f'x2="{_fmt(it.x2)}" y2="{_fmt(it.y2)}" stroke="{it.stroke}" '
                    f'stroke-width="{_fmt(it.stroke_w)}"{dash}{marker}/>'
                )
            elif isinstance(it, Polyline):
                pts = " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in it.pts)
                dash = f' stroke-dasharray="{it.dash}"' if it.dash else ""
                parts.append(
                    f'  <polyline id="{it.pid}" points="{pts}" fill="{it.fill}" '
                    f'stroke="{it.stroke}" stroke-width="{_fmt(it.stroke_w)}"{dash}/>'
                )
            elif isinstance(it, Polygon):
                pts = " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in it.pts)
                parts.append(
                    f'  <polygon id="{it.pid}" points="{pts}" fill="{it.fill}" '
                    f'stroke="{it.stroke}" stroke-width="{_fmt(it.stroke_w)}"/>'
                )
            elif isinstance(it, Text):
                mw = it.meta.get("max_width")
                lines = wrap_text(it.text, it.size, mw, it.bold) if mw else it.text.split("\n")
                anchor = {"left": "start", "center": "middle", "right": "end"}[it.align]
                weight = "bold" if it.bold else "normal"
                tspans = []
                for i, ln in enumerate(lines):
                    dy = "0" if i == 0 else f"{_fmt(it.size * 1.28)}"
                    tspans.append(
                        f'<tspan x="{_fmt(it.x)}" dy="{dy}">{escape(ln)}</tspan>'
                    )
                parts.append(
                    f'  <text id="{it.pid}" x="{_fmt(it.x)}" y="{_fmt(it.y)}" '
                    f'font-family="{FONT_STACK}" font-size="{_fmt(it.size)}" '
                    f'font-weight="{weight}" fill="{it.color}" '
                    f'text-anchor="{anchor}">{d}{"".join(tspans)}</text>'
                )
        parts.append("</g>")
    parts.append("</svg>")
    svg = "\n".join(parts) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    return {"bytes": len(svg.encode("utf-8")), "elements": n_elem,
            "layers": len(scene.layers)}
