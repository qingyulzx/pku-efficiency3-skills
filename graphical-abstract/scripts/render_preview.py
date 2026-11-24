#!/usr/bin/env python3
"""render_preview.py — independent rasterization + audit of the built figure.

Two jobs:
  1. Rasterize graphical_abstract.svg -> a preview PNG with whatever renderer
     the machine offers (cairosvg, rsvg-convert, inkscape, ImageMagick).
     This is an *independent* re-render: it shares no code with the builder,
     so a preview that appears means the SVG really renders. When no
     renderer exists, fall back to the builder's own PNG (recorded as a
     fallback, never claimed as independent).
  2. Audit the output bundle: SVG well-formedness, element/text counts,
     named ids, layer groups, PNG existence and pixel size — so a failed
     rasterization still leaves a checkable record instead of silent
     nothing.

Honesty contract: if rasterization is impossible in this environment the
report says so explicitly (render_gap) and the agent must surface it in
result.json instead of claiming a preview that does not exist.

Usage:
  python render_preview.py --svg graphical_abstract.svg --outdir previews [--timeout 120]
Exit codes: 0 = preview produced (or honest fallback), 1 = problems, 2 = bad invocation.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

SVG_NS = "{http://www.w3.org/2000/svg}"


def find_renderer():
    try:
        import cairosvg  # noqa: F401
        return ("cairosvg", "cairosvg")
    except ImportError:
        pass
    for cand in ("rsvg-convert", "inkscape", "magick"):
        if shutil.which(cand):
            return (cand, cand)
    # bare "convert" is ImageMagick's legacy name on Unix, but on Windows it is
    # the system FAT->NTFS disk converter — never accept it there.
    if os.name != "nt" and shutil.which("convert"):
        return ("convert", "convert")
    return None


def rasterize(svg, outdir, timeout, renderer):
    png = os.path.join(outdir, "graphical_abstract_preview.png")
    if renderer is None:
        return {"status": "unavailable",
                "render_gap": "no SVG rasterizer found (cairosvg / "
                              "rsvg-convert / inkscape / ImageMagick); "
                              "independent preview could not be produced "
                              "here — record this honestly in result.json"}
    name = renderer[0]
    try:
        if name == "cairosvg":
            import cairosvg
            cairosvg.svg2png(url=svg, write_to=png)
        elif name == "rsvg-convert":
            subprocess.run([name, "-o", png, svg], check=True,
                           capture_output=True, timeout=timeout)
        elif name == "inkscape":
            subprocess.run([name, svg, "--export-filename", png],
                           check=True, capture_output=True, timeout=timeout)
        else:  # magick / convert
            subprocess.run([name, svg, png], check=True,
                           capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "error",
                "render_gap": "rasterization timed out after %ss" % timeout}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "render_gap": "rasterization failed: %s" % e}
    if not os.path.isfile(png) or os.path.getsize(png) == 0:
        return {"status": "error",
                "render_gap": "renderer %s produced no output" % name}
    return {"status": "ok", "method": name, "png": png,
            "bytes": os.path.getsize(png)}


def png_size(path):
    """Width/height from the PNG IHDR header (no external dependency)."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
            import struct
            w, h = struct.unpack(">II", head[16:24])
            return [w, h]
    except Exception:  # noqa: BLE001
        pass
    try:
        from PIL import Image  # optional
        with Image.open(path) as im:
            return list(im.size)
    except Exception:  # noqa: BLE001
        return None


def audit_bundle(svg, outdir):
    """Check the SVG itself and the sibling exports of the build."""
    problems = []
    out = {"svg": svg}
    try:
        tree = ET.parse(svg)
    except ET.ParseError as e:
        return {"status": "error", "problems": ["SVG not well-formed: %s" % e]}
    root = tree.getroot()
    out["svg_w"] = root.get("width")
    out["svg_h"] = root.get("height")
    n_el, n_text, n_id = 0, 0, 0
    for el in root.iter():
        tag = el.tag.replace(SVG_NS, "")
        if tag == "text":
            n_text += 1
        n_el += 1
        if el.get("id"):
            n_id += 1
    layers = [g.get("id") for g in root.iter(SVG_NS + "g")
              if (g.get("id") or "").startswith("layer-")]
    out["n_elements"], out["n_text"], out["n_with_id"] = n_el, n_text, n_id
    out["layers"] = layers
    if n_text == 0:
        problems.append("SVG contains no <text> elements — "
                        "text is not editable")
    if not layers:
        problems.append("no layer-* groups found")
    exports = {}
    for kind, fname in (("png", "graphical_abstract.png"),
                        ("pdf", "graphical_abstract.pdf")):
        p = os.path.join(os.path.dirname(os.path.abspath(svg)), fname)
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            exports[kind] = {"path": p, "bytes": os.path.getsize(p)}
            if kind == "png":
                exports[kind]["pixels"] = png_size(p)
        else:
            problems.append("missing or empty export: %s" % fname)
    out["exports"] = exports
    out["status"] = "ok" if not problems else "error"
    out["problems"] = problems
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--svg", required=True,
                    help="graphical_abstract.svg from build_figure.py")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args()
    if not os.path.isfile(args.svg):
        print(json.dumps({"status": "error",
                          "reason": "svg not found: %s" % args.svg}))
        sys.exit(2)
    os.makedirs(args.outdir, exist_ok=True)

    render = rasterize(args.svg, args.outdir, args.timeout, find_renderer())
    # honest fallback: independent rasterization unavailable or failed, but
    # the builder produced a PNG -> reuse it, never claim independence.
    if render["status"] != "ok":
        builder_png = os.path.join(
            os.path.dirname(os.path.abspath(args.svg)),
            "graphical_abstract.png")
        if os.path.isfile(builder_png) and os.path.getsize(builder_png) > 0:
            reason = render.get("render_gap") or render.get("status")
            render = {"status": "fallback",
                      "png": builder_png,
                      "note": "independent rasterization unavailable/failed "
                              "(%s); reusing the builder's own PNG export as "
                              "preview — record this honestly in result.json"
                              % reason}

    audit = audit_bundle(args.svg, args.outdir)
    report = {"svg": args.svg, "render": render, "audit": audit}
    report_path = os.path.join(args.outdir, "render_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    ok = audit["status"] == "ok" and render["status"] in ("ok", "fallback")
    print(json.dumps({"status": "ok" if ok else "error",
                      "render": render["status"],
                      "render_gap": render.get("render_gap"),
                      "audit": audit["status"],
                      "problems": audit.get("problems", []),
                      "report": report_path}, ensure_ascii=False))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
