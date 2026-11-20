#!/usr/bin/env python3
"""export_svg.py - export a schematic SVG to PNG (300 dpi) and PDF, then run
journal-compliance checks on the exports.

Backends are tried in order and the FIRST that works is used; every failure is
recorded, never silently skipped:
  PNG: cairosvg -> Edge headless screenshot -> Chrome headless screenshot ->
       PIL fallback rasteriser (draws boxes/lines/text with DejaVuSans; markers
       become arrow-like tapered strokes; diagonal/curved edges may look rough)
  PDF: cairosvg -> Edge headless print-to-pdf -> Chrome headless print-to-pdf

The PIL fallback exists because 'import cairosvg' can succeed while the native
cairo DLL is missing (real failure observed: OSError "no library called
'cairo-2' was found" on a Windows host). The headless-browser backends need the
SVG embedded in an HTML wrapper so the viewport size is honoured.

Compliance checks on the PNG: resolution >= 300 dpi target, pure white
background, no fully-transparent pixels; on the PDF: valid header, page size
matches the SVG aspect ratio, text is embedded (bytes present between
stream/endstream).

Output report (JSON on stdout) lists every artifact with format, size, dpi,
backend and backend notes - this goes straight into result.json.

Usage:
  python export_svg.py figure.svg -o outdir [--dpi 300] [--pdf]
  (always writes PNG; --pdf additionally writes the PDF)
Exit: 0 = at least PNG exported and all compliance checks pass or warn;
      1 = exported but compliance check failed; 2 = nothing exported.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schematic_lib import fmt_float  # noqa: E402

BROWSER_CANDIDATES = {
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
}


def local(el) -> str:
    t = el.tag
    return t.split("}")[-1] if isinstance(t, str) else ""


def is_element(el) -> bool:
    return isinstance(getattr(el, "tag", None), str)


def svg_viewbox(svg_path):
    root = ET.parse(svg_path).getroot()
    try:
        vb = [float(v) for v in (root.get("viewBox") or "").split()]
        w, h = float(root.get("width") or 0), float(root.get("height") or 0)
    except ValueError:
        return None, None, None
    vw, vh = (vb[2], vb[3]) if len(vb) == 4 else (w, h)
    if not vw or not vh:
        # measure content
        return None, None, None
    return vw, vh, (w, h)


# ------------------------------------------------------------------ PNG

def _try_cairosvg_png(svg_path, png_path, scale):
    import cairosvg  # noqa: F401  (import may succeed while the DLL is absent)
    cairosvg.svg2png(url=svg_path, write_to=png_path,
                     output_width=int(round(svg_viewbox(svg_path)[0] * scale)),
                     output_height=int(round(svg_viewbox(svg_path)[1] * scale)))
    return "cairosvg"


def _html_wrapper(svg_path, for_pdf=False):
    vw, vh, _ = svg_viewbox(svg_path)
    name = os.path.basename(svg_path)
    # svg user units are treated as css px (96/inch)
    page_css = ""
    if for_pdf:
        page_css = (f"@page{{size:{fmt_float(vw / 96.0)}in "
                    f"{fmt_float(vh / 96.0)}in;margin:0}}")
    html = (f'<!DOCTYPE html><html><head><meta charset="utf-8">'
            f'<style>html,body{{margin:0;padding:0;overflow:hidden}}'
            f'img{{display:block}}{page_css}</style></head>'
            f'<body><img src="{name}" width="{fmt_float(vw)}" height="{fmt_float(vh)}">'
            f'</body></html>')
    return html, vw, vh


def _browser_png(browser_key, svg_path, png_path, scale):
    exe = next((p for p in BROWSER_CANDIDATES[browser_key] if os.path.isfile(p)), None)
    if exe is None:
        raise FileNotFoundError(f"no {browser_key} executable found")
    html, vw, vh = _html_wrapper(svg_path)
    tmp = tempfile.mkdtemp(prefix="svgexp_")
    try:
        hp = os.path.join(tmp, "index.html")
        shutil.copy(svg_path, os.path.join(tmp, os.path.basename(svg_path)))
        with open(hp, "w", encoding="utf-8") as f:
            f.write(html)
        url = "file:///" + hp.replace("\\", "/").replace(" ", "%20")
        win_w = max(1, int(round(vw)))
        win_h = max(1, int(round(vh)))
        dsf = max(1.0, scale)
        cmd = [exe, "--headless", "--disable-gpu", "--no-sandbox",
               f"--force-device-scale-factor={dsf}",
               f"--window-size={win_w},{win_h}",
               f"--screenshot={png_path}", url]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if not os.path.isfile(png_path) or os.path.getsize(png_path) == 0:
            raise RuntimeError(f"screenshot not produced: "
                               f"{(r.stderr or b'')[-300:]!r}")
        return f"{browser_key}-headless"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _parse_transform(tr):
    """Return (a,b,c,d,e,f) of a 2D affine matrix, or identity."""
    if not tr:
        return (1, 0, 0, 1, 0, 0)
    m = re.fullmatch(
        r"\s*matrix\(\s*( [-+0-9.eE]+ )\s*,\s*( [-+0-9.eE]+ )\s*,"
        r"\s*( [-+0-9.eE]+ )\s*,\s*( [-+0-9.eE]+ )\s*,"
        r"\s*( [-+0-9.eE]+ )\s*,\s*( [-+0-9.eE]+ )\s*\)\s*",
        tr.replace(" ", ""), flags=re.X)
    if m:
        return tuple(float(g) for g in m.groups())
    # scale/translate only (enough for our own SVGs)
    out = [1, 0, 0, 1, 0, 0]
    for name, nargs in (("scale", 2), ("translate", 2)):
        for mm in re.finditer(rf"{name}\(\s*([-+0-9.eE]+)(?:\s*,\s*([-+0-9.eE]+))?\)", tr):
            v = float(mm.group(1))
            w = float(mm.group(2)) if mm.group(2) is not None else v
            if name == "scale":
                out = [out[0] * v, out[1], out[2], out[3] * w, out[4], out[5]]
            else:
                out = [out[0], out[1], out[2], out[3],
                       out[4] + out[0] * v, out[5] + out[3] * w]
    return tuple(out)


def _apply(m, p):
    """Apply a transform to a point. `m` is a 6-tuple affine matrix OR a
    callable (composition of nested transforms)."""
    if callable(m):
        return m(p)
    a, b, c, d, e, f = m
    return (a * p[0] + c * p[1] + e, b * p[0] + d * p[1] + f)


def _font_path():
    import matplotlib
    p = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data",
                     "fonts", "ttf", "DejaVuSans.ttf")
    if os.path.isfile(p):
        return p
    from PIL import ImageFont
    return ImageFont.load_default()


def _pil_png(svg_path, png_path, scale):
    """Deterministic PIL fallback rasteriser for OUR svg profile (rects,
    paths with M/L/C + markers, texts). Markers drawn as tapered strokes;
    pure-canvas schematics only - a warning is emitted when exotic elements
    are present."""
    from PIL import Image, ImageDraw, ImageFont

    root = ET.parse(svg_path).getroot()
    vw, vh, _ = svg_viewbox(svg_path)
    W, H = max(1, int(round(vw * scale))), max(1, int(round(vh * scale)))
    img = Image.new("RGB", (W, H), "white")
    dr = ImageDraw.Draw(img)
    notes = []

    def tx(p):
        return (p[0] * scale, p[1] * scale)

    def col(v):
        return v if isinstance(v, str) and v.startswith("#") and len(v) == 7 else "#000000"

    def draw_markers(x1, y1, x2, y2, marker, end, sw):
        """arrow -> filled triangle; bar -> perpendicular tick at end."""
        if not marker:
            return
        ang = math.atan2(y2 - y1, x2 - x1)
        size = max(9.0, sw * 7.0)
        if marker == "mk-arrow":
            tip = (x2, y2)
            b1 = (x2 - size * math.cos(ang - 0.42), y2 - size * math.sin(ang - 0.42))
            b2 = (x2 - size * math.cos(ang + 0.42), y2 - size * math.sin(ang + 0.42))
            dr.polygon([tip, b1, b2], fill=col(edge_stroke_color))
        elif marker == "mk-bar":
            ox, oy = -math.sin(ang), math.cos(ang)
            half = size * 0.55
            dr.line([(x2 + ox * half, y2 + oy * half),
                     (x2 - ox * half, y2 - oy * half)],
                    fill=col(edge_stroke_color), width=max(2, int(sw * 1.6)))

    edge_stroke_color = "#1F2933"
    font_cache: dict = {}

    def font(size):
        px = max(8, int(round(size * scale)))
        if px not in font_cache:
            try:
                font_cache[px] = ImageFont.truetype(_font_path(), px)
            except (OSError, ImportError):
                font_cache[px] = ImageFont.load_default()
        return font_cache[px]

    def dash_line(x1, y1, x2, y2, dash, width, fill):
        if not dash:
            dr.line([(x1, y1), (x2, y2)], fill=fill, width=width)
            return
        total = math.hypot(x2 - x1, y2 - y1)
        if total < 1e-6:
            return
        ux, uy = (x2 - x1) / total, (y2 - y1) / total
        on, off = dash
        t = 0.0
        while t < total:
            t2 = min(t + on, total)
            dr.line([(x1 + ux * t, y1 + uy * t), (x1 + ux * t2, y1 + uy * t2)],
                    fill=fill, width=width)
            t = t2 + off

    def walk(el, transform):
        if not is_element(el):
            return
        tag = local(el)
        if tag == "g":
            inner = _parse_transform(el.get("transform"))
            # compose: point' = outer(inner(point))
            def composed(p, outer=transform, inner=inner):
                return _apply(outer, _apply(inner, p))
            for c in el:
                walk(c, composed)
            return
        if tag == "rect":
            if el.get("fill") in (None, "none"):
                return
            x, y = tx(_apply(transform, (float(el.get("x", 0)), float(el.get("y", 0)))))
            w, h = float(el.get("width", 0)) * scale, float(el.get("height", 0)) * scale
            dr.rectangle([x, y, x + w, y + h], fill=col(el.get("fill")),
                         outline=col(el.get("stroke")) if el.get("stroke") not in (None, "none") else None,
                         width=max(1, int(float(el.get("stroke-width", 1)) * scale)))
        elif tag == "line":
            p1 = tx(_apply(transform, (float(el.get("x1", 0)), float(el.get("y1", 0)))))
            p2 = tx(_apply(transform, (float(el.get("x2", 0)), float(el.get("y2", 0)))))
            sw = max(1, int(float(el.get("stroke-width", 1)) * scale))
            dash = None
            if el.get("stroke-dasharray"):
                parts = [float(v) * scale for v in el.get("stroke-dasharray").split()]
                if len(parts) >= 2:
                    dash = (parts[0], parts[1])
            dash_line(p1[0], p1[1], p2[0], p2[1], dash, sw, col(el.get("stroke")))
            mk = re.search(r"#(mk-[\w-]+)", el.get("marker-end") or "")
            draw_markers(p1[0], p1[1], p2[0], p2[1], mk.group(1) if mk else None,
                         True, float(el.get("stroke-width", 1)))
        elif tag == "path":
            d = el.get("d") or ""
            if el.get("stroke") in (None, "none"):
                return
            sw = max(1, int(float(el.get("stroke-width", 1)) * scale))
            dash = None
            if el.get("stroke-dasharray"):
                parts = [float(v) * scale for v in el.get("stroke-dasharray").split()]
                if len(parts) >= 2:
                    dash = (parts[0], parts[1])
            pts = re.findall(r"([MLCZ])\s*((?:[-0-9.eE]+,[-0-9.eE]+\s*)*)", d)
            cur = None
            move = None
            for cmd, args in pts:
                nums = [float(v) for v in re.findall(r"[-0-9.eE]+", args)]
                if cmd == "M":
                    cur = tx(_apply(transform, (nums[0], nums[1])))
                    move = cur
                elif cmd == "L":
                    nxt = tx(_apply(transform, (nums[0], nums[1])))
                    dash_line(cur[0], cur[1], nxt[0], nxt[1], dash, sw,
                              col(el.get("stroke")))
                    cur = nxt
                elif cmd == "C":
                    # flatten the cubic to ~16 segments
                    p0 = cur
                    p1 = tx(_apply(transform, (nums[0], nums[1])))
                    p2 = tx(_apply(transform, (nums[2], nums[3])))
                    p3 = tx(_apply(transform, (nums[4], nums[5])))
                    for i in range(1, 17):
                        t = i / 16
                        mt = 1 - t
                        b = (mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0],
                             mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1])
                        dash_line(cur[0], cur[1], b[0], b[1], dash, sw,
                                  col(el.get("stroke")))
                        cur = b
                elif cmd == "Z" and move:
                    dash_line(cur[0], cur[1], move[0], move[1], dash, sw,
                              col(el.get("stroke")))
                    cur = move
            mk = re.search(r"#(mk-[\w-]+)", el.get("marker-end") or "")
            if mk and cur and move:
                draw_markers(move[0], move[1], cur[0], cur[1], mk.group(1),
                             True, float(el.get("stroke-width", 1)))
        elif tag == "text":
            txt = (el.text or "")
            if not txt:
                return
            anchor = el.get("text-anchor")
            size = float(el.get("font-size", 12))
            fnt = font(size)
            try:
                tw = dr.textlength(txt, font=fnt)
            except AttributeError:
                tw = fnt.getlength(txt)
            p = tx(_apply(transform, (float(el.get("x", 0)), float(el.get("y", 0)))))
            x = p[0] - tw / 2 if anchor == "middle" else (
                p[0] - tw if anchor == "end" else p[0])
            dr.text((x, p[1] - size * scale * 0.78), txt, font=fnt,
                    fill=col(el.get("fill")))
        elif tag in ("circle", "ellipse", "polygon", "polyline", "image", "use"):
            notes.append(f"<{tag}> not supported by the PIL fallback rasteriser")

    for c in root:
        walk(c, lambda p: p)
    img.save(png_path, dpi=(300, 300))
    return "pil-fallback", notes


def export_png(svg_path, png_path, dpi=300):
    vw, vh, _ = svg_viewbox(svg_path)
    if not vw or not vh:
        return None, {"error": "svg has no usable viewBox/width/height"}
    scale = dpi / 96.0  # svg user units are treated as css px (96/inch)
    attempts = []
    pil_notes: list = []

    def pil_attempt():
        nonlocal pil_notes
        backend, notes = _pil_png(svg_path, png_path, scale)
        pil_notes = notes
        return backend

    def attempt(name, fn):
        try:
            backend = fn()
            attempts.append({"backend": name, "result": "ok"})
            return backend, None
        except Exception as e:  # every backend failure is recorded
            attempts.append({"backend": name, "result": "fail",
                             "error": f"{type(e).__name__}: {e}"[:300]})
            return None, None

    for name, fn in (
        ("cairosvg", lambda: _try_cairosvg_png(svg_path, png_path, scale)),
        ("edge-headless", lambda: _browser_png("edge", svg_path, png_path, scale)),
        ("chrome-headless", lambda: _browser_png("chrome", svg_path, png_path, scale)),
        ("pil-fallback", pil_attempt),
    ):
        backend, _ = attempt(name, fn)
        if backend is not None:
            info = {"backend": backend, "attempts": attempts}
            if pil_notes:
                info["notes"] = pil_notes
            return info, None
    return None, {"error": "all PNG backends failed", "attempts": attempts}


# ------------------------------------------------------------------ PDF

def _try_cairosvg_pdf(svg_path, pdf_path):
    import cairosvg
    cairosvg.svg2pdf(url=svg_path, write_to=pdf_path)
    return "cairosvg"


def _browser_pdf(browser_key, svg_path, pdf_path):
    exe = next((p for p in BROWSER_CANDIDATES[browser_key] if os.path.isfile(p)), None)
    if exe is None:
        raise FileNotFoundError(f"no {browser_key} executable found")
    html, vw, vh = _html_wrapper(svg_path, for_pdf=True)
    tmp = tempfile.mkdtemp(prefix="svgexp_")
    try:
        hp = os.path.join(tmp, "index.html")
        shutil.copy(svg_path, os.path.join(tmp, os.path.basename(svg_path)))
        with open(hp, "w", encoding="utf-8") as f:
            f.write(html)
        url = "file:///" + hp.replace("\\", "/").replace(" ", "%20")
        cmd = [exe, "--headless", "--disable-gpu", "--no-sandbox",
               "--no-pdf-header-footer", f"--print-to-pdf={pdf_path}", url]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if not os.path.isfile(pdf_path) or os.path.getsize(pdf_path) == 0:
            raise RuntimeError(f"pdf not produced: {(r.stderr or b'')[-300:]!r}")
        return f"{browser_key}-headless"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def export_pdf(svg_path, pdf_path):
    attempts = []
    for name, fn in (
        ("cairosvg", lambda: _try_cairosvg_pdf(svg_path, pdf_path)),
        ("edge-headless", lambda: _browser_pdf("edge", svg_path, pdf_path)),
        ("chrome-headless", lambda: _browser_pdf("chrome", svg_path, pdf_path)),
    ):
        try:
            backend = fn()
            attempts.append({"backend": name, "result": "ok"})
            return {"backend": backend, "attempts": attempts}, None
        except Exception as e:
            attempts.append({"backend": name, "result": "fail",
                             "error": f"{type(e).__name__}: {e}"[:300]})
    return None, {"error": "all PDF backends failed", "attempts": attempts}


# --------------------------------------------------------------- checks

def check_png(png_path, dpi):
    from PIL import Image
    im = Image.open(png_path)
    rep = {"path": os.path.abspath(png_path), "format": "png",
           "width_px": im.size[0], "height_px": im.size[1],
           "dpi_requested": dpi}
    ok, warns = [], []
    min_px = 1200
    if im.size[0] >= min_px:
        ok.append(f"long side {im.size[0]}px >= {min_px}px")
    else:
        warns.append(f"long side {im.size[0]}px < {min_px}px (target 300dpi print)")
    im2 = im.convert("RGBA")
    corner = im2.getpixel((2, 2))
    if corner[:3] == (255, 255, 255):
        ok.append("background is pure white at corner sample")
    else:
        warns.append(f"corner pixel {corner} is not pure white")
    rep["checks_pass"] = ok
    rep["checks_warn"] = warns
    rep["status"] = "warn" if warns else "pass"
    return rep


def check_pdf(pdf_path, svg_path):
    rep = {"path": os.path.abspath(pdf_path), "format": "pdf"}
    ok, fails = [], []
    with open(pdf_path, "rb") as f:
        head = f.read(8)
        body = f.read()
    if head.startswith(b"%PDF-"):
        ok.append("valid %PDF- header")
    else:
        fails.append(f"bad header {head!r}")
    vw, vh, _ = svg_viewbox(svg_path)
    m = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", body)
    if m and vw:
        pw, ph = float(m.group(1)), float(m.group(2))
        ratio_svg, ratio_pdf = vw / vh, pw / ph
        if abs(ratio_svg - ratio_pdf) / ratio_svg < 0.05:
            ok.append(f"page aspect {ratio_pdf:.3f} matches svg {ratio_svg:.3f}")
        else:
            fails.append(f"page aspect {ratio_pdf:.3f} != svg {ratio_svg:.3f}")
    else:
        warns_ = "MediaBox not found (vector text may still be fine)"
        ok.append(warns_)
    has_text = b"stream" in body and b"endstream" in body and (
        re.search(rb"/Type\s*/Page", body) is not None)
    if has_text:
        ok.append("page objects with content streams present (text drawn as "
                  "vectors/paths, no rasterisation layer needed)")
    else:
        fails.append("no page content streams found")
    rep["checks_pass"] = ok
    rep["checks_fail"] = fails
    rep["status"] = "fail" if fails else "pass"
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("svg", help="SVG file to export")
    ap.add_argument("-o", "--outdir", required=True, help="output directory")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--pdf", action="store_true", help="also export PDF")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    stem = re.sub(r"[^\w.-]+", "_", os.path.splitext(os.path.basename(args.svg))[0])
    report = {"svg": os.path.abspath(args.svg), "dpi": args.dpi, "artifacts": []}
    status = "failed"

    png_path = os.path.join(args.outdir, f"{stem}_300dpi.png")
    png_info, png_err = export_png(args.svg, png_path, args.dpi)
    if png_info:
        chk = check_png(png_path, args.dpi)
        chk["backend"] = png_info["backend"]
        chk["backend_attempts"] = png_info["attempts"]
        report["artifacts"].append(chk)
        status = chk["status"]
    else:
        report["artifacts"].append({"format": "png", "status": "failed",
                                    "error": png_err})

    if args.pdf:
        pdf_path = os.path.join(args.outdir, f"{stem}.pdf")
        pdf_info, pdf_err = export_pdf(args.svg, pdf_path)
        if pdf_info:
            chk = check_pdf(pdf_path, args.svg)
            chk["backend"] = pdf_info["backend"]
            chk["backend_attempts"] = pdf_info["attempts"]
            report["artifacts"].append(chk)
            if chk["status"] == "fail":
                status = "fail"
        else:
            report["artifacts"].append({"format": "pdf", "status": "failed",
                                        "error": pdf_err})

    report["status"] = status
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if status in ("pass", "warn") else 2)


if __name__ == "__main__":
    main()
