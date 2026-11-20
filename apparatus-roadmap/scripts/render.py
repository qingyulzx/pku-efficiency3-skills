#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render.py -- setup-roadmap skill renderer.

Reads an intermediate representation (IR, see references/ir_schema.md) and
produces a layered, editable SVG figure, plus optional PNG / PDF exports.

Layout is computed in two phases: a pure geometry pass (layout_*) measures
every box and corridor, the canvas is then sized to fit the content (never
cropping it), and only afterwards a draw pass (draw_*) emits primitives.
This makes canvas overflow structurally impossible for IR content; any text
that would still leave the canvas is recorded in the sidecar geometry
report as an overflow warning instead of being silently clipped.

Layers in the SVG (each is a <g> that can be hidden/edited independently):
  layer-frame      canvas border, title block
  layer-structure  component glyphs, connection polylines, arrowheads
  layer-annotation labels, condition tags, legend, uncertainty notes
  layer-source     visible source index (id -> location), provenance block

Every structural element carries:
  data-id, data-type/kind, data-from/to, data-medium, data-source-loc
  plus <title> (label) and <desc> (verbatim source quote).

Outputs:
  <outdir>/<name>.svg
  <outdir>/<name>.geometry.json   (boxes, anchors, overflow warnings, fonts)
  <outdir>/<name>.png             (with --also-png; needs a usable font)
  <outdir>/<name>.pdf             (with --also-pdf; vector via cairosvg if
                                   available, otherwise raster via Pillow)

Usage:
  python render.py intermediate.json --outdir /app/output [--name figure]
         [--also-png] [--also-pdf] [--png-scale 2] [--font PATH]

Pure standard library for the SVG; Pillow is used for PNG / raster-PDF;
cairosvg is used for vector PDF when installed (optional).
"""
import argparse
import datetime as _dt
import html
import json
import math
import os
import re
import sys

LAYER_FRAME = "layer-frame"
LAYER_STRUCT = "layer-structure"
LAYER_ANNOT = "layer-annotation"
LAYER_SOURCE = "layer-source"

CJK_RE = re.compile(u"[\u2e80-\u9fff\u3000-\u303f\uff00-\uffef\u2160-\u217f]")
SVG_NS = "http://www.w3.org/2000/svg"


def esc(s):
    return html.escape(str(s), quote=True)


def pil_color(c):
    """Translate SVG color strings for PIL; 'none'/None -> transparent."""
    if c is None or c == "none":
        return None
    return c


def has_cjk(s):
    return bool(CJK_RE.search(s or ""))


def est_width(s, size):
    """Approximate rendered width of s at font size `size` (px)."""
    w = 0.0
    for ch in s:
        if CJK_RE.match(ch):
            w += size * 1.02
        elif ch in u" iIl.,;:'\"|!()[]":
            w += size * 0.34
        elif ch.isupper() or ch.isdigit():
            w += size * 0.66
        else:
            w += size * 0.56
    return w


def wrap_text(s, max_width, size):
    """Greedy wrap: latin words stay whole, CJK breaks per character."""
    if not s:
        return [""]
    units = re.findall(r"[A-Za-z0-9][A-Za-z0-9./%°±\-–—μΩ^_]*|\s+|\S", s)
    lines, cur, cur_w = [], "", 0.0
    for u in units:
        uw = est_width(u, size)
        if u.isspace() and cur_w == 0.0:
            continue
        if cur_w + uw > max_width and cur.strip():
            lines.append(cur.rstrip())
            cur, cur_w = ("", 0.0) if u.isspace() else (u, uw)
        else:
            cur += u
            cur_w += uw
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [""]


# ----------------------------------------------------------------------------
# Font discovery (for the optional raster passes)
# ----------------------------------------------------------------------------
FONT_CANDIDATES = [
    # Windows
    r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc", r"C:\Windows\Fonts\Deng.ttf",
    # Linux (common distro layouts)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    # latin-only fallback
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    r"C:\Windows\Fonts\arial.ttf",
]


def find_fonts(extra=None):
    """Return (cjk_font_path_or_None, latin_font_path_or_None, notes)."""
    notes = []
    paths = []
    if extra:
        paths.append(extra)
    env = os.environ.get("SETUP_ROADMAP_FONT")
    if env:
        paths.append(env)
    paths.extend(FONT_CANDIDATES)
    cjk = latin = None
    for p in paths:
        if p and os.path.isfile(p):
            base = os.path.basename(p).lower()
            has_cjk_glyphs = any(k in base for k in
                                 ("msyh", "simhei", "simsun", "notosanscjk",
                                  "wqy", "pingfang", "heiti", "deng"))
            if has_cjk_glyphs and cjk is None:
                cjk = p
            if latin is None:
                latin = p
    if cjk is None:
        notes.append("no CJK-capable font file found; CJK text in the PNG "
                     "pass cannot be drawn (SVG keeps real text).")
    return cjk, latin, notes


class Painter(object):
    """Dual canvas: SVG element strings per layer + optional PIL raster.

    The PIL image is allocated lazily at the *first* draw call, using the
    canvas size current at that moment (the layout pass may still resize
    the canvas before drawing starts).
    """

    def __init__(self, width, height, also_png=False, font=None,
                 png_scale=1.0, font_family="sans-serif"):
        self.w, self.h = int(width), int(height)
        self.layers = {LAYER_FRAME: [], LAYER_STRUCT: [],
                       LAYER_ANNOT: [], LAYER_SOURCE: []}
        self.defs = []
        self.font_family = font_family
        self.overflow = []
        self.png = None
        self.font_notes = []
        self.want_png = also_png
        self.font_arg = font
        self.png_scale = png_scale
        self._pil = None
        self.img = None
        self.draw = None

    def _ensure_pil(self):
        if self._pil is not None or not self.want_png:
            return
        try:
            from PIL import Image, ImageDraw, ImageFont
            self._pil = {"Image": Image, "ImageDraw": ImageDraw,
                         "ImageFont": ImageFont}
            self.cjk_font, self.latin_font, self.font_notes = find_fonts(
                self.font_arg)
            pw = max(1, int(self.w * self.png_scale))
            ph = max(1, int(self.h * self.png_scale))
            self.img = Image.new("RGB", (pw, ph), "white")
            self.draw = ImageDraw.Draw(self.img)
        except ImportError:
            self.font_notes.append("Pillow not installed; raster export "
                                   "skipped.")
            self._pil = None

    def resize(self, w, h):
        """Grow the canvas (only legal before the first draw call)."""
        if self.draw is not None:
            raise RuntimeError("resize() called after drawing started")
        self.w, self.h = int(max(self.w, w)), int(max(self.h, h))

    # -- font handling for PIL -------------------------------------------
    def _font(self, size, cjk):
        if not self._pil:
            return None
        ImageFont = self._pil["ImageFont"]
        path = self.cjk_font if (cjk and self.cjk_font) else self.latin_font
        if not path:
            return None
        try:
            return ImageFont.truetype(path, int(size * self.png_scale))
        except Exception:
            return None

    # -- primitives: each writes SVG and (if enabled) PIL ----------------
    def line(self, layer, x1, y1, x2, y2, stroke="#1a1a1a", width=1.6,
             dash=None, arrow=False):
        dash_s = ' stroke-dasharray="%s"' % dash if dash else ""
        m = ' marker-end="url(#arrow)"' if arrow else ""
        self.layers[layer].append(
            '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
            'stroke-width="%.2f"%s%s/>' % (x1, y1, x2, y2, esc(stroke), width,
                                            dash_s, m))
        if self._pil and self.draw is not None:
            s = self.png_scale
            self.draw.line([x1 * s, y1 * s, x2 * s, y2 * s],
                           fill=pil_color(stroke),
                           width=max(1, int(width * s)))
            if arrow:
                self._arrow_head(x2, y2, x1, y1, stroke, width)

    def polyline(self, layer, pts, stroke="#1a1a1a", width=1.6, dash=None,
                 arrow=False):
        if len(pts) < 2:
            return
        p_s = " ".join("%.1f,%.1f" % (p[0], p[1]) for p in pts)
        dash_s = ' stroke-dasharray="%s"' % dash if dash else ""
        m = ' marker-end="url(#arrow)"' if arrow else ""
        self.layers[layer].append(
            '<polyline points="%s" fill="none" stroke="%s" stroke-width="%.2f"%s%s/>'
            % (p_s, esc(stroke), width, dash_s, m))
        if self._pil and self.draw is not None:
            s = self.png_scale
            self.draw.line([(p[0] * s, p[1] * s) for p in pts],
                           fill=pil_color(stroke),
                           width=max(1, int(width * s)),
                           joint="curve")
            if arrow:
                (x2, y2), (x1, y1) = pts[-1], pts[-2]
                self._arrow_head(x2, y2, x1, y1, stroke, width)

    def _arrow_head(self, x, y, fx, fy, stroke, width):
        ang = math.atan2(y - fy, x - fx)
        L = max(7.0, 4.0 * width)
        a1 = (x - L * math.cos(ang - 0.42), y - L * math.sin(ang - 0.42))
        a2 = (x - L * math.cos(ang + 0.42), y - L * math.sin(ang + 0.42))
        s = self.png_scale
        self.draw.polygon([(x * s, y * s), (a1[0] * s, a1[1] * s),
                           (a2[0] * s, a2[1] * s)], fill=stroke)

    def polygon(self, layer, pts, fill="#ffffff", stroke="#1a1a1a", width=1.4):
        p_s = " ".join("%.1f,%.1f" % (p[0], p[1]) for p in pts)
        self.layers[layer].append(
            '<polygon points="%s" fill="%s" stroke="%s" stroke-width="%.2f"/>'
            % (p_s, esc(fill), esc(stroke), width))
        if self._pil and self.draw is not None:
            s = self.png_scale
            self.draw.polygon([(p[0] * s, p[1] * s) for p in pts],
                              fill=pil_color(fill), outline=pil_color(stroke),
                              width=max(1, int(width * s)))

    def rect(self, layer, x, y, w, h, rx=0, fill="#ffffff", stroke="#1a1a1a",
             width=1.4, dash=None):
        rx_s = ' rx="%.1f"' % rx if rx else ""
        dash_s = ' stroke-dasharray="%s"' % dash if dash else ""
        self.layers[layer].append(
            '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f"%s fill="%s" '
            'stroke="%s" stroke-width="%.2f"%s/>'
            % (x, y, w, h, rx_s, esc(fill), esc(stroke), width, dash_s))
        if self._pil and self.draw is not None:
            s = self.png_scale
            self.draw.rectangle([x * s, y * s, (x + w) * s, (y + h) * s],
                                fill=pil_color(fill),
                                outline=pil_color(stroke),
                                width=max(1, int(width * s)))

    def circle(self, layer, cx, cy, r, fill="#ffffff", stroke="#1a1a1a",
               width=1.4):
        self.layers[layer].append(
            '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" stroke="%s" '
            'stroke-width="%.2f"/>' % (cx, cy, r, esc(fill), esc(stroke),
                                       width))
        if self._pil and self.draw is not None:
            s = self.png_scale
            self.draw.ellipse([(cx - r) * s, (cy - r) * s, (cx + r) * s,
                               (cy + r) * s],
                              fill=pil_color(fill), outline=pil_color(stroke),
                              width=max(1, int(width * s)))

    def ellipse(self, layer, cx, cy, rx, ry, fill="#ffffff", stroke="#1a1a1a",
                width=1.4):
        self.layers[layer].append(
            '<ellipse cx="%.1f" cy="%.1f" rx="%.1f" ry="%.1f" fill="%s" '
            'stroke="%s" stroke-width="%.2f"/>'
            % (cx, cy, rx, ry, esc(fill), esc(stroke), width))
        if self._pil and self.draw is not None:
            s = self.png_scale
            self.draw.ellipse([(cx - rx) * s, (cy - ry) * s, (cx + rx) * s,
                               (cy + ry) * s],
                              fill=pil_color(fill), outline=pil_color(stroke),
                              width=max(1, int(width * s)))

    def text(self, layer, x, y, s, size=13, anchor="start", fill="#111111",
             halo=True, weight="normal", style="normal"):
        if s is None or s == "":
            return
        self._ensure_pil()
        # overflow detection (records, never silently clips)
        tw = est_width(str(s), size)
        if anchor == "middle":
            x0, x1 = x - tw / 2.0, x + tw / 2.0
        elif anchor == "end":
            x0, x1 = x - tw, x
        else:
            x0, x1 = x, x + tw
        if x0 < 4 or x1 > self.w - 4 or y < 4 or y > self.h - 2:
            self.overflow.append({"text": str(s)[:40], "x0": round(x0, 1),
                                  "x1": round(x1, 1), "y": round(y, 1),
                                  "canvas": [self.w, self.h]})
        halo_s = (' paint-order="stroke" stroke="#ffffff" stroke-width="3" '
                  'stroke-linejoin="round"') if halo else ""
        w_s = ' font-weight="%s"' % weight if weight != "normal" else ""
        st_s = ' font-style="%s"' % style if style != "normal" else ""
        self.layers[layer].append(
            '<text x="%.1f" y="%.1f" font-size="%.1f" text-anchor="%s" '
            'fill="%s" font-family="%s"%s%s%s>%s</text>'
            % (x, y, size, anchor, esc(fill), esc(self.font_family),
               halo_s, w_s, st_s, html.escape(str(s))))
        if self._pil and self.draw is not None:
            f = self._font(size, has_cjk(str(s)))
            s_ = self.png_scale
            if f is None:
                if has_cjk(str(s)):
                    # honest: cannot rasterize CJK without a font
                    self.font_notes.append(
                        "CJK text could not be rasterized (no CJK font): %r"
                        % str(s)[:40])
                    return
                f = self._pil["ImageFont"].load_default()
            kw = {}
            anchor_map = {"start": "ls", "middle": "ms", "end": "rs"}
            try:
                kw["anchor"] = anchor_map.get(anchor, "ls")
            except Exception:
                pass
            try:
                self.draw.text((x * s_, y * s_), str(s), font=f,
                               fill=fill, stroke_width=0, **kw)
            except TypeError:
                self.draw.text((x * s_, y * s_), str(s), font=f, fill=fill)

    # -- svg assembly ------------------------------------------------------
    def svg_string(self, title, desc):
        defs = """<defs>
  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke"/>
  </marker>
</defs>"""
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<svg xmlns="%s" width="%d" height="%d" viewBox="0 0 %d %d">'
            % (SVG_NS, self.w, self.h, self.w, self.h),
            '<title>%s</title>' % html.escape(title),
            '<desc>%s</desc>' % html.escape(desc),
            defs,
        ]
        layer_doc = {
            LAYER_FRAME: "canvas border and title block",
            LAYER_STRUCT: "structural elements: component glyphs and connections",
            LAYER_ANNOT: "labels, condition tags, legend, uncertainty notes",
            LAYER_SOURCE: "source index and provenance",
        }
        for name in (LAYER_FRAME, LAYER_STRUCT, LAYER_ANNOT, LAYER_SOURCE):
            parts.append('<g id="%s" data-purpose="%s">'
                         % (name, esc(layer_doc[name])))
            parts.extend(self.layers[name])
            parts.append("</g>")
        parts.append("</svg>")
        return "\n".join(parts)

    def save_png(self, path):
        self._ensure_pil()
        if self._pil is None or self.img is None:
            return None
        self.img.save(path, "PNG")
        return path

    def save_pdf(self, path, svg_text):
        """Export PDF: vector via cairosvg when available, else raster."""
        self._ensure_pil()
        try:
            import cairosvg  # optional
            cairosvg.svg2pdf(bytestring=svg_text.encode("utf-8"),
                             write_to=path)
            return {"path": path, "mode": "vector",
                    "engine": "cairosvg"}
        except ImportError:
            pass
        except Exception as exc:
            self.font_notes.append("cairosvg failed (%s); using raster PDF"
                                   % exc)
        if self._pil is None or self.img is None:
            return None
        try:
            self.img.save(path, "PDF", resolution=96.0 * self.png_scale)
            return {"path": path, "mode": "raster",
                    "engine": "Pillow", "dpi": 96.0 * self.png_scale}
        except Exception as exc:
            self.font_notes.append("PDF export failed: %s" % exc)
            return None


# ----------------------------------------------------------------------------
# Style palette / media colors
# ----------------------------------------------------------------------------
MEDIA_PALETTE = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e",
                 "#8c564b", "#17becf", "#bcbd22", "#e377c2", "#7f7f7f"]
KIND_STYLE = {
    "material": {"dash": None, "note": u"实线：物料/气体流动"},
    "signal": {"dash": "6,4", "note": u"虚线：信号/电连接"},
    "energy": {"dash": "2,3", "note": u"点线：能量/热量传递"},
    "inferred": {"dash": "5,4", "note": u"虚线(推断)：材料未明示的连接"},
}


def medium_color(medium, cache):
    key = (medium or "").strip() or u"未标注介质"
    if key not in cache:
        cache[key] = MEDIA_PALETTE[len(cache) % len(MEDIA_PALETTE)]
    return cache[key]


def line_params(conn, cache):
    kind = conn.get("kind", "material")
    style = KIND_STYLE.get(kind, KIND_STYLE["material"])
    color = medium_color(conn.get("medium"), cache)
    if conn.get("certainty") == "inferred":
        style = KIND_STYLE["inferred"]
        color = "#7f7f7f"
    width = 1.8 if kind == "material" else 1.4
    return color, style["dash"], width


# ----------------------------------------------------------------------------
# Apparatus figure
# ----------------------------------------------------------------------------
def glyph_box_size(comp):
    """Return (w, h, label_lines, spec_lines) for a component."""
    label = str(comp.get("label") or comp.get("id"))
    size = 13
    w = max(120.0, min(300.0, est_width(label, size) + 46))
    label_lines = wrap_text(label, w - 18, size)
    specs = comp.get("specs") or []
    spec_lines = []
    for sp in specs:
        if isinstance(sp, dict):
            txt = u"%s: %s" % (sp.get("key", ""), sp.get("value", ""))
        else:
            txt = str(sp)
        spec_lines.extend(wrap_text(txt, w - 16, 11))
    h = 58 + 15 * len(spec_lines) + 14 * (len(label_lines) - 1)
    return w, h, label_lines, spec_lines


def draw_component_glyph(p, comp, x, y, w, h):
    """Draw the P&ID-style glyph for a component inside box (x,y,w,h).

    Glyph conventions follow references/symbol_library.md (informed by
    common P&ID practice). Unknown types fall back to a rounded box.
    """
    t = (comp.get("type") or "other").lower()
    cx, cy = x + w / 2.0, y + h / 2.0
    uncertain = comp.get("certainty") in ("unspecified_spec", "uncertain")
    dash = "5,4" if uncertain else None
    stroke = "#8a6d00" if uncertain else "#1a1a1a"
    fill = "#fffdf5" if uncertain else "#ffffff"

    def tag_uncertain():
        if uncertain:
            p.text(LAYER_ANNOT, x + w, y + 10, u"△ 规格未提供·示意", size=10,
                   anchor="end", fill="#8a6d00")

    if t in ("gas_source", "gas_tank", "tank", "cylinder"):
        # gas cylinder: rectangle with domed top
        bw = min(w - 26, 74)
        bh = min(h - 34, 46)
        p.polygon(LAYER_STRUCT, [(cx - bw / 2, y + 26), (cx + bw / 2, y + 26),
                                 (cx + bw / 2, y + 26 + bh),
                                 (cx - bw / 2, y + 26 + bh)],
                  fill=fill, stroke=stroke, width=1.6)
        p.ellipse(LAYER_STRUCT, cx, y + 24, bw / 2, 6, fill=fill, stroke=stroke)
        p.line(LAYER_STRUCT, cx, y + 18, cx, y + 24, stroke=stroke, width=1.6)
        p.line(LAYER_STRUCT, cx - 8, y + 14, cx + 8, y + 18, stroke=stroke,
               width=1.6)
    elif t in ("valve",):
        bw = min(w - 30, 66)
        p.polygon(LAYER_STRUCT,
                  [(cx - bw / 2, cy - 13), (cx, cy), (cx - bw / 2, cy + 13)],
                  fill=fill, stroke=stroke)
        p.polygon(LAYER_STRUCT,
                  [(cx + bw / 2, cy - 13), (cx, cy), (cx + bw / 2, cy + 13)],
                  fill=fill, stroke=stroke)
    elif t in ("pump", "vacuum_pump", "scroll_pump", "turbomolecular_pump"):
        r = min(h - 30, w - 40, 44) / 2.0
        p.circle(LAYER_STRUCT, cx, cy, r, fill=fill, stroke=stroke, width=1.8)
        p.polygon(LAYER_STRUCT, [(cx - r * 0.45, cy - r * 0.6),
                                 (cx + r * 0.55, cy),
                                 (cx - r * 0.45, cy + r * 0.6)],
                  fill=fill, stroke=stroke)
    elif t in ("mfc", "flow_controller", "mass_flow_controller"):
        bw = min(w - 26, 80)
        bh = 34
        p.rect(LAYER_STRUCT, cx - bw / 2, cy - bh / 2, bw, bh, fill=fill,
               stroke=stroke, width=1.6)
        # orifice-plate symbol: two touching triangles inside
        p.polygon(LAYER_STRUCT, [(cx - 16, cy - 9), (cx - 3, cy),
                                 (cx - 16, cy + 9)], fill="none", stroke=stroke)
        p.polygon(LAYER_STRUCT, [(cx + 16, cy - 9), (cx + 3, cy),
                                 (cx + 16, cy + 9)], fill="none", stroke=stroke)
    elif t in ("filter",):
        bw = min(w - 26, 74)
        bh = 34
        p.rect(LAYER_STRUCT, cx - bw / 2, cy - bh / 2, bw, bh, fill=fill,
               stroke=stroke, width=1.6)
        p.line(LAYER_STRUCT, cx - bw / 2 + 6, cy - bh / 2 + 6,
               cx + bw / 2 - 6, cy - bh / 2 + 6, stroke=stroke, width=1.0)
        p.line(LAYER_STRUCT, cx - bw / 2 + 6, cy + bh / 2 - 6,
               cx + bw / 2 - 6, cy + bh / 2 - 6, stroke=stroke, width=1.0)
        for i in range(1, 4):
            fx = cx - bw / 2 + i * bw / 4.0
            p.line(LAYER_STRUCT, fx, cy - bh / 2 + 6, fx, cy + bh / 2 - 6,
                   stroke=stroke, width=0.9, dash="3,2")
    elif t in ("adsorber", "column", "reactor", "trap"):
        bw = min(w - 34, 64)
        bh = min(h - 26, 54)
        p.rect(LAYER_STRUCT, cx - bw / 2, cy - bh / 2, bw, bh, fill=fill,
               stroke=stroke, width=1.6)
        for i in range(1, 5):
            hx = cx - bw / 2 + i * bw / 5.0
            p.line(LAYER_STRUCT, hx, cy - bh / 2 + 4, hx, cy + bh / 2 - 4,
                   stroke=stroke, width=0.8)
    elif t in ("chamber", "vessel", "detector", "detector_chamber",
               "load_lock", "process_chamber"):
        bw = min(w - 26, 86)
        bh = min(h - 30, 48)
        p.rect(LAYER_STRUCT, cx - bw / 2, cy - bh / 2, bw, bh, rx=10,
               fill=fill, stroke=stroke, width=1.8)
        p.circle(LAYER_STRUCT, cx, cy, 11, fill="none", stroke=stroke,
                 width=1.4)
        p.line(LAYER_STRUCT, cx, cy - 11, cx, cy + 11, stroke=stroke, width=1.0)
        p.line(LAYER_STRUCT, cx - 11, cy, cx + 11, cy, stroke=stroke, width=1.0)
    elif t in ("sensor", "gauge", "pressure_gauge", "temperature_sensor"):
        r = min(h - 34, 22) / 2.0 + 4
        p.circle(LAYER_STRUCT, cx, cy - 4, r, fill=fill, stroke=stroke,
                 width=1.6)
        p.line(LAYER_STRUCT, cx, cy - 4, cx - 12, cy + 16, stroke=stroke,
               width=1.4)
        p.line(LAYER_STRUCT, cx, cy - 4, cx + 12, cy + 16, stroke=stroke,
               width=1.4)
        p.text(LAYER_ANNOT, cx, cy - 1, "P" if "pressure" in t else "T",
               size=10, anchor="middle", fill=stroke, halo=False)
    elif t in ("heater", "furnace", "heating_belt"):
        bw = min(w - 26, 84)
        bh = 34
        p.rect(LAYER_STRUCT, cx - bw / 2, cy - bh / 2, bw, bh, fill=fill,
               stroke=stroke, width=1.6)
        pts, x0 = [], cx - bw / 2 + 6
        seg = (bw - 12) / 6.0
        for i in range(7):
            pts.append((x0 + i * seg, cy + (8 if i % 2 == 0 else -8)))
        p.polyline(LAYER_STRUCT, pts, stroke=stroke, width=1.3)
    elif t in ("cooler", "dewar", "cryostat"):
        bw = min(w - 26, 84)
        bh = min(h - 30, 48)
        p.rect(LAYER_STRUCT, cx - bw / 2 - 6, cy - bh / 2 - 6, bw + 12,
               bh + 12, rx=8, fill="none", stroke=stroke, width=1.2, dash="4,3")
        p.rect(LAYER_STRUCT, cx - bw / 2, cy - bh / 2, bw, bh, rx=6,
               fill=fill, stroke=stroke, width=1.6)
    elif t in ("electronics", "power", "controller", "readout", "amplifier",
               "power_supply"):
        bw = min(w - 26, 86)
        bh = min(h - 30, 44)
        p.rect(LAYER_STRUCT, cx - bw / 2, cy - bh / 2, bw, bh, fill=fill,
               stroke=stroke, width=1.6)
        p.line(LAYER_STRUCT, cx - 10, cy + bh / 2 - 8, cx + 10, cy + bh / 2 - 8,
               stroke=stroke, width=1.8)
        p.line(LAYER_STRUCT, cx, cy + bh / 2 - 8, cx, cy + bh / 2 - 14,
               stroke=stroke, width=1.8)  # ground symbol
        p.text(LAYER_ANNOT, cx, cy - 4, comp.get("short_mark") or "E",
               size=12, anchor="middle", fill=stroke, halo=False)
    elif t in ("source", "radon_source", "sample_source", "sputter_source",
               "ion_beam_source"):
        r = min(h - 34, 26) / 2.0 + 4
        p.circle(LAYER_STRUCT, cx, cy, r, fill="#fde9d9", stroke=stroke,
                 width=1.6)
        for dx, dy in ((-6, -4), (4, -7), (7, 5), (-4, 7), (0, 0)):
            p.circle(LAYER_STRUCT, cx + dx, cy + dy, 1.6, fill=stroke,
                     stroke=stroke, width=0.8)
    else:
        p.rect(LAYER_STRUCT, x + 13, y + 20, w - 26, h - 34, rx=6, fill=fill,
               stroke=stroke, width=1.5, dash=dash)
    tag_uncertain()


def _assign_columns(ids, rels):
    """Longest-path column assignment (cycles tolerated, converges)."""
    col = {i: 0 for i in ids}
    for _ in range(max(1, len(ids))):
        changed = False
        for r in rels:
            f, t = r["from"], r["to"]
            if f in col and t in col and r.get("route") != "below":
                if col[t] < col[f] + 1:
                    col[t] = col[f] + 1
                    changed = True
        if not changed:
            break
    return col


def layout_apparatus(ir):
    """Pure geometry pass for an apparatus figure (no drawing)."""
    comps = ir.get("components", [])
    conns = ir.get("connections", [])
    idx = {c["id"]: i for i, c in enumerate(comps)}
    sizes = {c["id"]: glyph_box_size(c) for c in comps}

    connected = set()
    for cn in conns:
        connected.add(cn["from"])
        connected.add(cn["to"])
    isolated = [c for c in comps if c["id"] not in connected]

    col = _assign_columns([c["id"] for c in comps],
                          [{"from": cn["from"], "to": cn["to"],
                            "route": cn.get("route")} for cn in conns])
    if isolated:
        max_col = max([col[c["id"]] for c in comps] + [0])
        for c in isolated:
            col[c["id"]] = max_col + 1

    columns = {}
    for c in comps:
        columns.setdefault(col[c["id"]], []).append(c)
    for k in columns:
        columns[k].sort(key=lambda c: idx[c["id"]])

    margin_x, top, col_gap = 60, 70, 130
    col_w = {k: max(sizes[c["id"]][0] for c in cs) for k, cs in columns.items()}
    col_x, x = {}, margin_x
    for k in sorted(columns):
        col_x[k] = x
        x += col_w[k] + col_gap
    max_h = max(sizes[c["id"]][1] for c in comps) if comps else 60
    row_h = max_h + 46
    pos = {}
    for k, cs in columns.items():
        for r, c in enumerate(cs):
            w, h, _l, _s = sizes[c["id"]]
            pos[c["id"]] = (col_x[k], top + r * row_h + 14)
    n_rows = max((len(cs) for cs in columns.values()), default=1)
    below_y = top + n_rows * row_h + 30

    # connection classification (needed for corridor sizing + legend)
    cache = {}
    legend_items = []
    seen = set()
    backward = {}
    below_slot = 0
    for cn in conns:
        f, t = cn["from"], cn["to"]
        is_back = (col.get(t, 0) <= col.get(f, 0)) or cn.get("route") == "below"
        backward[cn["id"]] = is_back
        if is_back:
            below_slot += 1
        color, dash, lw = line_params(cn, cache)
        key = ((cn.get("medium") or u"未标注介质").strip(), color,
               cn.get("kind", "material"))
        if key not in seen:
            seen.add(key)
            legend_items.append(key)

    # extents
    max_x = margin_x
    max_y = top
    for c in comps:
        w, h, _l, spec_lines = sizes[c["id"]]
        px, py = pos[c["id"]]
        max_x = max(max_x, px + w)
        max_y = max(max_y, py + h + 14 * len(spec_lines))
    corridor_bottom = below_y + 30 * max(below_slot, 1)
    legend_top = corridor_bottom + 34
    legend_h = 18 + 17 * len(legend_items)
    max_y = max(max_y, legend_top + legend_h)
    if isolated:
        k = max(columns)
        max_x = max(max_x, col_x[k] +
                    max(sizes[c["id"]][0] for c in isolated) + 24)

    return {
        "comps": comps, "conns": conns, "idx": idx, "sizes": sizes,
        "isolated": isolated, "col": col, "columns": columns, "col_x": col_x,
        "pos": pos, "below_y": below_y, "below_slot": below_slot,
        "backward": backward, "legend_items": legend_items,
        "extents": {"max_x": max_x, "max_y": max_y,
                    "legend_top": legend_top, "legend_h": legend_h},
        "margin_x": margin_x, "top": top,
    }


def draw_apparatus(L, p, geom):
    comps, conns = L["comps"], L["conns"]
    sizes, pos, col = L["sizes"], L["pos"], L["col"]

    # --- draw components ---
    for c in comps:
        cid = c["id"]
        w, h, label_lines, spec_lines = sizes[cid]
        x, y = pos[cid]
        loc = c.get("source", {}).get("location", "")
        p.layers[LAYER_STRUCT].append(
            '<g id="%s" data-id="%s" data-type="%s" data-source-loc="%s">'
            % (esc(cid), esc(cid), esc(c.get("type", "other")), esc(loc)))
        p.layers[LAYER_STRUCT].append(
            "<title>%s</title>" % html.escape(c.get("label") or cid))
        quote = (c.get("source") or {}).get("quote", "")
        if quote:
            p.layers[LAYER_STRUCT].append(
                "<desc>source quote: %s</desc>" % html.escape(quote))
        draw_component_glyph(p, c, x, y, w, h)
        p.layers[LAYER_STRUCT].append("</g>")
        # label + id tag + specs (annotation layer)
        p.layers[LAYER_ANNOT].append('<!-- label for %s -->' % esc(cid))
        ty = y + h - 6 - 14 * (len(label_lines) - 1)
        for ln in label_lines:
            p.text(LAYER_ANNOT, x + w / 2, ty, ln, size=13, anchor="middle",
                   weight="bold")
            ty += 14
        p.text(LAYER_ANNOT, x + 2, y + 11, cid, size=9.5, fill="#666666",
               halo=False)
        yy = y + h + 14
        for sl in spec_lines:
            p.text(LAYER_ANNOT, x + w / 2, yy, sl, size=10.5, anchor="middle",
                   fill="#333333")
            yy += 13.5
        geom["elements"][cid] = {
            "type": c.get("type"), "box": [x, y, w, h],
            "label": c.get("label"),
            "anchors": {"left": [x, y + h / 2], "right": [x + w, y + h / 2],
                        "top": [x + w / 2, y], "bottom": [x + w / 2, y + h]},
        }

    # --- draw connections ---
    below_y = L["below_y"]
    below_slot = 0
    for cn in conns:
        cid = cn["id"]
        f, t = cn["from"], cn["to"]
        if f not in pos or t not in pos:
            raise ValueError("connection %s references unknown component "
                             "(%s -> %s)" % (cid, f, t))
        color, dash, lw = line_params(cn, {})
        fx, fy = pos[f]
        fw, fh, _fl, _fs = sizes[f]
        tx, ty = pos[t]
        tw, th, _tl, _ts = sizes[t]
        backward = L["backward"][cid]
        if not backward:
            # forward: right edge -> vertical channel -> left edge
            y1, y2 = fy + fh / 2, ty + th / 2
            if abs(y1 - y2) < 1:
                pts = [(fx + fw, y1), (tx, y1)]
            else:
                ch = tx - 26 - 18 * (below_slot % 3)
                ch = max(ch, fx + fw + 18)
                pts = [(fx + fw, y1), (ch, y1), (ch, y2), (tx, y2)]
        else:
            # backward / explicit below: bottom exit, lower corridor, target
            yc = below_y + 30 * below_slot
            below_slot += 1
            pts = [(fx + fw / 2, fy + fh), (fx + fw / 2, yc),
                   (tx + tw / 2, yc), (tx + tw / 2, ty + th)]
        loc = (cn.get("source") or {}).get("location", "")
        p.layers[LAYER_STRUCT].append(
            '<g id="%s" data-id="%s" data-from="%s" data-to="%s" '
            'data-medium="%s" data-kind="%s" data-source-loc="%s">'
            % (esc(cid), esc(cid), esc(f), esc(t),
               esc(cn.get("medium") or ""), esc(cn.get("kind", "material")),
               esc(loc)))
        if (cn.get("source") or {}).get("quote"):
            p.layers[LAYER_STRUCT].append(
                "<desc>source quote: %s</desc>"
                % html.escape(cn["source"]["quote"]))
        p.polyline(LAYER_STRUCT, pts, stroke=color, width=lw, dash=dash,
                   arrow=True)
        p.layers[LAYER_STRUCT].append("</g>")
        # connection label at midpoint of longest segment (clamped in-canvas)
        mx, my = polyline_midpoint(pts)
        mx = min(max(mx, 90.0), p.w - 90.0)
        label_parts = []
        if cn.get("medium"):
            label_parts.append(str(cn["medium"]))
        for cd_ in (cn.get("conditions") or []):
            if isinstance(cd_, dict):
                label_parts.append(u"%s %s" % (cd_.get("key", ""),
                                               cd_.get("value", "")))
            else:
                label_parts.append(str(cd_))
        if cn.get("certainty") == "inferred":
            label_parts.append(u"(连接为推断)")
        if label_parts:
            txt = u"；".join(label_parts)
            lines = wrap_text(txt, 150, 10.5)
            ly = my - 6 - 12 * (len(lines) - 1)
            for ln in lines:
                p.text(LAYER_ANNOT, mx, ly, ln, size=10.5, anchor="middle",
                       fill=color)
                ly += 12
        geom["connections"][cid] = {
            "from": f, "to": t, "points": pts, "end": pts[-1],
            "expected_end": geom["elements"][t]["anchors"]["left"]
            if not backward else geom["elements"][t]["anchors"]["bottom"],
        }

    # --- isolated zone frame ---
    if L["isolated"]:
        k = max(L["columns"])
        zx = L["col_x"][k]
        maxiw = max(sizes[c["id"]][0] for c in L["isolated"])
        zy = L["top"]
        zh = sum(sizes[c["id"]][1] + 40 for c in L["isolated"]) + 30
        p.rect(LAYER_ANNOT, zx - 12, zy - 6, maxiw + 24, zh, rx=8, fill="none",
               stroke="#999999", width=1.0, dash="6,4")
        p.text(LAYER_ANNOT, zx - 2, zy + 12, u"材料未给出连接关系（未连线）",
               size=11, fill="#777777")

    # --- legend ---
    lx = L["margin_x"]
    ly = L["extents"]["legend_top"]
    p.text(LAYER_ANNOT, lx, ly, u"图例 Legend", size=12, weight="bold")
    ly += 18
    for (medium, color, kind) in L["legend_items"]:
        style = KIND_STYLE.get(kind, KIND_STYLE["material"])
        p.line(LAYER_ANNOT, lx, ly - 4, lx + 34, ly - 4, stroke=color,
               width=1.8, dash=style["dash"], arrow=True)
        p.text(LAYER_ANNOT, lx + 42, ly, u"%s（%s）" % (medium, style["note"]),
               size=11)
        ly += 17


def polyline_midpoint(pts):
    segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    seg = max(segs, key=lambda s: abs(s[0][0] - s[1][0]) +
              abs(s[0][1] - s[1][1]))
    return ((seg[0][0] + seg[1][0]) / 2.0, (seg[0][1] + seg[1][1]) / 2.0)


# ----------------------------------------------------------------------------
# Route / flowchart figure (stages, steps, decisions)
# ----------------------------------------------------------------------------
NODE_FILL = {"stage": "#eaf2fb", "step": "#ffffff", "decision": "#fdf6e3",
             "start": "#e8f5e9", "end": "#e8f5e9", "milestone": "#fff8e1"}


def route_node_size(node):
    kind = node.get("kind", "step")
    label = node.get("label") or node.get("id")
    if kind == "decision":
        w = max(150.0, min(260.0, est_width(label, 12) + 80))
        return w, 76, []
    if kind in ("start", "end"):
        w = max(90.0, est_width(label, 13) + 40)
        return w, 40, []
    w = 250
    lines = []
    body = []
    for key in ("objective",):
        v = node.get(key)
        if v:
            body.append((u"目标", v))
    for key, zh in (("methods", u"方法"), ("inputs", u"输入"),
                    ("outputs", u"输出")):
        v = node.get(key)
        if v:
            if isinstance(v, list):
                v = u"；".join(str(x) for x in v)
            body.append((zh, v))
    h = 46
    for k, v in body:
        for ln in wrap_text(u"%s：%s" % (k, v), w - 24, 11.5):
            lines.append(ln)
            h += 16.5
    if node.get("milestone"):
        for ln in wrap_text(u"里程碑：%s" % node["milestone"], w - 24, 11.5):
            lines.append(u"◆ " + ln)
            h += 16.5
    return w, max(h, 66), lines


def layout_route(ir):
    nodes = ir.get("nodes", [])
    edges = ir.get("edges", [])
    idx = {n["id"]: i for i, n in enumerate(nodes)}
    sizes = {n["id"]: route_node_size(n) for n in nodes}

    col = _assign_columns([n["id"] for n in nodes],
                          [{"from": e["from"], "to": e["to"],
                            "route": e.get("route")} for e in edges])
    columns = {}
    for n in nodes:
        columns.setdefault(col[n["id"]], []).append(n)
    for k in columns:
        columns[k].sort(key=lambda n: idx[n["id"]])

    margin_x, top, col_gap = 60, 76, 120
    col_x, x = {}, margin_x
    col_w = {}
    for k in sorted(columns):
        w = max(sizes[n["id"]][0] for n in columns[k])
        col_w[k] = w
        col_x[k] = x
        x += w + col_gap
    row_h = max((sizes[n["id"]][1] for n in nodes), default=60) + 40
    pos = {}
    for k, cs in columns.items():
        for r, n in enumerate(cs):
            w, h, _s = sizes[n["id"]]
            pos[n["id"]] = (col_x[k] + (col_w[k] - w) / 2.0, top + r * row_h)
    n_rows = max((len(cs) for cs in columns.values()), default=1)
    below_y = top + n_rows * row_h + 24

    below_slot = sum(1 for e in edges
                     if (col.get(e["to"], 0) <= col.get(e["from"], 0))
                     or e.get("route") == "below")

    max_x = margin_x
    max_y = top
    for n in nodes:
        w, h, _l = sizes[n["id"]]
        px, py = pos[n["id"]]
        max_x = max(max_x, px + w)
        max_y = max(max_y, py + h + 30)  # +30 for uncertainty captions
    max_y = max(max_y, below_y + 26 * max(below_slot, 1) + 20)

    return {"nodes": nodes, "edges": edges, "idx": idx, "sizes": sizes,
            "col": col, "columns": columns, "col_x": col_x, "col_w": col_w,
            "pos": pos, "below_y": below_y, "below_slot": below_slot,
            "extents": {"max_x": max_x, "max_y": max_y},
            "margin_x": margin_x, "top": top}


def draw_route(L, p, geom):
    nodes, edges = L["nodes"], L["edges"]
    sizes, pos, col = L["sizes"], L["pos"], L["col"]

    for n in nodes:
        nid = n["id"]
        w, h, lines = sizes[nid]
        x, y = pos[nid]
        kind = n.get("kind", "step")
        loc = (n.get("source") or {}).get("location", "")
        p.layers[LAYER_STRUCT].append(
            '<g id="%s" data-id="%s" data-kind="%s" data-source-loc="%s">'
            % (esc(nid), esc(nid), esc(kind), esc(loc)))
        p.layers[LAYER_STRUCT].append(
            "<title>%s</title>" % html.escape(n.get("label") or nid))
        if (n.get("source") or {}).get("quote"):
            p.layers[LAYER_STRUCT].append(
                "<desc>source quote: %s</desc>"
                % html.escape(n["source"]["quote"]))
        uncertain = n.get("certainty") in ("unspecified_spec", "uncertain")
        stroke = "#8a6d00" if uncertain else "#1a1a1a"
        if kind == "decision":
            cx, cy = x + w / 2, y + h / 2
            p.polygon(LAYER_STRUCT, [(x, cy), (cx, y), (x + w, cy),
                                     (cx, y + h)],
                      fill=NODE_FILL[kind], stroke=stroke, width=1.6)
            dls = wrap_text(n.get("label") or nid, w - 60, 12)
            ty = cy - 5 * (len(dls) - 1) + 4
            for ln in dls:
                p.text(LAYER_ANNOT, cx, ty, ln, size=12, anchor="middle",
                       weight="bold")
                ty += 14
        elif kind in ("start", "end"):
            p.rect(LAYER_STRUCT, x, y, w, h, rx=h / 2, fill=NODE_FILL[kind],
                   stroke=stroke, width=1.6)
            p.text(LAYER_ANNOT, x + w / 2, y + h / 2 + 4.5,
                   n.get("label") or nid, size=13, anchor="middle",
                   weight="bold")
        else:
            p.rect(LAYER_STRUCT, x, y, w, h, rx=8, fill=NODE_FILL[kind],
                   stroke=stroke, width=1.6,
                   dash=("5,4" if uncertain else None))
            p.text(LAYER_ANNOT, x + 10, y + 19,
                   u"%s%s" % (n.get("step_no", ""), n.get("label") or nid),
                   size=13, weight="bold")
            p.text(LAYER_ANNOT, x + w - 8, y + 17, nid, size=9.5,
                   anchor="end", fill="#666666", halo=False)
            ty = y + 37
            for ln in lines:
                p.text(LAYER_ANNOT, x + 10, ty, ln, size=11.5, fill="#333333")
                ty += 16.5
        if uncertain:
            p.text(LAYER_ANNOT, x + w / 2, y + h + 12,
                   u"△ 内容未完全确定·示意", size=10, anchor="middle",
                   fill="#8a6d00")
        if n.get("milestone"):
            p.polygon(LAYER_ANNOT, [(x + w - 26, y - 14), (x + w - 6, y - 8),
                                    (x + w - 26, y - 2)],
                      fill="#f5b301", stroke="#7a5c00", width=1.0)
        p.layers[LAYER_STRUCT].append("</g>")
        geom["elements"][nid] = {
            "type": kind, "box": [x, y, w, h], "label": n.get("label"),
            "anchors": {"left": [x, y + h / 2], "right": [x + w, y + h / 2],
                        "top": [x + w / 2, y], "bottom": [x + w / 2, y + h]},
        }

    below_y = L["below_y"]
    below_slot = 0
    for e in edges:
        eid = e.get("id", "E%d" % below_slot)
        f, t = e["from"], e["to"]
        if f not in pos or t not in pos:
            raise ValueError("edge %s references unknown node (%s -> %s)"
                             % (eid, f, t))
        fx, fy = pos[f]
        fw, fh, _fl = sizes[f]
        tx, ty = pos[t]
        tw, th, _tl = sizes[t]
        backward = (col.get(t, 0) <= col.get(f, 0)) or e.get("route") == "below"
        color = "#1a1a1a"
        if e.get("kind") == "loop":
            color = "#7f7f7f"
        if not backward:
            y1, y2 = fy + fh / 2, ty + th / 2
            if abs(y1 - y2) < 1:
                pts = [(fx + fw, y1), (tx, y1)]
            else:
                ch = tx - 30 - 14 * (below_slot % 3)
                ch = max(ch, fx + fw + 18)
                pts = [(fx + fw, y1), (ch, y1), (ch, y2), (tx, y2)]
        else:
            yc = below_y + 26 * below_slot
            below_slot += 1
            pts = [(fx + fw / 2, fy + fh), (fx + fw / 2, yc),
                   (tx + tw / 2, yc), (tx + tw / 2, ty + th)]
        loc = (e.get("source") or {}).get("location", "")
        p.layers[LAYER_STRUCT].append(
            '<g id="%s" data-id="%s" data-from="%s" data-to="%s" '
            'data-kind="%s" data-source-loc="%s">'
            % (esc(eid), esc(eid), esc(f), esc(t), esc(e.get("kind", "main")),
               esc(loc)))
        if (e.get("source") or {}).get("quote"):
            p.layers[LAYER_STRUCT].append(
                "<desc>source quote: %s</desc>"
                % html.escape(e["source"]["quote"]))
        p.polyline(LAYER_STRUCT, pts, stroke=color, width=1.8, arrow=True)
        p.layers[LAYER_STRUCT].append("</g>")
        label = e.get("label") or e.get("condition")
        if label:
            mx, my = polyline_midpoint(pts)
            mx = min(max(mx, 80.0), p.w - 80.0)
            p.text(LAYER_ANNOT, mx, my - 7, str(label), size=11,
                   anchor="middle", fill="#0b4f9e")
        geom["connections"][eid] = {
            "from": f, "to": t, "points": pts, "end": pts[-1],
            "expected_end": geom["elements"][t]["anchors"]["left"]
            if not backward else geom["elements"][t]["anchors"]["bottom"],
        }


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def build_figure(ir, also_png=False, font=None, png_scale=2.0):
    ftype = ir.get("figure_type", "apparatus")
    title = ir.get("title") or u"实验装置/技术路线图"
    geom = {"elements": {}, "connections": {}, "overflow": [],
            "figure_type": ftype, "fonts": {}}

    # phase 1: pure layout
    if ftype == "apparatus":
        L = layout_apparatus(ir)
    elif ftype == "route":
        L = layout_route(ir)
    else:
        raise ValueError("unsupported figure_type %r (expected 'apparatus' "
                         "or 'route')" % ftype)

    # source block height estimate (needed to size the canvas)
    doc = ir.get("source_document") or {}
    def _src_items():
        if ftype == "apparatus":
            for c in ir.get("components", []):
                yield u"%s %s ← %s" % (c["id"], c.get("label", ""),
                                       (c.get("source") or {}).get(
                                           "location", u"位置未标"))
            for cn in ir.get("connections", []):
                yield u"%s %s→%s ← %s" % (cn["id"], cn["from"], cn["to"],
                                          (cn.get("source") or {}).get(
                                              "location", u"位置未标"))
        else:
            for n in ir.get("nodes", []):
                yield u"%s %s ← %s" % (n["id"], n.get("label", ""),
                                       (n.get("source") or {}).get(
                                           "location", u"位置未标"))
            for e in ir.get("edges", []):
                yield u"%s %s→%s ← %s" % (e.get("id", "?"), e["from"],
                                          e["to"],
                                          (e.get("source") or {}).get(
                                              "location", u"位置未标"))
    src_items = list(_src_items())
    n_src_lines = len(src_items) + 2  # header + provenance line
    src_block_h = 14 * n_src_lines + 30

    # phase 2: size canvas (grow, never crop)
    min_w = int(ir.get("canvas", {}).get("width", 0) or 1280)
    min_h = int(ir.get("canvas", {}).get("height", 0) or 820)
    need_w = L["extents"]["max_x"] + 50
    need_h = L["extents"]["max_y"] + src_block_h + 50
    painter = Painter(max(min_w, need_w), max(min_h, need_h),
                      also_png=also_png, font=font, png_scale=png_scale)

    # phase 3: draw
    if ftype == "apparatus":
        draw_apparatus(L, painter, geom)
        y_end = L["extents"]["max_y"]
    else:
        draw_route(L, painter, geom)
        y_end = L["extents"]["max_y"]

    # title block
    painter.text(LAYER_FRAME, painter.w / 2, 34, title, size=19,
                 anchor="middle", weight="bold", halo=False)
    sub = ir.get("subtitle") or ""
    if sub:
        painter.text(LAYER_FRAME, painter.w / 2, 54, sub, size=12,
                     anchor="middle", fill="#444444", halo=False)

    # source layer: per-element source index + provenance
    src_lines = [u"来源索引（元素 → 材料位置）："]
    src_lines.extend(src_items)
    prov = (u"数据来源：%s %s ｜ 生成工具：setup-roadmap skill render.py ｜ "
            u"图层：结构/标注/来源（可在SVG编辑器中分层编辑） ｜ 生成时间：%s"
            % (doc.get("id", u"未标注"), doc.get("title", ""),
               _dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
    src_lines.append(prov)
    sy = y_end + 20
    for ln in src_lines:
        painter.text(LAYER_SOURCE, 24, sy, ln, size=10, fill="#888888",
                     halo=False)
        sy += 13.5
    # canvas border
    painter.rect(LAYER_FRAME, 8, 8, painter.w - 16, painter.h - 16, rx=6,
                 fill="none", stroke="#cccccc", width=1.0)

    geom["canvas"] = [painter.w, painter.h]
    geom["fonts"] = {"cjk": getattr(painter, "cjk_font", None),
                     "latin": getattr(painter, "latin_font", None),
                     "notes": painter.font_notes}
    geom["overflow"] = painter.overflow
    desc = ("Layered editable figure generated from an intermediate "
            "representation. Elements carry data-id and source locations; "
            "verbatim source quotes are stored in each element's <desc> and "
            "in the sidecar geometry report.")
    return painter, geom, desc


def main():
    ap = argparse.ArgumentParser(
        description="Render an apparatus/route IR to layered SVG (+PNG/PDF).")
    ap.add_argument("ir_json")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--name", default=None)
    ap.add_argument("--also-png", action="store_true")
    ap.add_argument("--also-pdf", action="store_true")
    ap.add_argument("--png-scale", type=float, default=2.0)
    ap.add_argument("--font", default=None)
    args = ap.parse_args()

    with open(args.ir_json, "r", encoding="utf-8") as f:
        ir = json.load(f)
    name = args.name or os.path.splitext(
        os.path.basename(args.ir_json))[0].replace("_ir", "")
    painter, geom, desc = build_figure(ir, also_png=args.also_png,
                                       font=args.font,
                                       png_scale=args.png_scale)
    os.makedirs(args.outdir, exist_ok=True)
    svg_path = os.path.join(args.outdir, name + ".svg")
    svg_text = painter.svg_string(ir.get("title") or "figure", desc)
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(svg_text)
    geom_path = os.path.join(args.outdir, name + ".geometry.json")
    with open(geom_path, "w", encoding="utf-8") as f:
        json.dump(geom, f, ensure_ascii=False, indent=1)
    png_path = None
    if args.also_png:
        png_path = painter.save_png(os.path.join(args.outdir, name + ".png"))
    pdf_info = None
    if args.also_pdf:
        pdf_info = painter.save_pdf(os.path.join(args.outdir, name + ".pdf"),
                                    svg_text)
    out = {"svg": svg_path, "geometry": geom_path, "png": png_path,
           "pdf": pdf_info,
           "canvas": geom["canvas"],
           "elements": len(geom["elements"]),
           "connections": len(geom["connections"]),
           "overflow_warnings": geom["overflow"],
           "font_notes": painter.font_notes}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
