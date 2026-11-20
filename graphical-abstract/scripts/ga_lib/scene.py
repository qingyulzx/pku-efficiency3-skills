"""Device-independent scene graph for graphical abstracts.

The builder (model.py) turns a figure_model.json into a Scene; the writers
(svg_writer / mpl_writer / pillow_writer) serialize the same Scene so every
export is guaranteed to agree with the editable SVG source.

Every primitive carries `pid` (public id, becomes the SVG id / matplotlib
gid) and optional `desc` (provenance, becomes <desc> in SVG) and `meta`
(dict kept for the element->source mapping).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------- palette

# Okabe & Ito (2008) colour-blind-safe palette.
OKABE_ITO = {
    "black": "#000000", "orange": "#E69F00", "sky": "#56B4E9",
    "green": "#009E73", "yellow": "#F0E442", "blue": "#0072B2",
    "vermillion": "#D55E00", "purple": "#CC79A7", "grey": "#ADADAD",
}

# Series order chosen for pairwise grey-scale separability.
SERIES_ORDER = ["blue", "orange", "green", "purple", "sky", "vermillion", "grey"]

INK = "#1A1A1A"        # default text
PAPER = "#FFFFFF"      # canvas background
PANEL_BG = "#FFFFFF"
PANEL_EDGE = "#D8D8D8"
MUTED = "#5A5A5A"


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rel_luminance(hexcol: str) -> float:
    """WCAG relative luminance (0=black, 1=white)."""
    r, g, b = (c / 255.0 for c in _hex_to_rgb(hexcol))
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_ratio(a: str, b: str) -> float:
    la, lb = rel_luminance(a), rel_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def series_color(i: int) -> str:
    return OKABE_ITO[SERIES_ORDER[i % len(SERIES_ORDER)]]


def tint(hexcol: str, factor: float) -> str:
    """Blend a colour towards white (factor=0 -> white, 1 -> full colour)."""
    r, g, b = _hex_to_rgb(hexcol)
    r = round(255 - (255 - r) * factor)
    g = round(255 - (255 - g) * factor)
    b = round(255 - (255 - b) * factor)
    return f"#{r:02X}{g:02X}{b:02X}"


# ---------------------------------------------------------------- primitives

@dataclass
class Prim:
    pid: str
    desc: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class Rect(Prim):
    x: float = 0; y: float = 0; w: float = 0; h: float = 0
    fill: str = PAPER; stroke: str = PANEL_EDGE; stroke_w: float = 1.0
    rx: float = 0; dash: str = ""


@dataclass
class Ellipse(Prim):
    cx: float = 0; cy: float = 0; rx: float = 0; ry: float = 0
    fill: str = PAPER; stroke: str = PANEL_EDGE; stroke_w: float = 1.0


@dataclass
class Line(Prim):
    x1: float = 0; y1: float = 0; x2: float = 0; y2: float = 0
    stroke: str = INK; stroke_w: float = 1.0; dash: str = ""


@dataclass
class Arrow(Prim):
    x1: float = 0; y1: float = 0; x2: float = 0; y2: float = 0
    stroke: str = INK; stroke_w: float = 2.0
    head: float = 9.0
    dash: str = ""


@dataclass
class Polyline(Prim):
    pts: list = field(default_factory=list)   # [(x, y), ...]
    stroke: str = INK; stroke_w: float = 2.0
    fill: str = "none"; dash: str = ""


@dataclass
class Polygon(Prim):
    pts: list = field(default_factory=list)
    fill: str = INK; stroke: str = "none"; stroke_w: float = 0


@dataclass
class Circle(Prim):
    cx: float = 0; cy: float = 0; r: float = 0
    fill: str = INK; stroke: str = "none"; stroke_w: float = 0


@dataclass
class Text(Prim):
    x: float = 0; y: float = 0                # anchor point (top of text)
    text: str = ""
    size: float = 16
    bold: bool = False
    color: str = INK
    align: str = "left"                       # left | center | right vs anchor x


# ---------------------------------------------------------------- scene

@dataclass
class Layer:
    lid: str
    title: str = ""
    items: list = field(default_factory=list)


class Scene:
    def __init__(self, width: float, height: float, background: str = PAPER,
                 title: str = "", desc: str = ""):
        self.width = width
        self.height = height
        self.background = background
        self.title = title
        self.desc = desc
        self.layers: list[Layer] = []

    def layer(self, lid: str, title: str = "") -> Layer:
        lay = Layer(lid, title)
        self.layers.append(lay)
        return lay

    def add(self, layer: Layer, item: Prim) -> Prim:
        layer.items.append(item)
        return item

    def iter_items(self):
        for lay in self.layers:
            for item in lay.items:
                yield lay, item

    def bbox(self) -> tuple[float, float, float, float]:
        """(minx, miny, maxx, maxy) over drawn geometry (text estimated)."""
        from .helv import text_width
        xs0, ys0, xs1, ys1 = [], [], [], []
        for _, it in self.iter_items():
            if isinstance(it, Rect):
                xs0.append(it.x); ys0.append(it.y); xs1.append(it.x + it.w); ys1.append(it.y + it.h)
            elif isinstance(it, (Ellipse, Circle)):
                cx, cy = it.cx, it.cy
                rx = it.rx if isinstance(it, Ellipse) else it.r
                ry = it.ry if isinstance(it, Ellipse) else it.r
                xs0.append(cx - rx); ys0.append(cy - ry); xs1.append(cx + rx); ys1.append(cy + ry)
            elif isinstance(it, (Line, Arrow)):
                xs0 += [it.x1, it.x2]; ys0 += [it.y1, it.y2]; xs1 += [it.x1, it.x2]; ys1 += [it.y1, it.y2]
            elif isinstance(it, (Polyline, Polygon)):
                for x, y in it.pts:
                    xs0.append(x); ys0.append(y); xs1.append(x); ys1.append(y)
            elif isinstance(it, Text):
                w = text_width(it.text, it.size, it.bold)
                x0 = it.x - (w / 2 if it.align == "center" else w if it.align == "right" else 0)
                xs0.append(x0); ys0.append(it.y); xs1.append(x0 + w); ys1.append(it.y + it.size * 1.1)
        if not xs0:
            return (0, 0, self.width, self.height)
        return (min(xs0), min(ys0), max(xs1), max(ys1))
