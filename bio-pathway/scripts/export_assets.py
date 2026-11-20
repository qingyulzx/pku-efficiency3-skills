#!/usr/bin/env python3
"""export_assets.py - export the SVG to PNG and PDF with a real fallback chain.

Backend chain (first available wins, the chain used is recorded in the report):
  PNG: cairosvg -> rsvg-convert -> inkscape -> headless chromium ->
       native Pillow re-render from model.json (approximate raster preview)
  PDF: cairosvg -> rsvg-convert -> inkscape -> Pillow (raster PDF from the PNG)

The native fallback re-renders from the model using the same layout code as
render_svg.py, so geometry matches the SVG; it is still labeled 'fallback' in
the report because font metrics differ. A blank-output check runs on every PNG.

Usage:
  python export_assets.py --svg pathway.svg --outdir exports \
      [--model model.json] [--png-width 2400] [--report export-report.json]
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__ out of the skill package
sys.path.insert(0, str(Path(__file__).parent))

SVG_NS = "{http://www.w3.org/2000/svg}"


def try_cairosvg():
    try:
        import cairosvg  # noqa: F401
        return True
    except Exception:
        return False


def which_any(names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def render_png_cairo(svg, out, width):
    import cairosvg
    cairosvg.svg2png(url=str(svg), write_to=str(out), output_width=width)
    return "cairosvg"


def render_png_cli(svg, out, width):
    for tool, cmd in (
        ("rsvg-convert", ["rsvg-convert", "-w", str(width), "-o", str(out), str(svg)]),
        ("inkscape", ["inkscape", str(svg), "--export-type=png",
                      f"--export-filename={out}", f"--export-width={width}"]),
        ("chromium", ["chromium", "--headless", "--no-sandbox",
                      f"--screenshot={out}", "--window-size=1600,1200",
                      "--default-background-color=FFFFFFFF", str(svg)]),
        ("google-chrome", ["google-chrome", "--headless", "--no-sandbox",
                           f"--screenshot={out}", "--window-size=1600,1200",
                           "--default-background-color=FFFFFFFF", str(svg)]),
    ):
        exe = shutil.which(tool)
        if exe:
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=120)
                if Path(out).exists() and Path(out).stat().st_size > 0:
                    return tool
            except (subprocess.SubprocessError, OSError):
                continue
    return None


def load_font(size):
    from PIL import ImageFont
    for cand in ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "C:\\Windows\\Fonts\\arial.ttf"):
        try:
            return ImageFont.truetype(cand, size)
        except Exception:
            continue
    return ImageFont.load_default()


def render_png_fallback(model_path, svg_path, out, width):
    """Native Pillow re-render from the model - same layout, approximate text."""
    import render_svg as rs
    from PIL import Image, ImageDraw
    model = json.loads(Path(model_path).read_text(encoding="utf-8"))
    spec = json.loads((Path(__file__).parent.parent / "references" /
                       "edge-types.json").read_text(encoding="utf-8"))
    layout = rs.compute_layout(model, spec["node_types"])
    W, H = layout["canvas"]
    scale = width / W
    img = Image.new("RGB", (int(W * scale), int(H * scale)), "white")
    draw = ImageDraw.Draw(img)
    f_node = load_font(int(15 * scale))
    f_small = load_font(int(12 * scale))
    f_tiny = load_font(int(10 * scale))

    def S(p):
        return (p[0] * scale, p[1] * scale)

    for band in layout["compartments"]:
        y, h = band["_y"] * scale, band["_h"] * scale
        fill = spec["palette"]["compartment_fills"].get(
            band.get("kind", "region"), "#ffffff") if band.get("kind") != "region" \
            else spec["palette"]["compartment_fills"].get(band["id"], "#ffffff")
        if band.get("kind") == "membrane":
            draw.rectangle([0, y + h / 2 - 6 * scale, img.width, y + h / 2 + 6 * scale],
                           fill="#f2e9dc", outline="#b08d57")
        elif band.get("kind") == "nucleus":
            draw.rounded_rectangle([10 * scale, y, img.width - 10 * scale, y + h],
                                   radius=20 * scale, fill="#eef2fb", outline="#4a5f8a")
        else:
            draw.rectangle([0, y, img.width, y + h], fill=fill)
        draw.text((14 * scale, y + 8 * scale), band.get("label", band["id"]),
                  fill="#666666", font=f_small)

    for ed in model.get("edges", []):
        geom = rs.edge_geometry(ed, layout)
        if geom is None:
            continue
        pts = parse_path_points(geom["d"])
        if len(pts) >= 2:
            flat = flatten(pts)
            draw.line([S(p) for p in flat], fill="#222222",
                      width=max(1, int(1.8 * scale)), joint="curve")
            draw_head(draw, flat[-2], flat[-1], ed, spec, scale)

    for b in layout["boxes"]:
        fill = spec["node_types"].get(b.type, {}).get("fill", "#dbe9f6")
        stroke = spec["node_types"].get(b.type, {}).get("stroke", "#2c5f8a")
        x0, y0 = S((b.x, b.y))
        x1, y1 = S((b.x + b.w, b.y + b.h))
        if b.type in ("molecule", "cell"):
            draw.ellipse([x0, y0, x1, y1], fill=fill, outline=stroke, width=2)
        else:
            draw.rounded_rectangle([x0, y0, x1, y1], radius=8 * scale, fill=fill,
                                   outline=stroke, width=2)
        cx = (x0 + x1) / 2
        draw.text((cx, (y0 + y1) / 2 - 8 * scale), b.label, fill="#111111",
                  font=f_node, anchor="mm")
        if b.sub:
            draw.text((cx, (y0 + y1) / 2 + 9 * scale), b.sub, fill="#555555",
                      font=f_tiny, anchor="mm")
    img.save(out)
    return "pillow-fallback(model re-render)"


def parse_path_points(d):
    import re
    nums = [float(x) for x in re.findall(r"-?\d+\.?\d*", d)]
    if len(nums) < 4 or len(nums) % 2:
        return []
    pts = []
    for i in range(0, len(nums), 2):
        pts.append((nums[i], nums[i + 1]))
    return pts


def flatten(pts):
    """Treat consecutive triples as quadratic Beziers (our renderer's vocabulary)."""
    if len(pts) == 4 and pts[0] != pts[1]:  # M p0 Q c p1 -> 3 unique points
        out = [pts[0]]
        p0, c, p1 = pts[0], pts[1], pts[-1]
        for t in [i / 12 for i in range(1, 13)]:
            mt = 1 - t
            out.append((mt * mt * p0[0] + 2 * mt * t * c[0] + t * t * p1[0],
                        mt * mt * p0[1] + 2 * mt * t * c[1] + t * t * p1[1]))
        return out
    return pts


def draw_head(draw, p_from, p_to, ed, spec, scale):
    import math
    if p_from is None:
        return
    etspec = spec["edge_types"].get(ed["type"], {})
    head = etspec.get("head", "arrow")
    if ed.get("directed") is False:
        head = "none"
    if head == "by-sign":
        head = {"positive": "arrow", "negative": "tbar"}.get(ed.get("sign"), "arrow")
    if head == "none":
        return
    dx, dy = p_to[0] - p_from[0], p_to[1] - p_from[1]
    n = max(math.hypot(dx, dy), 1e-6)
    ux, uy = dx / n, dy / n
    if head == "arrow":
        tipx, tipy = p_to[0] * scale, p_to[1] * scale
        bx, by = tipx - ux * 11 * scale, tipy - uy * 11 * scale
        draw.polygon([(tipx, tipy),
                      (bx - uy * 4.5 * scale, by + ux * 4.5 * scale),
                      (bx + uy * 4.5 * scale, by - ux * 4.5 * scale)], fill="#222222")
    elif head == "tbar":
        tipx, tipy = p_to[0] * scale, p_to[1] * scale
        draw.line([(tipx - uy * 6 * scale, tipy + ux * 6 * scale),
                   (tipx + uy * 6 * scale, tipy - ux * 6 * scale)],
                  fill="#222222", width=max(2, int(2.2 * scale)))
    elif head == "open-arrow":
        tipx, tipy = p_to[0] * scale, p_to[1] * scale
        bx, by = tipx - ux * 11 * scale, tipy - uy * 11 * scale
        draw.polygon([(tipx, tipy),
                      (bx - uy * 4.5 * scale, by + ux * 4.5 * scale),
                      (bx + uy * 4.5 * scale, by - ux * 4.5 * scale)],
                     fill="white", outline="#222222")


def blank_check(png):
    try:
        from PIL import Image
        img = Image.open(png).convert("RGB")
        ext = img.getextrema()
        return all(lo == hi for lo, hi in ext)  # uniform image == blank
    except Exception as exc:
        return f"blank-check unavailable: {exc}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--svg", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--model")
    ap.add_argument("--png-width", type=int, default=2400)
    ap.add_argument("--report")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    svg = Path(args.svg)
    if not svg.exists():
        print(json.dumps({"error": f"svg not found: {svg}"}))
        return 2
    png_path = outdir / (svg.stem + ".png")
    pdf_path = outdir / (svg.stem + ".pdf")
    notes = []
    report = {"svg": str(svg.resolve()), "png": None, "pdf": None, "notes": notes}

    # ---- PNG ----
    backend = None
    if try_cairosvg():
        try:
            backend = render_png_cairo(svg, png_path, args.png_width)
        except Exception as exc:
            notes.append(f"cairosvg failed ({exc}); falling back")
    if backend is None:
        backend = render_png_cli(svg, png_path, args.png_width)
        if backend:
            notes.append("used a CLI backend; PNG width may differ from requested")
    if backend is None and args.model:
        try:
            backend = render_png_fallback(args.model, svg, png_path, args.png_width)
            notes.append("native fallback re-render from model; vector SVG remains "
                         "the authoritative source")
        except Exception as exc:
            notes.append(f"native fallback failed: {exc!r}")
    if backend:
        size = png_path.stat().st_size
        blank = blank_check(png_path)
        report["png"] = {"path": str(png_path.resolve()), "backend": backend,
                         "bytes": size, "requested_width": args.png_width,
                         "blank_check": blank, "status": "ok" if size > 5000 else
                         ("suspicious-small" if size else "empty")}
        if blank is True:
            report["png"]["status"] = "suspicious-blank"
    else:
        report["png"] = {"path": None, "backend": None,
                         "status": "failed",
                         "reason": "no backend available; keep the SVG as the "
                                   "delivered figure and report the failure in "
                                   "result.json (or use browser-automation to "
                                   "screenshot the SVG)"}
        notes.append("PNG export failed on all backends")

    # ---- PDF ----
    backend_pdf = None
    if try_cairosvg():
        try:
            import cairosvg
            cairosvg.svg2pdf(url=str(svg), write_to=str(pdf_path))
            backend_pdf = "cairosvg"
        except Exception as exc:
            notes.append(f"cairosvg pdf failed ({exc}); falling back")
    if backend_pdf is None:
        exe = which_any(["rsvg-convert", "inkscape"])
        if exe:
            try:
                if "rsvg" in exe:
                    subprocess.run([exe, "-f", "pdf", "-o", str(pdf_path), str(svg)],
                                   check=True, capture_output=True, timeout=120)
                    backend_pdf = "rsvg-convert"
                else:
                    subprocess.run([exe, str(svg), "--export-type=pdf",
                                    f"--export-filename={pdf_path}"], check=True,
                                   capture_output=True, timeout=120)
                    backend_pdf = "inkscape"
            except (subprocess.SubprocessError, OSError) as exc:
                notes.append(f"CLI pdf backend failed: {exc}")
    if backend_pdf is None and report["png"].get("path"):
        try:
            from PIL import Image
            img = Image.open(report["png"]["path"]).convert("RGB")
            img.save(pdf_path, "PDF", resolution=150)
            backend_pdf = "pillow-raster"
            notes.append("PDF is a raster conversion of the PNG (vector PDF "
                         "backends unavailable); the SVG stays the editable vector "
                         "source")
        except Exception as exc:
            notes.append(f"pillow pdf failed: {exc!r}")
    if backend_pdf:
        report["pdf"] = {"path": str(pdf_path.resolve()), "backend": backend_pdf,
                         "bytes": pdf_path.stat().st_size, "status": "ok"}
    else:
        report["pdf"] = {"path": None, "backend": None, "status": "failed",
                         "reason": "no PDF backend available; deliver SVG + PNG and "
                                   "report the failure"}

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    failed = [k for k in ("png", "pdf") if report[k]["status"] == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
