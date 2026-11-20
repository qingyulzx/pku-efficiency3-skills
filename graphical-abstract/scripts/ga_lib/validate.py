"""Post-build checks: traceability, accessibility, geometry and exports.

All checks return issue dicts {severity, code, detail, where}:
  severity "error"   -> the figure must be fixed before delivery
  severity "warning" -> acceptable but must be recorded in result.json limits
"""
from __future__ import annotations

import json
import os
import re


def issue(sev, code, detail, where=""):
    return {"severity": sev, "code": code, "detail": detail, "where": where}


# ---------------------------------------------------------------- SVG checks

def check_svg(svg_path: str, min_font_px: float = 12.0) -> list[dict]:
    issues: list[dict] = []
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(svg_path)
    except ET.ParseError as e:
        return [issue("error", "svg-not-wellformed", f"SVG failed to parse: {e}", svg_path)]
    root = tree.getroot()
    ns = "{http://www.w3.org/2000/svg}"
    vb = root.get("viewBox", "").split()
    if len(vb) != 4:
        return [issue("error", "svg-no-viewbox", "missing viewBox", svg_path)]
    W, H = float(vb[2]), float(vb[3])
    ids = set()
    n_el = 0
    for el in root.iter():
        tag = el.tag.replace(ns, "")
        if tag in ("rect", "text", "line", "ellipse", "circle", "polyline", "polygon"):
            n_el += 1
            eid = el.get("id")
            if not eid:
                issues.append(issue("warning", "svg-anonymous-element",
                                    f"<{tag}> without id", svg_path))
            elif eid in ids:
                issues.append(issue("error", "svg-duplicate-id", f"duplicate id '{eid}'", svg_path))
            else:
                ids.add(eid)
            fs = el.get("font-size")
            if fs:
                try:
                    v = float(fs)
                    if v < min_font_px:
                        issues.append(issue("error", "font-too-small",
                                            f"font-size {v}px < {min_font_px}px on '{eid}'", svg_path))
                except ValueError:
                    pass
            for attr in ("x", "y", "x1", "x2", "y1", "y2", "cx", "cy"):
                a = el.get(attr)
                if a:
                    try:
                        v = float(a)
                        lim = W if attr[0] == "x" or attr == "cx" else H
                        if v < -1 or v > lim + 1:
                            issues.append(issue("error", "canvas-overflow",
                                                f"'{eid}' {attr}={v} outside 0..{lim:.0f}", svg_path))
                    except ValueError:
                        pass
            if tag == "rect":
                try:
                    x, y = float(el.get("x", 0)), float(el.get("y", 0))
                    w, h = float(el.get("width", 0)), float(el.get("height", 0))
                    if x + w > W + 1 or y + h > H + 1:
                        issues.append(issue("error", "canvas-overflow",
                                            f"rect '{el.get('id')}' exceeds canvas ({x + w:.0f},{y + h:.0f})",
                                            svg_path))
                except ValueError:
                    pass
    if n_el == 0:
        issues.append(issue("error", "svg-empty", "no drawable elements found", svg_path))
    return issues


# ------------------------------------------------------------- mapping checks

def check_element_map(element_map: list[dict], source_texts: dict | None = None) -> list[dict]:
    """element_map: list of {id, panel, kind, text, source, encoding}.

    Checks (a) every contentful element carries a source with file+locator+quote,
    (b) numeric claims appear verbatim in their quote, (c) if the caller passes
    source_texts {file: text}, quotes are verified against the actual material.
    """
    issues: list[dict] = []
    for el in element_map:
        kind = el.get("kind")
        src = el.get("source")
        if kind in ("entity", "relation", "datum", "claim", "group") and not src:
            issues.append(issue("warning", "no-source",
                                f"{kind} '{el.get('id')}' has no source; record where it comes from "
                                f"or justify in limits", el.get("panel")))
            continue
        if not src:
            continue
        q = (src.get("quote") or "").strip()
        if not q:
            issues.append(issue("warning", "no-quote",
                                f"'{el.get('id')}' source lacks a verbatim quote", el.get("panel")))
        if not src.get("file"):
            issues.append(issue("warning", "no-file",
                                f"'{el.get('id')}' source lacks a file reference", el.get("panel")))
        if not src.get("locator"):
            issues.append(issue("warning", "no-locator",
                                f"'{el.get('id')}' source lacks a locator (page/section/line)",
                                el.get("panel")))
        if source_texts and src.get("file") in source_texts:
            hay = source_texts[src["file"]]
            norm = lambda s: re.sub(r"\s+", " ", s).strip()
            if norm(q) and norm(q) not in norm(hay):
                issues.append(issue("error", "quote-not-in-source",
                                    f"quote for '{el.get('id')}' not found in {src['file']} "
                                    f"(check wording/page)", el.get("panel")))
        enc = el.get("encoding") or {}
        v = enc.get("value")
        if isinstance(v, (int, float)) and q:
            num = ("%g" % v)
            if not re.search(r"(?<![\d.])" + re.escape(num).replace(r"\.", r"\.?") + r"(?![\d])", q):
                issues.append(issue("warning", "value-not-in-quote",
                                    f"value {num} of '{el.get('id')}' does not appear in its quote; "
                                    f"extend the quote to include the number or explain the derivation",
                                    el.get("panel")))
    return issues


# ------------------------------------------------------------- colour checks

def check_contrast(element_map: list[dict]) -> list[dict]:
    from .scene import contrast_ratio, rel_luminance
    issues: list[dict] = []
    for el in element_map:
        enc = el.get("encoding") or {}
        color = enc.get("color")
        if color and el.get("kind") == "datum":
            cr = contrast_ratio(color, "#FFFFFF")
            if cr < 2.0:
                issues.append(issue("warning", "low-contrast-fill",
                                    f"bar colour {color} vs white background has contrast {cr:.1f}:1 "
                                    f"(grey-scale print risk)", el.get("panel")))
    series = {}
    for el in element_map:
        enc = el.get("encoding") or {}
        if enc.get("channel") in ("length", "position(y)") and enc.get("series"):
            series.setdefault(el.get("panel"), set()).add(enc.get("color"))
    for panel, colors in series.items():
        cl = sorted(colors)
        for a, b in zip(cl, cl[1:]):
            dl = abs(rel_luminance(a) - rel_luminance(b))
            if dl < 0.08:
                issues.append(issue("warning", "grayscale-collision",
                                    f"series colours {a} and {b} in panel '{panel}' are hard to "
                                    f"tell apart in grey scale (|dL|={dl:.2f}); vary lightness too",
                                    panel))
    return issues


# ------------------------------------------------------------- export checks

def check_exports(files: dict) -> list[dict]:
    """files: {'svg': path, 'png': path, 'pdf': path, ...}"""
    issues: list[dict] = []
    for kind, path in files.items():
        if not path:
            issues.append(issue("error", "export-missing", f"{kind} export path is empty"))
            continue
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            issues.append(issue("error", "export-missing", f"{kind} file missing or empty: {path}"))
            continue
        if kind == "pdf":
            with open(path, "rb") as f:
                head = f.read(8)
            if not head.startswith(b"%PDF"):
                issues.append(issue("error", "pdf-invalid", f"{path} does not start with %PDF"))
        if kind == "png":
            try:
                from PIL import Image
                with Image.open(path) as im:
                    if im.format != "PNG":
                        issues.append(issue("error", "png-invalid", f"{path} is not a PNG"))
                    g = im.convert("L").resize((64, 36))
                    px = list(g.getdata())
                    if max(px) - min(px) < 8:
                        issues.append(issue("error", "png-blank",
                                            f"{path} looks blank (no tonal range)"))
            except ImportError:
                issues.append(issue("warning", "png-unchecked",
                                    "Pillow unavailable; PNG could not be inspected"))
    return issues


def run_all(model: dict | None, svg_path: str, exports: dict,
            element_map: list[dict], source_texts: dict | None = None) -> list[dict]:
    issues: list[dict] = []
    min_font = float((model or {}).get("checks", {}).get("min_font_px", 12.0))
    issues += check_svg(svg_path, min_font)
    issues += check_element_map(element_map, source_texts)
    issues += check_contrast(element_map)
    issues += check_exports(exports)
    return issues


def summarize(issues: list[dict]) -> dict:
    errs = [i for i in issues if i["severity"] == "error"]
    warns = [i for i in issues if i["severity"] == "warning"]
    return {"n_errors": len(errs), "n_warnings": len(warns),
            "error_codes": sorted({i["code"] for i in errs}),
            "warning_codes": sorted({i["code"] for i in warns}),
            "pass": len(errs) == 0}
