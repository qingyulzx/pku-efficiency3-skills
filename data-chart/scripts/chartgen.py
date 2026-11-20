#!/usr/bin/env python3
"""Render a publication chart from a chart spec, keeping data-to-glyph traceability.

Pipeline position: step 2 of the skill workflow (render). Takes the chart spec
written by the agent (see references/chart-spec.md) plus a journal style
profile (references/styles/*.json) and produces:

  <outdir>/<chart_id>.svg          editable vector source (text kept as <text>, never outlined)
  <outdir>/<chart_id>.pdf          vector export
  <outdir>/<chart_id>.png          raster preview/check (default 300 dpi)
  <outdir>/<chart_id>.glyphs.json  explicit value->glyph mapping table (the audit trail)
  <outdir>/<chart_id>.render_report.json  per-format export status

Every glyph entry records: source value, series, category, the SVG pixel
geometry the value was mapped to, and the source locator. verify_svg.py reads
the geometry back out of the SVG and checks it against these values.

Usage:
  python chartgen.py --spec spec.json --style nature.json --outdir out/

Exit codes: 0 success (possibly with warnings in render_report), 2 spec/style
error that must be fixed before rendering, 3 render error after which partial
outputs may exist.
"""

import argparse
import json
import math
import os
import sys
import traceback

SUPPORTED_CHARTS = {"bar", "grouped_bar", "line", "scatter", "heatmap", "pie", "box"}

MM_PER_IN = 25.4
PT_PER_IN = 72.0


class SpecError(Exception):
    """Raised for spec/style problems the caller (agent) must fix."""


# ---------------------------------------------------------------- validation

def _check_number(v, ctx):
    if v is None:
        return
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SpecError(f"{ctx}: value {v!r} is not a number or null")
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        raise SpecError(f"{ctx}: value {v!r} is NaN/Inf")


def validate_spec(spec):
    """Validate chart spec. Raises SpecError with an actionable message."""
    for key in ("chart_id", "chart_type", "series"):
        if key not in spec:
            raise SpecError(f"spec is missing required key '{key}'")
    cid = spec["chart_id"]
    if not isinstance(cid, str) or not cid or any(c in cid for c in "/\\:*?\"<>|"):
        raise SpecError(f"chart_id {cid!r} must be a safe file name fragment")
    ctype = spec["chart_type"]
    if ctype not in SUPPORTED_CHARTS:
        raise SpecError(
            f"chart_type {ctype!r} not supported; choose one of {sorted(SUPPORTED_CHARTS)}"
        )

    series = spec["series"]
    if not isinstance(series, list) or not series:
        raise SpecError("'series' must be a non-empty list")
    ncat = None
    if ctype in ("bar", "grouped_bar", "line", "scatter", "box"):
        cats = spec.get("categories")
        if not isinstance(cats, list) or not cats:
            raise SpecError(f"{ctype} requires a non-empty 'categories' list")
        ncat = len(cats)
        if len(set(map(str, cats))) != ncat:
            raise SpecError("duplicate category labels in 'categories'")

    for si, s in enumerate(series):
        sname = s.get("name", f"series[{si}]")
        if "values" not in s:
            raise SpecError(f"series '{sname}' has no 'values'")
        vals = s["values"]
        if not isinstance(vals, list):
            raise SpecError(f"series '{sname}': 'values' must be a list")
        if ctype == "heatmap":
            # matrix values are validated by shape below; skip scalar checks
            continue
        if ncat is not None and len(vals) != ncat:
            raise SpecError(
                f"series '{sname}' has {len(vals)} values but there are {ncat} "
                f"categories; align the series with the category list or drop it"
            )
        for i, v in enumerate(vals):
            _check_number(v, f"series '{sname}' value[{i}]")
        errs = s.get("errors")
        if errs is not None:
            if not isinstance(errs, list) or len(errs) != len(vals):
                raise SpecError(
                    f"series '{sname}': 'errors' must be a list of the same length "
                    f"as 'values' ({len(vals)})"
                )
            for i, e in enumerate(errs):
                _check_number(e, f"series '{sname}' error[{i}]")
                if e is not None and e < 0:
                    raise SpecError(f"series '{sname}' error[{i}] is negative")
        if "source" not in s or not isinstance(s["source"], dict) or not s["source"].get("locator"):
            raise SpecError(
                f"series '{sname}' needs a 'source' object with a 'locator' "
                f"(where the numbers come from: file/table/row/column)"
            )

    # axis sanity
    for axname in ("x", "y"):
        ax = spec.get(axname) or {}
        if ax.get("log"):
            vals = []
            for s in series:
                vals.extend(v for v in s["values"] if v is not None)
            if ctype == "pie" and axname == "y":
                continue
            bad = [v for v in vals if v <= 0]
            if bad and axname == "y" or (axname == "x" and ctype == "scatter"):
                if bad:
                    raise SpecError(
                        f"log scale requested on {axname} axis but values "
                        f"{bad[:3]} are non-positive; use a linear axis or "
                        f"exclude/transform those points explicitly"
                    )
    if ctype == "pie":
        for s in series:
            bad = [v for v in s["values"] if v is not None and v < 0]
            if bad:
                raise SpecError(f"pie series '{s.get('name')}': negative values {bad[:3]}")
        total = sum(v for s in series for v in s["values"] if v is not None)
        if total <= 0:
            raise SpecError("pie: sum of values must be positive")
    if ctype == "heatmap":
        rows = spec.get("categories") or []
        cols = spec.get("columns") or []
        if not rows or not cols:
            raise SpecError("heatmap requires 'categories' (rows) and 'columns' (cols)")
        for s in series:
            grid = s["values"]
            if not isinstance(grid, list) or len(grid) != len(rows) or any(
                isinstance(r, list) and len(r) != len(cols) for r in grid
            ):
                raise SpecError(
                    f"heatmap series '{s.get('name')}': 'values' must be a "
                    f"{len(rows)}x{len(cols)} matrix matching rows x columns"
                )
    if ctype == "box":
        for s in series:
            for i, v in enumerate(s["values"]):
                if v is not None and not isinstance(v, list):
                    raise SpecError(
                        f"box series '{s.get('name')}': value[{i}] must be a list of "
                        f"raw observations (replicates), not a scalar"
                    )
    return True


# ------------------------------------------------------------------- helpers

def _axis_label(ax_spec):
    ax_spec = ax_spec or {}
    label = ax_spec.get("label", "")
    unit = ax_spec.get("unit")
    if unit and label:
        return f"{label} ({unit})"
    if unit:
        return f"({unit})"
    return label


def _fmt_tick(v):
    if isinstance(v, float) and v == int(v) and abs(v) < 1e15:
        return str(int(v))
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _series_color(s, palette, idx):
    c = s.get("color")
    if c:
        return c
    return palette[idx % len(palette)]


# -------------------------------------------------------------------- render

def render(spec, style, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    fig_fnt = style.get("font", {})
    lines = style.get("lines", {})
    palette = style.get("colors", {}).get(
        "palette", ["#0072b2", "#d55e00", "#009e73", "#cc79a7", "#e69f00", "#56b4e9"]
    )
    fam_requested = [fig_fnt.get("family", "DejaVu Sans")] + fig_fnt.get(
        "fallbacks", ["DejaVu Sans"])
    fam, missing_fonts = [], []
    try:
        from matplotlib import font_manager
        available = {f.name for f in font_manager.fontManager.ttflist}
        seen = set()
        for f in fam_requested:
            if f in available and f not in seen:
                fam.append(f)
                seen.add(f)
            elif f not in available:
                missing_fonts.append(f)
    except Exception:  # noqa: BLE001 - font discovery is best effort
        fam = fam_requested[:1]
    if not fam:
        fam = ["DejaVu Sans"]
    fam.append("DejaVu Sans")
    plt.rcParams.update({
        # keep text as real <text> elements -> SVG stays editable (Nature:
        # "Do not outline text"); this is the single most important switch.
        "svg.fonttype": "none",
        "pdf.fonttype": 42,          # embed TrueType, keep text selectable
        "font.family": fam,        "font.size": fig_fnt.get("tick_pt", 8),
        "axes.linewidth": lines.get("axis_linewidth_pt", 0.8),
        "lines.linewidth": lines.get("data_linewidth_pt", 1.0),
        "lines.markersize": fig_fnt.get("marker_pt", 4),
        "axes.unicode_minus": False,
        "savefig.transparent": False,
        "figure.dpi": 100.0,
        "savefig.dpi": 100.0,
    })

    fs = style.get("figure", {})
    w_in = fs.get("width_mm", 120) / MM_PER_IN
    h_in = fs.get("height_mm", 80) / MM_PER_IN
    # fix figure dpi at 72 so display-pixels == SVG user units (1 pt)
    fig = plt.figure(figsize=(w_in, h_in), dpi=PT_PER_IN)
    ax = fig.add_axes((style.get("margins", {}).get("left", 0.16),
                       style.get("margins", {}).get("bottom", 0.15),
                       1 - style.get("margins", {}).get("left", 0.16)
                       - style.get("margins", {}).get("right", 0.04),
                       1 - style.get("margins", {}).get("bottom", 0.15)
                       - style.get("margins", {}).get("top", 0.10)))

    ctype = spec["chart_type"]
    categories = spec.get("categories")
    series = spec["series"]
    null_notes = []          # every null value we skip is recorded here
    glyphs = []              # the value -> glyph mapping table
    artists = {}             # glyph index -> matplotlib artist(s)

    tick_pt = fig_fnt.get("tick_pt", 8)
    label_pt = fig_fnt.get("label_pt", 9)
    title_pt = fig_fnt.get("title_pt", 10)

    if ctype in ("bar", "grouped_bar"):
        if ctype == "bar" and len(series) == 1:
            width = 0.65
            offsets = {0: 0.0}
        else:
            n = len(series)
            width = min(0.8 / n, 0.65)
            offsets = {i: (i - (n - 1) / 2.0) * width for i in range(n)}
        for si, s in enumerate(series):
            color = _series_color(s, palette, si)
            x, h, base_err = [], [], []
            for ci, v in enumerate(s["values"]):
                if v is None:
                    null_notes.append(
                        f"series '{s['name']}' category '{categories[ci]}': no source "
                        f"value (null); bar omitted"
                    )
                    continue
                x.append(ci + offsets[si])
                h.append(v)
                base_err.append((s.get("errors") or [None] * len(s["values"]))[ci])
            eb = None
            if any(e is not None for e in base_err):
                eb = ax.bar(
                    x, h, width=width, color=color, label=s["name"],
                    edgecolor=style.get("bar", {}).get("edge_color", "black"),
                    linewidth=lines.get("bar_edge_linewidth_pt", 0.5),
                    yerr=base_err, error_kw={
                        "elinewidth": lines.get("error_linewidth_pt", 0.7),
                        "capsize": fig_fnt.get("error_cap_pt", 2.0),
                        "ecolor": style.get("bar", {}).get("error_color", "black"),
                    },
                )
                bars = eb
            else:
                bars = ax.bar(
                    x, h, width=width, color=color, label=s["name"],
                    edgecolor=style.get("bar", {}).get("edge_color", "black"),
                    linewidth=lines.get("bar_edge_linewidth_pt", 0.5),
                )
            for xi, hi, bi, erri in zip(x, h, bars, base_err):
                glyphs.append({
                    "kind": "bar", "series": s["name"],
                    "series_color": color,
                    "category": categories[int(round(xi - offsets[si]))],
                    "value": hi, "error": erri,
                    "error_meaning": s.get("error_meaning"),
                    "source": s["source"],
                })
                artists[len(glyphs) - 1] = bi
        ax.set_xticks(range(len(categories)))
        ax.set_xticklabels([str(c) for c in categories], fontsize=tick_pt)
        # rotate long labels so they cannot collide
        longest = max((len(str(c)) for c in categories), default=0)
        if longest > max(6, int(38 / max(len(categories), 1))):
            ax.tick_params(axis="x", labelrotation=30)
            for t in ax.get_xticklabels():
                t.set_ha("right")

    elif ctype == "line":
        for si, s in enumerate(series):
            color = _series_color(s, palette, si)
            xs, ys = [], []
            for ci, v in enumerate(s["values"]):
                if v is None:
                    null_notes.append(
                        f"series '{s['name']}' x={ci}: null value, point omitted"
                    )
                    continue
                xs.append(ci)
                ys.append(v)
                glyphs.append({
                    "kind": "point", "series": s["name"], "series_color": color,
                    "category": categories[ci], "value_x": ci, "value_y": v,
                    "source": s["source"],
                })
            ax.plot(xs, ys, "-o", color=color, label=s["name"],
                    markersize=fig_fnt.get("marker_pt", 4))
        ax.set_xticks(range(len(categories)))
        ax.set_xticklabels([str(c) for c in categories], fontsize=tick_pt)
        longest = max((len(str(c)) for c in categories), default=0)
        if longest > max(6, int(38 / max(len(categories), 1))):
            ax.tick_params(axis="x", labelrotation=30)
            for t in ax.get_xticklabels():
                t.set_ha("right")

    elif ctype == "scatter":
        xs_all = []
        for s in series:
            xs_all.extend(v for v in s["values"] if v is not None)
        numeric_x = all(isinstance(x, (int, float)) for x in xs_all)
        for si, s in enumerate(series):
            color = _series_color(s, palette, si)
            xs = s.get("x_values")
            for ci, v in enumerate(s["values"]):
                if v is None:
                    null_notes.append(
                        f"series '{s['name']}': null y at index {ci}, point omitted"
                    )
                    continue
                xv = xs[ci] if xs is not None else (
                    ci if not numeric_x else s["values"][ci]
                )
                if xv is None:
                    null_notes.append(
                        f"series '{s['name']}': null x at index {ci}, point omitted"
                    )
                    continue
                glyphs.append({
                    "kind": "point", "series": s["name"], "series_color": color,
                    "category": str(categories[ci]) if categories else str(ci),
                    "value_x": xv, "value_y": v,
                    "source": s["source"],
                })
            ys = [v for v in s["values"] if v is not None]
            if xs is not None:
                pts = [(x, y) for x, y in zip(xs, s["values"]) if x is not None and y is not None]
                ax.plot([p[0] for p in pts], [p[1] for p in pts], "o", color=color,
                        label=s["name"], markersize=fig_fnt.get("marker_pt", 5))
            elif not numeric_x:
                ax.plot(range(len(ys)), ys, "o", color=color, label=s["name"],
                        markersize=fig_fnt.get("marker_pt", 5))
        if categories and not numeric_x:
            ax.set_xticks(range(len(categories)))
            ax.set_xticklabels([str(c) for c in categories], fontsize=tick_pt)

    elif ctype == "heatmap":
        import numpy as np
        rows = categories
        cols = spec["columns"]
        s = series[0]
        grid = np.array([[np.nan if v is None else v for v in row] for row in s["values"]])
        cmap_name = style.get("heatmap", {}).get("colormap", "viridis")
        cmap = plt.get_cmap(cmap_name).copy()
        cmap.set_bad("#bbbbbb")
        im = ax.pcolormesh(
            np.arange(len(cols) + 1) - 0.5, np.arange(len(rows) + 1) - 0.5,
            grid, cmap=cmap,
            vmin=spec.get("color_scale", {}).get("vmin"),
            vmax=spec.get("color_scale", {}).get("vmax"),
        )
        cb = fig.colorbar(im, ax=ax)
        cb.set_label(_axis_label(spec.get("color_scale") or {"label": "value"}), fontsize=label_pt)
        cb.ax.tick_params(labelsize=tick_pt)
        for ri, row in enumerate(s["values"]):
            for ci, v in enumerate(row):
                if v is None:
                    null_notes.append(
                        f"heatmap cell row '{rows[ri]}' col '{cols[ci]}': null, drawn grey"
                    )
                glyphs.append({
                    "kind": "cell", "series": s["name"],
                    "category": f"{rows[ri]}|{cols[ci]}", "value": v,
                    "row": ri, "col": ci,
                    "expected_fill": _rgba_hex(im.cmap(im.norm(v)))
                    if v is not None and not math.isnan(v) else None,
                    "source": s["source"],
                })
        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels([str(c) for c in cols], fontsize=tick_pt)
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels([str(r) for r in rows], fontsize=tick_pt)
        ax.invert_yaxis()

    elif ctype == "pie":
        s = series[0]
        vals, labs = [], []
        for ci, v in enumerate(s["values"]):
            if v is None:
                null_notes.append(f"pie: null value at index {ci}, slice omitted")
                continue
            vals.append(v)
            labs.append(str(categories[ci]))
        pie_result = ax.pie(
            vals, labels=None, colors=[
                _series_color({"color": None}, palette, i) for i in range(len(vals))
            ],
            startangle=90, counterclock=False,
            wedgeprops={"edgecolor": "white",
                        "linewidth": lines.get("pie_edge_pt", 0.5)},
        )
        wedges = pie_result[0]
        for wi, (w, v, lab) in enumerate(zip(wedges, vals, labs)):
            glyphs.append({
                "kind": "sector", "series": s["name"], "category": lab,
                "series_color": palette[wi % len(palette)],
                "value": v, "value_sum": sum(vals),
                "theta1_deg": math.degrees(w.theta1), "theta2_deg": math.degrees(w.theta2),
                "source": s["source"],
            })
            artists[len(glyphs) - 1] = w
        ax.set_aspect("equal")

    elif ctype == "box":
        data, positions, labels = [], [], []
        for si, s in enumerate(series):
            for ci, v in enumerate(s["values"]):
                if v is None or not v:
                    null_notes.append(
                        f"box series '{s['name']}' category '{categories[ci]}': "
                        f"no observations, box omitted"
                    )
                    continue
                data.append(v)
                positions.append(ci + si * 0.0)
                labels.append(categories[ci])
                glyphs.append({
                    "kind": "box", "series": s["name"],
                    "series_color": _series_color(s, palette, si),
                    "category": categories[ci], "value": v,
                    "source": s["source"],
                })
        bp = ax.boxplot(data, positions=positions, widths=0.5, patch_artist=True)
        for bi, b in enumerate(bp["boxes"]):
            b.set_facecolor(glyphs[bi]["series_color"])
            b.set_alpha(0.6)
        ax.set_xticks(range(len(categories)))
        ax.set_xticklabels([str(c) for c in categories], fontsize=tick_pt)

    # ---- axes / legend / title -------------------------------------------
    if ctype != "pie":
        ax.set_xlabel(_axis_label(spec.get("x")), fontsize=label_pt)
        ax.set_ylabel(_axis_label(spec.get("y")), fontsize=label_pt)
        if spec.get("y", {}).get("log"):
            ax.set_yscale("log")
        if spec.get("x", {}).get("log"):
            ax.set_xscale("log")
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(style.get("spines", {}).get("show_top_right", False))
        if len(series) > 1:
            ax.legend(fontsize=tick_pt, frameon=False,
                      loc=style.get("legend", {}).get("loc", "best"))
    if spec.get("title"):
        ax.set_title(spec["title"], fontsize=title_pt, pad=6)
    if spec.get("notes"):
        fig.text(0.01, 0.01, str(spec["notes"]), fontsize=min(tick_pt, 6), ha="left")

    # ---- geometry capture (display px == SVG user units, dpi==72) --------
    fig.canvas.draw()
    H = fig.get_figheight() * PT_PER_IN  # SVG height in user units

    def to_svg_pt(xy):
        x, y = ax.transData.transform(xy)
        return (float(x), float(H - y))

    for gi, g in enumerate(glyphs):
        a = artists.get(gi)
        if g["kind"] == "bar":
            x0, y0 = to_svg_pt((a.get_x(), a.get_y()))  # data-space corner
            x1, y1 = to_svg_pt((a.get_x() + a.get_width(), a.get_y() + a.get_height()))
            g["rect_svg_pt"] = [min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)]
            g["bar_top_svg_pt"] = min(y0, y1)
            g["baseline_svg_pt"] = max(y0, y1)
            if g["error"]:
                yv, ye = g["value"], g["error"]
                top, bot = to_svg_pt((0, yv + ye))[1], to_svg_pt((0, yv - ye))[1]
                g["error_top_svg_pt"] = min(top, bot)
                g["error_bottom_svg_pt"] = max(top, bot)
        elif g["kind"] == "point":
            if isinstance(g.get("value_x"), (int, float)):
                g["center_svg_pt"] = list(to_svg_pt((g["value_x"], g["value_y"])))
        elif g["kind"] == "cell":
            x0, y0 = to_svg_pt((g["col"] - 0.5, g["row"] - 0.5))
            x1, y1 = to_svg_pt((g["col"] + 0.5, g["row"] + 0.5))
            g["rect_svg_pt"] = [min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)]
        elif g["kind"] == "sector":
            g["center_svg_pt"] = [float(ax.transData.transform((0, 0))[0]),
                                  H - float(ax.transData.transform((0, 0))[1])]

    # axis calibration: two reference (value -> SVG pt) pairs per axis
    cal = {}
    if ctype != "pie":
        yl = ax.get_ylim()
        xl = ax.get_xlim()
        cal["y"] = [[float(yl[0]), to_svg_pt((0, yl[0]))[1]],
                    [float(yl[1]), to_svg_pt((0, yl[1]))[1]]]
        cal["x"] = [[float(xl[0]), to_svg_pt((xl[0], 0))[0]],
                    [float(xl[1]), to_svg_pt((xl[1], 0))[0]]]
        cal["y_ticks"] = [[float(t), to_svg_pt((0, t))[1]] for t in ax.get_yticks()]
        cal["x_ticks"] = [[float(t), to_svg_pt((t, 0))[0]] for t in ax.get_xticks()]

    # ---- export -----------------------------------------------------------
    chart_id = spec["chart_id"]
    paths = {}
    report = {"chart_id": chart_id, "chart_type": ctype,
              "figure_mm": [round(w_in * MM_PER_IN, 1), round(h_in * MM_PER_IN, 1)],
              "font_family_used": fam,
              "fonts_requested_but_missing": missing_fonts,
              "style_profile": style.get("profile", "custom"),
              "exports": {}, "null_value_notes": null_notes}

    for fmt in ("svg", "pdf", "png"):
        p = os.path.join(outdir, f"{chart_id}.{fmt}")
        entry = {"path": p}
        try:
            if fmt == "png":
                fig.savefig(p, dpi=style.get("export", {}).get("png_dpi", 300))
            else:
                fig.savefig(p)
            entry.update(status="ok", bytes=os.path.getsize(p))
        except Exception as e:  # noqa: BLE001 - recorded, other formats continue
            entry.update(status="failed", error=f"{type(e).__name__}: {e}")
        report["exports"][fmt] = entry
        if entry["status"] == "ok":
            paths[fmt] = p

    glyphs_doc = {
        "chart_id": chart_id,
        "chart_type": ctype,
        "svg_height_pt": H,
        "axes_calibration": cal,
        "series": [
            {"name": s["name"], "color": _series_color(s, palette, i),
             "error_meaning": s.get("error_meaning"), "source": s["source"]}
            for i, s in enumerate(series)
        ],
        "glyphs": glyphs,
        "null_value_notes": null_notes,
        "spec_sha256": _sha256_file(spec.get("_spec_path", "")),
    }
    gp = os.path.join(outdir, f"{chart_id}.glyphs.json")
    with open(gp, "w", encoding="utf-8") as f:
        json.dump(glyphs_doc, f, indent=1, ensure_ascii=False)
    report["glyphs_path"] = gp
    report["glyph_count"] = len(glyphs)

    rp = os.path.join(outdir, f"{chart_id}.render_report.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    plt.close(fig)
    return report


def _rgba_hex(rgba):
    return "#{:02x}{:02x}{:02x}".format(int(rgba[0] * 255), int(rgba[1] * 255),
                                        int(rgba[2] * 255))


def _sha256_file(p):
    import hashlib
    if p and os.path.isfile(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    return None


# ---------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spec", required=True, help="chart spec JSON path")
    ap.add_argument("--style", required=True, help="style profile JSON path")
    ap.add_argument("--outdir", default=".", help="output directory")
    args = ap.parse_args(argv)

    os.makedirs(args.outdir, exist_ok=True)
    try:
        with open(args.spec, encoding="utf-8") as f:
            spec = json.load(f)
        spec["_spec_path"] = os.path.abspath(args.spec)
        with open(args.style, encoding="utf-8") as f:
            style = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[chartgen] FAILED to load inputs: {e}", file=sys.stderr)
        return 2

    try:
        validate_spec(spec)
    except SpecError as e:
        print(f"[chartgen] SPEC ERROR: {e}", file=sys.stderr)
        return 2

    try:
        report = render(spec, style, args.outdir)
    except Exception:  # noqa: BLE001
        print("[chartgen] RENDER ERROR (traceback follows)", file=sys.stderr)
        traceback.print_exc()
        return 3

    failed = [k for k, v in report["exports"].items() if v["status"] != "ok"]
    print(json.dumps({
        "ok": not failed or "svg" not in failed,
        "exports": {k: v["status"] for k, v in report["exports"].items()},
        "glyph_count": report["glyph_count"],
        "null_values_skipped": len(report["null_value_notes"]),
        "render_report": os.path.basename(report.get("glyphs_path", "")).replace(
            ".glyphs.json", ".render_report.json"),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
