"""Raster/vector export via matplotlib (primary) with a Pillow fallback.

`write_png` and `write_pdf` draw the *same* Scene that produced the SVG, so
exports cannot drift from the editable source. Both functions return a dict
describing which backend was used, or raise with an actionable message.
"""
from __future__ import annotations

from .helv import wrap_text
from .scene import Scene, Rect, Ellipse, Line, Arrow, Polyline, Polygon, Circle, Text


def _dash(seq: str):
    """SVG '5,3' -> matplotlib (offset, (on, off)) dash pattern."""
    if not seq:
        return None
    try:
        vals = tuple(float(v) for v in seq.split(","))
        if len(vals) == 2:
            return (0, vals)
        return (0, vals) if len(vals) > 2 else None
    except ValueError:
        return None


def _draw_mpl(scene: Scene, dpi: float):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle, Ellipse as MEllipse, Circle as MCircle, Polygon as MPoly

    fig = plt.figure(figsize=(scene.width / 100.0, scene.height / 100.0), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, scene.width)
    ax.set_ylim(scene.height, 0)  # y-down to match SVG
    ax.set_aspect("equal")
    ax.axis("off")
    fig.patch.set_facecolor(scene.background)
    if scene.background and scene.background != "none":
        ax.add_patch(Rectangle((0, 0), scene.width, scene.height,
                               facecolor=scene.background, edgecolor="none"))

    for lay in scene.layers:
        for it in lay.items:
            gid = it.pid
            if isinstance(it, Rect):
                ax.add_patch(Rectangle((it.x, it.y), it.w, it.h,
                                       facecolor=it.fill, edgecolor=it.stroke,
                                       linewidth=it.stroke_w,
                                       linestyle=_dash(it.dash) or "solid",
                                       capstyle="round", gid=gid))
                if it.rx:
                    ax.add_patch(Rectangle((it.x, it.y), it.w, it.h,
                                           facecolor="none", edgecolor="none", gid=gid + "-hit"))
            elif isinstance(it, Ellipse):
                ax.add_patch(MEllipse((it.cx, it.cy), it.rx * 2, it.ry * 2,
                                      facecolor=it.fill, edgecolor=it.stroke,
                                      linewidth=it.stroke_w, gid=gid))
            elif isinstance(it, Circle):
                ax.add_patch(MCircle((it.cx, it.cy), it.r, facecolor=it.fill,
                                     edgecolor=it.stroke, linewidth=it.stroke_w, gid=gid))
            elif isinstance(it, (Line, Arrow)):
                ls = _dash(it.dash) or "solid"
                ax.plot([it.x1, it.x2], [it.y1, it.y2], color=it.stroke,
                        linewidth=it.stroke_w, linestyle=ls, solid_capstyle="round",
                        gid=gid)
                if isinstance(it, Arrow):
                    import math
                    ang = math.atan2(it.y2 - it.y1, it.x2 - it.x1)
                    h = it.head
                    base = (it.x2 - h * 1.6 * math.cos(ang),
                            it.y2 - h * 1.6 * math.sin(ang))
                    ax.add_patch(MPoly(
                        [(it.x2, it.y2),
                         (base[0] - h * 0.6 * math.sin(-ang), base[1] - h * 0.6 * math.cos(-ang)),
                         (base[0] + h * 0.6 * math.sin(-ang), base[1] + h * 0.6 * math.cos(-ang))],
                        closed=True, facecolor=it.stroke, edgecolor="none"))
            elif isinstance(it, (Polyline, Polygon)):
                xs = [p[0] for p in it.pts]
                ys = [p[1] for p in it.pts]
                if isinstance(it, Polygon):
                    ax.add_patch(MPoly(list(it.pts), closed=True, facecolor=it.fill,
                                       edgecolor=it.stroke if it.stroke != "none" else "none",
                                       linewidth=it.stroke_w, gid=gid))
                else:
                    if it.fill not in ("none", None):
                        ax.fill(xs + [xs[0]], ys + [ys[0]], color=it.fill, gid=gid)
                    else:
                        ax.plot(xs, ys, color=it.stroke, linewidth=it.stroke_w,
                                linestyle=_dash(it.dash) or "solid", gid=gid)
            elif isinstance(it, Text):
                mw = it.meta.get("max_width")
                lines = wrap_text(it.text, it.size, mw, it.bold) if mw else it.text.split("\n")
                ha = it.align
                ax.text(it.x, it.y + it.size * 0.8, "\n".join(lines),
                        fontsize=it.size, fontweight="bold" if it.bold else "normal",
                        color=it.color, ha=ha, va="baseline",
                        multialignment=ha, linespacing=1.28, family="sans-serif", gid=gid)
    return fig


def write_png(scene: Scene, path: str, dpi: float = 300) -> dict:
    """PNG export. Tries matplotlib first; falls back to Pillow (2x SSAA)."""
    try:
        fig = _draw_mpl(scene, dpi)
        fig.savefig(path, dpi=dpi, facecolor=scene.background)
        import matplotlib.pyplot as plt
        plt.close(fig)
        return {"backend": "matplotlib", "dpi": dpi}
    except ImportError as e:
        from .pillow_writer import write_png_pil
        return write_png_pil(scene, path, scale=max(2.0, dpi / 150.0))


def write_pdf(scene: Scene, path: str) -> dict:
    """Vector PDF export (matplotlib). Raises with guidance when unavailable."""
    try:
        fig = _draw_mpl(scene, 100)
        fig.savefig(path, format="pdf", facecolor=scene.background)
        import matplotlib.pyplot as plt
        plt.close(fig)
        return {"backend": "matplotlib", "format": "pdf"}
    except ImportError as e:
        raise RuntimeError(
            "matplotlib is unavailable, so vector PDF export failed. Keep the "
            "SVG as the editable source and export PDF/PNG through the "
            "browser-automation tool (print the SVG) or pdf-render-tool; "
            "record the substitution in result.json. Original error: " + str(e)
        ) from e
