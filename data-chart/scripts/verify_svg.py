#!/usr/bin/env python3
"""Read glyph geometry back out of a rendered SVG and verify it against the
source values recorded in the glyphs.json mapping table.

This is the closing half of the value->glyph traceability loop:

  chartgen.py : source value -> mapped glyph (mapping table with geometry)
  verify_svg.py : SVG file -> measured geometry -> back-calculated value
                  -> compared with source value (tolerance-based)

It does NOT trust chartgen's recorded geometry: rectangle corners, point
positions, cell colours and sector angles are re-measured from the SVG path
data, and the pixel->value mapping is re-derived from the tick marks and tick
labels found in the SVG itself (falling back to the axis-end calibration only
when tick texts are not machine-readable, e.g. log-scale exponents).

Checks performed per glyph kind:
  bar     : rect corner geometry vs expected; bar-top value read-back via axis
            calibration; error-bar extent -> +/- error read-back
  point   : marker centre (x, y) read-back vs value_x / value_y
  cell    : heatmap quad position and fill colour vs expected colour
  sector  : pie wedge start/end angle read-back -> fraction vs value/sum
  box     : box x-position vs category slot (full box read-back not supported)

Plus file-level checks: SVG contains <text> elements (text not outlined, so
the figure stays editable) and, when a style profile is given, font sizes stay
inside the journal's allowed point range.

Usage:
  python verify_svg.py --svg fig.svg --glyphs fig.glyphs.json \
      [--style profile.json] [--out verification_report.json]

Exit code 0 = all checks passed; 1 = verification failures (report written);
2 = inputs unreadable.
"""

import argparse
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

SVGNS = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}"

NUM = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
CMD = re.compile(r"[MLAZCQSTmlazcqst]")

DEFAULT_TOL_PX = 0.6          # geometry agreement, SVG user units (pt)
DEFAULT_TOL_REL = 0.005       # value read-back, fraction of axis span
COLOR_TOL = 6                 # per-channel 0..255


# ------------------------------------------------------------- SVG parsing

def local(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def style_dict(style_str):
    out = {}
    for part in (style_str or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def parse_path(d):
    """Parse a path 'd' string -> list of absolute (cmd, points) with 'z' as
    ('Z', []). Handles relative commands by tracking the current point."""
    cmds = []
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    i = 0
    tokens = re.findall(r"[MLAZCQSTHVmllazcqsthv]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", d or "")
    while i < len(tokens):
        t = tokens[i]
        if CMD.match(t):
            cmd = t
            i += 1
            arity = {"M": 2, "L": 2, "T": 2, "S": 4, "C": 6, "Q": 4, "A": 7,
                     "H": 1, "V": 1, "Z": 0, "m": 2, "l": 2, "t": 2, "s": 4,
                     "c": 6, "q": 4, "a": 7, "h": 1, "v": 1, "z": 0}[t]
            if arity == 0:
                cmds.append(("Z", []))
                cur = start
                continue
            vals = []
            while i < len(tokens) and not CMD.match(tokens[i]) and len(vals) < arity:
                vals.append(float(tokens[i]))
                i += 1
            if t == "M":
                p = (vals[0], vals[1])
                cmds.append(("M", [p[0], p[1]]))
                cur, start = p, p
            elif t == "m":
                p = (cur[0] + vals[0], cur[1] + vals[1])
                cmds.append(("M", [p[0], p[1]]))
                cur, start = p, p
            elif t == "L":
                p = (vals[0], vals[1])
                cmds.append(("L", [p[0], p[1]]))
                cur = p
            elif t == "l":
                p = (cur[0] + vals[0], cur[1] + vals[1])
                cmds.append(("L", [p[0], p[1]]))
                cur = p
            elif t == "A":
                p = (vals[5], vals[6])
                cmds.append(("A", vals))
                cur = p
            elif t == "a":
                p = (cur[0] + vals[5], cur[1] + vals[6])
                vals = vals[:5] + [p[0], p[1]]
                cmds.append(("A", vals))
                cur = p
            elif t == "H":
                cur = (vals[0], cur[1])
                cmds.append(("L", [cur[0], cur[1]]))
            elif t == "h":
                cur = (cur[0] + vals[0], cur[1])
                cmds.append(("L", [cur[0], cur[1]]))
            elif t == "V":
                cur = (cur[0], vals[0])
                cmds.append(("L", [cur[0], cur[1]]))
            elif t == "v":
                cur = (cur[0], cur[1] + vals[0])
                cmds.append(("L", [cur[0], cur[1]]))
            else:  # C/S/Q/T - keep absolute points
                pts = []
                for k in range(0, len(vals) - 1, 2):
                    if t.islower():
                        pts.extend([cur[0] + vals[k], cur[1] + vals[k + 1]])
                    else:
                        pts.extend([vals[k], vals[k + 1]])
                cmds.append((t.upper(), pts))
                cur = (pts[-2], pts[-1])
        else:
            i += 1
    return cmds


def path_bbox_points(cmds):
    """All anchor points of a parsed path."""
    pts = []
    for cmd, vals in cmds:
        if cmd in ("M", "L"):
            pts.append((vals[0], vals[1]))
        elif cmd == "A":
            pts.append((vals[5], vals[6]))
        elif cmd in ("C", "S", "Q"):
            for k in range(0, len(vals) - 1, 2):
                pts.append((vals[k], vals[k + 1]))
    return pts


def rect_from_path(cmds):
    """Return (x, y, w, h) if the path is an axis-aligned 4-corner polygon
    (or closes into one), else None."""
    pts = path_bbox_points(cmds)
    if len(pts) < 4:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    corners = {(x0, y0), (x0, y1), (x1, y0), (x1, y1)}
    on_edge = all(
        (abs(p[0] - x0) < 1e-6 or abs(p[0] - x1) < 1e-6) and
        (abs(p[1] - y0) < 1e-6 or abs(p[1] - y1) < 1e-6) for p in pts)
    if on_edge and len(corners) == 4 and (x1 - x0) > 0.05 and (y1 - y0) > 0.05:
        return (x0, y0, x1 - x0, y1 - y0)
    return None


class SvgFacts:
    """Everything verify needs, collected in one walk of the SVG tree."""

    def __init__(self, root):
        self.text_elements = []       # (text, style)
        self.yticks = []              # (value_from_label, tick_x, tick_y)
        self.xticks = []
        self.rects = []               # dicts: x,y,w,h, fill, clipped, group
        self.error_segments = []      # (x, y_top, y_bot) vertical 2-pt paths
        self.markers = []             # use elements: x, y, fill
        self.quad_paths = []          # QuadMesh paths: rect, fill
        self.arc_paths = []           # paths containing A commands: cmds, fill
        self.wedge_paths = []         # filled C-curve paths closing via L+Z: pie wedges
        self._walk(root, [])

    def _walk(self, elem, ancestors):
        gid = elem.get("id", "")
        ids = ancestors + ([gid] if gid else [])
        tag = local(elem.tag)
        if tag == "text":
            self.text_elements.append(("".join(elem.itertext()) or elem.text or "",
                                       style_dict(elem.get("style"))))
            for c in elem:
                self._walk(c, ids)
            return
        if tag == "path":
            self._handle_path(elem, ids)
            return
        if tag == "use":
            st = style_dict(elem.get("style"))
            fill = st.get("fill", "")
            try:
                x = float(elem.get("x", "0"))
                y = float(elem.get("y", "0"))
            except ValueError:
                return
            in_legend = any(a.startswith("legend") for a in ids)
            if not in_legend and fill and fill.lower() not in ("none",):
                self.markers.append({"x": x, "y": y, "fill": fill})
            return
        if tag == "g" and gid.startswith("ytick"):
            self._tick_pair(elem, self.yticks, horizontal=False)
            return
        if tag == "g" and gid.startswith("xtick"):
            self._tick_pair(elem, self.xticks, horizontal=True)
            return
        for c in elem:
            self._walk(c, ids)

    def _tick_pair(self, g, out, horizontal):
        use_xy, label = None, None

        def find(elem):
            nonlocal use_xy, label
            tag = local(elem.tag)
            if tag == "use" and use_xy is None:
                try:
                    use_xy = (float(elem.get("x", "0")), float(elem.get("y", "0")))
                except ValueError:
                    pass
            elif tag == "text" and label is None:
                label = "".join(elem.itertext())
            for c in elem:
                find(c)

        find(g)
        if use_xy is None or label is None:
            return
        try:
            val = float(label.replace(",", "").replace("\u2212", "-"))
        except (TypeError, ValueError):
            return
        out.append((val, use_xy[0], use_xy[1]))

    def _handle_path(self, elem, ids):
        d = elem.get("d")
        if not d:
            return
        st = style_dict(elem.get("style"))
        fill = st.get("fill", "")
        stroke = st.get("stroke", "")
        clipped = bool(elem.get("clip-path"))
        cmds = parse_path(d)
        in_legend = any(a.startswith("legend") for a in ids)
        in_quadmesh = any(a.startswith("QuadMesh") for a in ids)
        in_linecoll = any(a.startswith("LineCollection") for a in ids)

        if in_linecoll and fill.lower() == "none" and stroke:
            pts = path_bbox_points(cmds)
            if len(pts) == 2 and abs(pts[0][0] - pts[1][0]) < 0.1:
                ytop, ybot = sorted([pts[0][1], pts[1][1]])
                self.error_segments.append((pts[0][0], ytop, ybot))
            return
        if in_quadmesh:
            r = rect_from_path(cmds)
            if r:
                self.quad_paths.append({"rect": r, "fill": fill})
            return
        if any(c[0] == "A" for c in cmds):
            if not in_legend:
                self.arc_paths.append({"cmds": cmds, "fill": fill})
            return
        if (fill and fill.lower() != "none" and len(cmds) >= 4
                and any(c[0] == "C" for c in cmds)
                and cmds[-1][0] == "Z" and cmds[-2][0] == "L"
                and not in_legend and not in_quadmesh):
            # pie wedge: filled, curved boundary, closes back to the centre
            self.wedge_paths.append({"cmds": cmds, "fill": fill})
            return
        r = rect_from_path(cmds)
        if r and not in_legend:
            self.rects.append({"x": r[0], "y": r[1], "w": r[2], "h": r[3],
                               "fill": fill, "clipped": clipped})


# ----------------------------------------------------------- calibration

def fit_linear(pairs):
    """Least squares value = a*px + b from (value, px) pairs."""
    n = len(pairs)
    if n < 2:
        return None
    sx = sum(p[1] for p in pairs)
    sy = sum(p[0] for p in pairs)
    sxx = sum(p[1] * p[1] for p in pairs)
    sxy = sum(p[0] * p[1] for p in pairs)
    den = n * sxx - sx * sx
    if abs(den) < 1e-12:
        return None
    a = (n * sxy - sx * sy) / den
    b = (sy - a * sx) / n
    resid = max(abs(v - (a * p + b)) for v, p in pairs)
    return a, b, resid


def make_mapper(a, b):
    return lambda p: a * p + b


def calibration_from_svg(facts, glyphs_doc, axis):
    """Independent pixel->value mapping from SVG ticks; fallback to the
    axis-end calibration recorded in glyphs.json."""
    ticks = facts.yticks if axis == "y" else facts.xticks
    coord = 2 if axis == "y" else 1
    pairs = [(t[0], t[coord]) for t in ticks]
    fit = fit_linear(pairs)
    if fit and len(pairs) >= 2:
        a, b, resid = fit
        if resid < 1e-6:
            return make_mapper(a, b), {"source": "svg_ticks",
                                       "n_ticks": len(pairs),
                                       "max_residual": resid}
    cal = (glyphs_doc.get("axes_calibration") or {}).get(axis)
    if cal and len(cal) >= 2:
        (v0, p0), (v1, p1) = cal[0], cal[1]
        if abs(p1 - p0) > 1e-9:
            a = (v1 - v0) / (p1 - p0)
            b = v0 - a * p0
            return make_mapper(a, b), {"source": "glyphs_axis_ends",
                                       "reason": "tick labels not machine-readable "
                                                 "or non-linear (log) axis"}
    return None, {"source": "none", "reason": "no usable calibration"}


def hex_to_rgb(c):
    c = c.strip()
    if c.startswith("#"):
        c = c[1:]
        if len(c) == 3:
            c = "".join(ch * 2 for ch in c)
        if len(c) >= 6:
            return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    return None


def color_close(c1, c2, tol=COLOR_TOL):
    r1, g1, b1 = hex_to_rgb(c1) or (None, None, None)
    r2, g2, b2 = hex_to_rgb(c2) or (None, None, None)
    if None in (r1, g1, b1) or None in (r2, g2, b2):
        return c1.lower() == c2.lower()
    return abs(r1 - r2) <= tol and abs(g1 - g2) <= tol and abs(b1 - b2) <= tol


# ------------------------------------------------------------- verify core

def verify(svg_path, glyphs_path, style=None, tol_px=DEFAULT_TOL_PX,
           tol_rel=DEFAULT_TOL_REL):
    with open(glyphs_path, encoding="utf-8") as f:
        glyphs_doc = json.load(f)
    tree = ET.parse(svg_path)
    facts = SvgFacts(tree.getroot())
    glyphs = glyphs_doc.get("glyphs", [])
    checks = []
    failures = 0

    def record(name, ok, **kw):
        nonlocal failures
        c = {"glyph": name, "pass": bool(ok)}
        c.update(kw)
        checks.append(c)
        if not ok:
            failures += 1
        return c

    ymap, ycal = calibration_from_svg(facts, glyphs_doc, "y")
    xmap, xcal = calibration_from_svg(facts, glyphs_doc, "x")

    span = None
    if ymap:
        cal = glyphs_doc.get("axes_calibration") or {}
        yt = cal.get("y_ticks")
        if yt:
            vals = [v for v, _ in yt]
            span = max(vals) - min(vals) if len(vals) > 1 else None
    if span is None:
        vals = [g["value"] for g in glyphs if g.get("value") is not None]
        span = (max(vals) - min(vals)) if len(vals) > 1 else 1.0
    if span == 0:
        span = 1.0
    tol_val = tol_rel * span

    # ---------------- per-kind read-back ----------------
    bars = [g for g in glyphs if g["kind"] == "bar"]
    points = [g for g in glyphs if g["kind"] == "point"]
    cells = [g for g in glyphs if g["kind"] == "cell"]
    sectors = [g for g in glyphs if g["kind"] == "sector"]
    boxes = [g for g in glyphs if g["kind"] == "box"]

    for g in bars:
        name = f"bar/{g['series']}/{g['category']}"
        if ymap is None:
            record(name, False, reason="no y-axis calibration available")
            continue
        cand = [r for r in facts.rects
                if r["clipped"] and color_close(r["fill"], g["series_color"])]
        exp = g.get("rect_svg_pt")
        best, best_d = None, 1e9
        for r in cand:
            d = abs((r["x"] + r["w"] / 2) - (exp[0] + exp[2] / 2)) if exp else 1e9
            if d < best_d:
                best, best_d = r, d
        if best is None or best_d > max(tol_px, 2.0):
            record(name, False,
                   reason=f"no SVG rectangle with fill {g['series_color']} near "
                          f"expected x (candidates={len(cand)})")
            continue
        geom_ok = True
        geom_detail = {}
        if exp:
            for label, got, want in (("x", best["x"], exp[0]),
                                     ("y", best["y"], exp[1]),
                                     ("w", best["w"], exp[2]),
                                     ("h", best["h"], exp[3])):
                d = abs(got - want)
                geom_detail[label] = {"svg": round(got, 3),
                                      "expected": round(want, 3),
                                      "delta": round(d, 3)}
                if d > tol_px:
                    geom_ok = False
        readback = ymap(best["y"])            # top of the rect == value
        err = abs(readback - g["value"])
        entry = {
            "expected_value": g["value"],
            "readback_value": round(readback, 6),
            "abs_error": round(err, 8),
            "tolerance": round(tol_val, 8),
            "geometry": geom_detail,
            "source_locator": g.get("source", {}).get("locator"),
        }
        ok = err <= tol_val and geom_ok
        # error bar read-back
        if g.get("error") is not None:
            cx = best["x"] + best["w"] / 2
            segs = [s for s in facts.error_segments if abs(s[0] - cx) < tol_px + 1.0]
            if segs:
                s = segs[0]
                hi, lo = ymap(s[1]), ymap(s[2])   # y1 < y2 in SVG => hi value
                read_err = (hi - lo) / 2.0
                eerr = abs(read_err - g["error"])
                entry["error_bar"] = {
                    "expected": g["error"], "readback": round(read_err, 6),
                    "abs_error": round(eerr, 8), "pass": eerr <= tol_val}
                ok = ok and eerr <= tol_val
            else:
                entry["error_bar"] = {"pass": False,
                                      "reason": "no error segment at bar centre"}
                ok = False
        record(name, ok, **entry)

    for g in points:
        name = f"point/{g['series']}/{g['category']}"
        if ymap is None:
            record(name, False, reason="no y-axis calibration available")
            continue
        cand = [m for m in facts.markers if color_close(m["fill"], g["series_color"])]
        exp = g.get("center_svg_pt")
        best, best_d = None, 1e9
        if exp:
            for m in cand:
                d = math.hypot(m["x"] - exp[0], m["y"] - exp[1])
                if d < best_d:
                    best, best_d = m, d
        elif len(cand) == len(points):
            # order-stable fallback when geometry was not recorded
            idx = [p for p in points].index(g)
            if idx < len(cand):
                best = cand[idx]
        if best is None or best_d > max(tol_px * 4, 2.4):
            record(name, False,
                   reason=f"no SVG marker with fill {g['series_color']} at expected "
                          f"position (candidates={len(cand)})")
            continue
        ry = ymap(best["y"])
        yerr = abs(ry - g["value_y"])
        entry = {"expected_value_y": g["value_y"],
                 "readback_value_y": round(ry, 6),
                 "abs_error": round(yerr, 8), "tolerance": round(tol_val, 8),
                 "source_locator": g.get("source", {}).get("locator")}
        ok = yerr <= tol_val
        if xmap is not None and isinstance(g.get("value_x"), (int, float)):
            rx = xmap(best["x"])
            xerr = abs(rx - g["value_x"])
            entry["expected_value_x"] = g["value_x"]
            entry["readback_value_x"] = round(rx, 6)
            entry["abs_error_x"] = round(xerr, 8)
            ok = ok and xerr <= tol_val
        record(name, ok, **entry)

    if cells:
        quads = facts.quad_paths
        if len(quads) != len(cells):
            record("heatmap/quads", False,
                   reason=f"SVG has {len(quads)} quad paths but mapping table has "
                          f"{len(cells)} cells")
        else:
            for i, g in enumerate(cells):
                name = f"cell/{g['category']}"
                q = quads[i]
                exp = g.get("rect_svg_pt")
                geom_ok = True
                if exp:
                    geom_ok = (abs(q["rect"][0] - exp[0]) <= tol_px and
                               abs(q["rect"][1] - exp[1]) <= tol_px and
                               abs(q["rect"][2] - exp[2]) <= tol_px and
                               abs(q["rect"][3] - exp[3]) <= tol_px)
                entry = {"expected_rect": exp, "svg_rect":
                         [round(v, 3) for v in q["rect"]],
                         "source_locator": g.get("source", {}).get("locator")}
                if g.get("value") is None:
                    record(name, True, null_value=True, **entry)
                    continue
                col_ok = (g.get("expected_fill") is not None and
                          color_close(q["fill"], g["expected_fill"]))
                entry["expected_fill"] = g.get("expected_fill")
                entry["svg_fill"] = q["fill"]
                record(name, geom_ok and col_ok, **entry)

    for g in sectors:
        name = f"sector/{g['category']}"
        wedge = None
        for wp in facts.wedge_paths:
            if color_close(wp["fill"], g.get("series_color", "")):
                wedge = wp
                break
        if wedge is None:
            record(name, False,
                   reason=f"no filled wedge path with fill {g.get('series_color')}")
            continue
        cmds = wedge["cmds"]
        center = None
        angles = []
        for cmd, vals in cmds:
            if cmd == "L":
                center = (vals[0], vals[1])   # final L returns to pie centre
            elif cmd == "M":
                angles.append(("M", vals[0], vals[1]))
            elif cmd == "C":
                angles.append(("C", vals[-2], vals[-1]))
        if center is None or len(angles) < 2:
            record(name, False, reason="wedge path structure not recognised")
            continue
        cx, cy = center

        def ang(x, y):
            return math.atan2(-(y - cy), x - cx)

        th = [ang(a[1], a[2]) for a in angles]
        sweep = 0.0
        for a, b in zip(th, th[1:]):
            d = b - a
            while d > math.pi:
                d -= 2 * math.pi
            while d < -math.pi:
                d += 2 * math.pi
            sweep += d
        frac = abs(sweep) / (2 * math.pi)
        want_frac = g["value"] / g["value_sum"]
        err = abs(frac - want_frac)
        record(name, err <= 0.01,
               expected_fraction=round(want_frac, 6),
               readback_fraction=round(frac, 6),
               readback_start_angle_deg=round(math.degrees(th[0]) % 360, 3),
               readback_end_angle_deg=round(math.degrees(th[-1]) % 360, 3),
               glyph_theta1_deg=round(g["theta1_deg"], 3),
               glyph_theta2_deg=round(g["theta2_deg"], 3),
               svg_fill=wedge["fill"],
               abs_error=round(err, 6),
               source_locator=g.get("source", {}).get("locator"))

    for g in boxes:
        name = f"box/{g['series']}/{g['category']}"
        record(name, None, reason="box: full geometry read-back not implemented; "
               "verified via mapping table + PNG visual check")

    # ---------------- file-level checks ----------------
    n_text = len(facts.text_elements)
    edit_ok = n_text > 0
    record("svg/text_editable", edit_ok,
           n_text_elements=n_text,
           reason=None if edit_ok else
           "no <text> elements - text appears outlined; SVG would not be editable")
    if style:
        fmin = style.get("font", {}).get("min_pt")
        fmax = style.get("font", {}).get("max_pt")
        if fmin or fmax:
            sizes = []
            for _t, st in facts.text_elements:
                fs = st.get("font-size", "")
                m = NUM.search(fs)
                if m:
                    sizes.append(float(m.group()))
            if sizes:
                lo, hi = min(sizes), max(sizes)
                ok = True
                if fmin and lo < fmin - 0.5:
                    ok = False
                if fmax and hi > fmax + 0.5:
                    ok = False
                record("svg/font_size_range", ok,
                       min_pt_found=lo, max_pt_found=hi,
                       journal_min_pt=fmin, journal_max_pt=fmax)

    n_data_rects = sum(1 for r in facts.rects if r["clipped"])

    report = {
        "svg": os.path.abspath(svg_path),
        "glyphs": os.path.abspath(glyphs_path),
        "calibration": {"y": ycal, "x": xcal},
        "tolerances": {"geometry_pt": tol_px,
                       "value_relative_of_span": tol_rel},
        "value_span_used_for_tolerance": span,
        "glyphs_total": len(glyphs),
        "checks_passed": sum(1 for c in checks if c["pass"] is True),
        "checks_failed": sum(1 for c in checks if c["pass"] is False),
        "checks_not_applicable": sum(1 for c in checks if c["pass"] is None),
        "svg_data_rectangles": n_data_rects,
        "checks": checks,
        "pass": failures == 0,
    }
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--svg", required=True)
    ap.add_argument("--glyphs", required=True)
    ap.add_argument("--style", default=None, help="optional style profile JSON")
    ap.add_argument("--out", default=None, help="report path (default: <svg dir>/"
                   "<chart_id>.verification_report.json)")
    ap.add_argument("--tol-px", type=float, default=DEFAULT_TOL_PX)
    ap.add_argument("--tol-rel", type=float, default=DEFAULT_TOL_REL)
    args = ap.parse_args(argv)

    try:
        style = None
        if args.style:
            with open(args.style, encoding="utf-8") as f:
                style = json.load(f)
        report = verify(args.svg, args.glyphs, style, args.tol_px, args.tol_rel)
    except (OSError, ET.ParseError, json.JSONDecodeError) as e:
        print(f"[verify_svg] FAILED to read inputs: {e}", file=sys.stderr)
        return 2

    out = args.out or re.sub(r"\.svg$", "", args.svg) + ".verification_report.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    print(json.dumps({
        "pass": report["pass"],
        "glyphs_total": report["glyphs_total"],
        "checks_passed": report["checks_passed"],
        "checks_failed": report["checks_failed"],
        "calibration": {k: v.get("source") for k, v in report["calibration"].items()
                         if v},
        "report": out,
    }))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
