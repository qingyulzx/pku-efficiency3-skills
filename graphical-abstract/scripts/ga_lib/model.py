"""Figure-model loader, validator and layout engine.

A figure_model.json is a structured, human/agent-writable description of the
graphical abstract: panels (question / method / results / conclusion), the
entities, relations, data and text inside them, and - for every element -
the source locator in the original material. This module validates the model,
computes a deterministic layout (same model in -> same figure out) and emits:

  * a Scene (rendered to SVG/PNG/PDF by the writers), and
  * an element map: every drawn element with its id, source and visual
    encoding, ready to embed in result.json.
"""
from __future__ import annotations

import json
import re
from .scene import (Scene, Rect, Ellipse, Line, Arrow, Polyline, Polygon,
                    Circle, Text, OKABE_ITO, SERIES_ORDER, INK, PAPER,
                    PANEL_EDGE, MUTED, series_color, tint, contrast_ratio,
                    rel_luminance)
from .helv import wrap_text, text_width

ROLE_ORDER = ["question", "method", "results", "conclusion"]
ROLE_COLORS = {"question": "blue", "method": "green", "results": "orange",
               "conclusion": "purple"}

S_HEAD, S_NODE, S_EDGE, S_TICK, S_VALUE, S_LEGEND = 21, 16.5, 13.5, 13, 14, 14
S_STAT, S_STATLBL, S_BULLET, S_NOTE, S_TITLE, S_SUB = 46, 15, 16, 13, 26, 15


class ModelError(Exception):
    pass


# ---------------------------------------------------------------- loading

def load_model(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        try:
            model = json.load(f)
        except json.JSONDecodeError as e:
            raise ModelError(f"figure model is not valid JSON: {e}") from e
    issues = validate_model(model)
    if issues:
        raise ModelError("figure model has problems:\n  - " + "\n  - ".join(issues))
    return model


def validate_model(model: dict) -> list[str]:
    issues: list[str] = []
    if not isinstance(model, dict):
        return ["model root must be a JSON object"]
    if model.get("schema") != "graphical-abstract/1":
        issues.append("schema must be 'graphical-abstract/1'")
    panels = model.get("panels")
    if not isinstance(panels, list) or not panels:
        issues.append("panels must be a non-empty list")
        return issues
    seen_ids: set[str] = set()
    for i, p in enumerate(panels):
        pid = p.get("id") or f"panel-{i}"
        if p.get("id") in seen_ids:
            issues.append(f"duplicate panel id '{pid}'")
        seen_ids.add(p.get("id", ""))
        role = p.get("role", "custom")
        layout = p.get("layout")
        if layout not in ("flow", "chart", "stats", "text"):
            issues.append(f"panel '{pid}': layout must be flow|chart|stats|text, got {layout!r}")
        if layout == "flow":
            node_ids = set()
            for n in p.get("nodes", []):
                nid = n.get("id")
                if not nid:
                    issues.append(f"panel '{pid}': a node is missing 'id'")
                elif nid in node_ids:
                    issues.append(f"panel '{pid}': duplicate node id '{nid}'")
                else:
                    node_ids.add(nid)
                if not n.get("label"):
                    issues.append(f"panel '{pid}': node '{nid}' is missing 'label'")
                if not (n.get("source") or {}).get("quote"):
                    issues.append(f"panel '{pid}': node '{nid}' has no source.quote")
            for e in p.get("edges", []):
                for end in ("from", "to"):
                    if e.get(end) not in node_ids:
                        issues.append(f"panel '{pid}': edge '{e.get('id')}' references unknown node '{e.get(end)}'")
            for g in p.get("groups", []):
                for m in g.get("members", []):
                    if m not in node_ids:
                        issues.append(f"panel '{pid}': group '{g.get('id')}' references unknown node '{m}'")
        elif layout == "chart":
            ch = p.get("chart") or {}
            t = ch.get("type")
            if t not in ("bar", "hbar", "grouped_bar", "line"):
                issues.append(f"panel '{pid}': chart.type must be bar|hbar|grouped_bar|line, got {t!r}")
            series = ch.get("series") or []
            if t in ("bar", "hbar") and not series:
                issues.append(f"panel '{pid}': chart needs a non-empty 'series' list")
            if t == "grouped_bar" and (not ch.get("categories") or not ch.get("groups") or not ch.get("values")):
                issues.append(f"panel '{pid}': grouped_bar needs categories, groups and values")
            if t == "line" and not ch.get("x_labels"):
                issues.append(f"panel '{pid}': line chart needs 'x_labels'")
            for s in series:
                v = s.get("value")
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    issues.append(f"panel '{pid}': series '{s.get('id')}' value must be a number, got {v!r}")
        elif layout == "stats":
            if not p.get("stats"):
                issues.append(f"panel '{pid}': stats layout needs a 'stats' list")
        elif layout == "text":
            if not p.get("bullets"):
                issues.append(f"panel '{pid}': text layout needs a 'bullets' list")
    return issues


# ---------------------------------------------------------------- builder

class Builder:
    def __init__(self, model: dict):
        self.m = model
        self.elements: list[dict] = []   # element -> source -> encoding map
        self.issues: list[dict] = []     # layout warnings (overflow etc.)

    def note(self, severity: str, code: str, detail: str):
        self.issues.append({"severity": severity, "code": code, "detail": detail})

    def track(self, pid, panel, kind, text, source, encoding, bbox):
        self.elements.append({"id": pid, "panel": panel, "kind": kind,
                              "text": text, "source": source,
                              "encoding": encoding, "bbox": [round(v, 1) for v in bbox]})

    # -- public entry -----------------------------------------------------
    def build(self) -> tuple[Scene, dict]:
        m = self.m
        W = float((m.get("canvas") or {}).get("width", 1800))
        H = float((m.get("canvas") or {}).get("height", 1000))
        scene = Scene(W, H, PAPER, title=m.get("title", ""),
                      desc=m.get("caption_note", ""))
        lay_root = scene.layer("content", "All figure content")

        panels = m["panels"]
        order = m.get("reading_order")
        if order:
            ordered = sorted(panels, key=lambda p: order.index(p["id"]) if p["id"] in order else 999)
        else:
            def role_rank(p):
                r = p.get("role", "custom")
                return ROLE_ORDER.index(r) if r in ROLE_ORDER else len(ROLE_ORDER)
            ordered = sorted(panels, key=lambda p: (role_rank(p), panels.index(p)))
        self.numbering = {p["id"]: i + 1 for i, p in enumerate(ordered)}

        # vertical zones
        margin = 36.0
        head_h = 74.0 if m.get("title") else 18.0
        legend_items = self._legend_items(m)
        notes = [n for n in (m.get("notes") or []) if n]
        bottom_h = (34.0 if legend_items else 0.0) + len(notes) * 19.0 + (10.0 if notes else 0.0)
        area = (margin, head_h, W - 2 * margin, H - head_h - margin - bottom_h)

        self.panel_rects = self._panel_geometry(ordered, area)
        for p in ordered:
            getattr(self, "_panel_" + p["layout"])(lay_root, p, self.panel_rects[p["id"]])
        if legend_items:
            self._legend(lay_root, legend_items, W, H - margin - len(notes) * 19.0 - 6)
        y = H - margin - len(notes) * 19.0 + 4
        for i, n in enumerate(notes):
            t = Text(pid=f"note-{i+1}", x=margin, y=y + i * 19, text="Note — " + n,
                     size=S_NOTE, color=MUTED, align="left")
            lay_root.items.append(t)
            self.track(t.pid, None, "note", n, None,
                       {"channel": "text", "detail": "footnote, not on-canvas claim"},
                       [margin, y + i * 19, W - 2 * margin, 19])
        for a, b in zip(ordered, ordered[1:]):
            self._panel_link(lay_root, self.panel_rects[a["id"]], self.panel_rects[b["id"]])
        report = {"panel_rects": {k: [round(v, 1) for v in v2] for k, v2 in self.panel_rects.items()},
                  "issues": self.issues, "n_elements": len(self.elements)}
        return scene, report

    # -- geometry helpers ---------------------------------------------------
    def _panel_geometry(self, panels, area):
        ax, ay, aw, ah = area
        weights = {"question": 1.0, "method": 1.18, "results": 1.55,
                   "conclusion": 1.05}
        ws = [weights.get(p.get("role", ""), 1.0) for p in panels]
        gap = 20.0
        total_w = aw - gap * (len(panels) - 1)
        rects, x = {}, ax
        for p, w in zip(panels, ws):
            pw = total_w * w / sum(ws)
            rects[p["id"]] = (x, ay, pw, ah)
            x += pw + gap
        return rects

    def _legend_items(self, m):
        lg = m.get("legend") or {}
        items = []
        if lg.get("items"):
            items = lg["items"]
        elif lg.get("auto", True):
            for p in m["panels"]:
                ch = p.get("chart") or {}
                if ch.get("type") in ("grouped_bar", "line"):
                    for g in ch.get("groups") or []:
                        items.append({"id": "lg-" + g["id"], "label": g["label"],
                                      "color": g.get("color") or self._group_color(ch, g["id"]),
                                      "source": g.get("source")})
        seen, uniq = set(), []
        for it in items:
            if it.get("id") not in seen:
                seen.add(it.get("id"))
                uniq.append(it)
        return uniq

    def _group_color(self, chart, gid):
        groups = chart.get("groups") or []
        i = [g["id"] for g in groups].index(gid)
        return SERIES_ORDER[i % len(SERIES_ORDER)]

    def _panel_frame(self, layer, p, rect):
        x, y, w, h = rect
        role = p.get("role", "custom")
        accent = OKABE_ITO[ROLE_COLORS.get(role, "blue")]
        n = self.numbering.get(p["id"], 0)
        layer.items.append(Rect(pid=f"{p['id']}-frame", x=x, y=y, w=w, h=h,
                                fill="#FFFFFF", stroke=PANEL_EDGE, stroke_w=1.5, rx=10,
                                desc=f"panel {n}: {role}"))
        layer.items.append(Rect(pid=f"{p['id']}-strip", x=x, y=y, w=w, h=5,
                                fill=accent, stroke="none", stroke_w=0, rx=2,
                                desc=f"panel accent (role: {role})"))
        if n:
            layer.items.append(Circle(pid=f"{p['id']}-badge", cx=x + 28, cy=y + 34, r=14,
                                      fill=accent, desc=f"reading-order step {n}"))
            layer.items.append(Text(pid=f"{p['id']}-badgenum", x=x + 28, y=y + 26.5,
                                    text=str(n), size=16, bold=True, color="#FFFFFF",
                                    align="center", desc=f"step {n} of the reading order"))
        heading = p.get("heading") or role.capitalize()
        ht = Text(pid=f"{p['id']}-heading", x=x + 50, y=y + 22, text=heading,
                  size=S_HEAD, bold=True, color=INK, align="left",
                  desc=f"panel heading: {heading}")
        ht.meta["max_width"] = w - 66
        layer.items.append(ht)
        self.track(f"{p['id']}-heading", p["id"], "panel_heading", heading,
                   p.get("source"), {"channel": "text", "detail": "panel heading"},
                   [x + 50, y + 22, w - 66, 34])
        return (x + 18, y + 62, w - 36, h - 80)

    def _panel_link(self, layer, ra, rb):
        if not (self.m.get("link_panels", True)):
            return
        ya = ra[1] + 34
        layer.items.append(Arrow(pid=f"link-{int(ra[0])}-{int(rb[0])}",
                                 x1=ra[0] + ra[2] + 2, y1=ya, x2=rb[0] - 6, y2=ya,
                                 stroke="#B9B9B9", stroke_w=2, head=8,
                                 desc="reading-order link between panels"))

    # -- flow panels ---------------------------------------------------------
    def _panel_flow(self, layer, p, rect):
        x, y, w, h = rect
        cx, cy, cw, ch = self._panel_frame(layer, p, rect)
        direction = p.get("direction", "TB")
        nodes = p.get("nodes", [])
        by_layer: dict[int, list] = {}
        for i, n in enumerate(nodes):
            by_layer.setdefault(int(n.get("layer", i)), []).append(n)
        keys = sorted(by_layer)
        if direction == "LR":
            self.note("warning", "layout-lr", "LR flow renders as TB fallback; split into layers instead")
        # row layout (TB)
        pad_v, gap_row, gap_col = 11.0, 34.0, 14.0
        total_h = 0.0
        placed: dict[str, tuple[float, float, float, float]] = {}
        heights = []
        for k in keys:
            row = by_layer[k]
            nw = (cw - gap_col * (len(row) - 1)) / len(row)
            nw = min(nw, 330.0)
            hh = 0.0
            for n in row:
                lines = wrap_text(n["label"], S_NODE, nw - 20, bold=False)
                nh = len(lines) * S_NODE * 1.28 + 2 * pad_v
                if n.get("note"):
                    nh += len(wrap_text(n["note"], S_NOTE, nw - 20)) * S_NOTE * 1.28 + 4
                hh = max(hh, nh)
            heights.append(hh)
            total_h += hh
        total_h += gap_row * (len(keys) - 1)
        if total_h > ch + 0.5:
            self.note("error", "panel-content-overflow",
                      f"panel '{p['id']}' flow content {total_h:.0f}px exceeds {ch:.0f}px; "
                      f"shorten labels, merge nodes, or enlarge canvas.height")
        # center the stack vertically when it fits
        yy = cy + max(0.0, (ch - total_h) / 2)
        for ki, k in enumerate(keys):
            row = by_layer[k]
            nw = min((cw - gap_col * (len(row) - 1)) / len(row), 330.0)
            xx = cx + (cw - (nw * len(row) + gap_col * (len(row) - 1))) / 2
            for n in row:
                accent = OKABE_ITO.get(n.get("accent") or SERIES_ORDER[ki % len(SERIES_ORDER)], series_color(ki))
                lines = wrap_text(n["label"], S_NODE, nw - 20)
                nh = heights[ki]
                shape = n.get("shape", "rounded_box")
                nid = n["id"]
                if shape == "ellipse":
                    layer.items.append(Ellipse(pid=nid, cx=xx + nw / 2, cy=yy + nh / 2,
                                               rx=nw / 2, ry=nh / 2, fill=tint(accent, 0.16),
                                               stroke=accent, stroke_w=2.4 if n.get("emph") else 1.6,
                                               desc=self._srd(n, "entity")))
                else:
                    layer.items.append(Rect(pid=nid, x=xx, y=yy, w=nw, h=nh,
                                            fill=tint(accent, 0.16), stroke=accent,
                                            stroke_w=2.4 if n.get("emph") else 1.6,
                                            rx=8 if shape == "rounded_box" else 0,
                                            desc=self._srd(n, "entity")))
                self.track(nid, p["id"], "entity", n["label"], n.get("source"),
                           {"channel": "shape+color", "detail":
                            f"{shape}, accent {accent}, layer {k}"}, [xx, yy, nw, nh])
                ty = yy + (nh - len(lines) * S_NODE * 1.28) / 2 + 2
                t = Text(pid=nid + "-label", x=xx + nw / 2, y=ty, text=n["label"],
                         size=S_NODE, color=INK, align="center")
                t.meta["max_width"] = nw - 20
                layer.items.append(t)
                if n.get("note"):
                    nl = wrap_text(n["note"], S_NOTE, nw - 20)
                    ny = yy + nh - pad_v - len(nl) * S_NOTE * 1.28 + 2
                    tn = Text(pid=nid + "-note", x=xx + nw / 2, y=ny, text=n["note"],
                              size=S_NOTE, color=MUTED, align="center")
                    tn.meta["max_width"] = nw - 20
                    layer.items.append(tn)
                placed[nid] = (xx, yy, nw, nh)
                xx += nw + gap_col
            yy += heights[ki] + gap_row
        # sequence arrows between layer bands
        edges = p.get("edges") or []
        if not edges and p.get("sequence", True) and len(keys) > 1:
            for ki in range(len(keys) - 1):
                row_a, row_b = by_layer[keys[ki]], by_layer[keys[ki + 1]]
                a, b = row_a[len(row_a) // 2], row_b[len(row_b) // 2]
                ra, rb = placed[a["id"]], placed[b["id"]]
                eid = f"seq-{p['id']}-{ki}"
                arr = Arrow(pid=eid, x1=ra[0] + ra[2] / 2, y1=ra[1] + ra[3] + 3,
                            x2=rb[0] + rb[2] / 2, y2=rb[1] - 3, stroke=MUTED,
                            stroke_w=1.8, head=8, desc="sequence: implied order of steps")
                layer.items.append(arr)
                self.track(eid, p["id"], "layout", "then", None,
                           {"channel": "direction", "detail": "implied sequence between layers (structural, not a scientific claim)"},
                           [arr.x1, arr.y1, arr.x2 - arr.x1, arr.y2 - arr.y1])
        for e in edges:
            if e["from"] not in placed or e["to"] not in placed:
                continue
            ra, rb = placed[e["from"]], placed[e["to"]]
            ca = (ra[0] + ra[2] / 2, ra[1] + ra[3] / 2)
            cb = (rb[0] + rb[2] / 2, rb[1] + rb[3] / 2)
            dx, dy = cb[0] - ca[0], cb[1] - ca[1]
            if abs(dy) >= abs(dx):   # vertical
                p1 = (ca[0], ra[1] + ra[3] + 3) if dy > 0 else (ca[0], ra[1] - 3)
                p2 = (cb[0], rb[1] - 3) if dy > 0 else (cb[0], rb[1] + rb[3] + 3)
            else:
                p1 = (ra[0] + ra[2] + 3, ca[1]) if dx > 0 else (ra[0] - 3, ca[1])
                p2 = (rb[0] - 3, cb[1]) if dx > 0 else (rb[0] + rb[2] + 3, cb[1])
            arr = Arrow(pid=e["id"], x1=p1[0], y1=p1[1], x2=p2[0], y2=p2[1],
                        stroke=INK, stroke_w=1.8, head=8,
                        dash="5,3" if e.get("style") == "dashed" else "",
                        desc=self._srd(e, "relation"))
            layer.items.append(arr)
            enc = {"channel": "direction",
                   "detail": e.get("meaning") or e.get("label") or "directed relation"}
            self.track(e["id"], p["id"], "relation", e.get("label") or "", e.get("source"),
                       enc, [p1[0], p1[1], p2[0] - p1[0], p2[1] - p1[1]])
            if e.get("label"):
                mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
                lw = text_width(e["label"], S_EDGE) + 10
                layer.items.append(Rect(pid=e["id"] + "-labelbg", x=mx - lw / 2, y=my - 9,
                                        w=lw, h=16, fill="#FFFFFF", stroke="none",
                                        stroke_w=0, rx=3))
                t = Text(pid=e["id"] + "-label", x=mx, y=my - 5.5, text=e["label"],
                         size=S_EDGE, color=INK, align="center")
                t.meta["max_width"] = 140
                layer.items.append(t)
        # groups
        for g in p.get("groups") or []:
            mem = [placed[mid] for mid in g.get("members", []) if mid in placed]
            if not mem:
                continue
            gx = min(r[0] for r in mem) - 10
            gy = min(r[1] for r in mem) - 10
            gw = max(r[0] + r[2] for r in mem) + 10 - gx
            gh = max(r[1] + r[3] for r in mem) + 10 - gy
            layer.items.append(Rect(pid=g["id"], x=gx, y=gy, w=gw, h=gh,
                                    fill=tint("#666666", 0.05), stroke="#9A9A9A",
                                    stroke_w=1.2, rx=10, dash="5,3",
                                    desc=self._srd(g, "group")))
            self.track(g["id"], p["id"], "group", g.get("label") or "", g.get("source"),
                       {"channel": "containment", "detail": "dashed container: members belong to one level"},
                       [gx, gy, gw, gh])
            if g.get("label"):
                t = Text(pid=g["id"] + "-label", x=gx + 10, y=gy + 5, text=g["label"],
                         size=S_NOTE, bold=True, color=MUTED, align="left")
                t.meta["max_width"] = gw - 20
                layer.items.append(t)

    def _srd(self, item, kind):
        s = item.get("source") or {}
        loc = s.get("locator", "")
        q = s.get("quote", "")
        bits = [kind]
        if s.get("file"):
            bits.append(str(s["file"]) + (f" {loc}" if loc else ""))
        if q:
            bits.append('"' + q[:160] + '"')
        return " | ".join(bits)

    # -- chart panels ---------------------------------------------------------
    def _panel_chart(self, layer, p, rect):
        x, y, w, h = rect
        cx, cy, cw, ch = self._panel_frame(layer, p, rect)
        ch_cfg = p.get("chart") or {}
        t = ch_cfg.get("type", "bar")
        if t == "hbar":
            self._chart_hbar(layer, p, (cx, cy, cw, ch), ch_cfg)
        elif t == "grouped_bar":
            self._chart_grouped(layer, p, (cx, cy, cw, ch), ch_cfg)
        elif t == "line":
            self._chart_line(layer, p, (cx, cy, cw, ch), ch_cfg)
        else:
            self._chart_bar(layer, p, (cx, cy, cw, ch), ch_cfg)

    def _value_source(self, s, ch_cfg, panel_id, label):
        src = s.get("source") or ch_cfg.get("series_source") or ch_cfg.get("source")
        if not src:
            self.note("error", "missing-source",
                      f"panel '{panel_id}': value '{label}' has no source; add source.quote or chart.series_source")
        return src

    def _y_axis(self, layer, p, area, vmax, unit, ch_h, y0):
        """Draws y ticks/gridlines; returns px-per-unit scale."""
        cx, cy, cw, ch = area
        ticks = 5
        for i in range(ticks + 1):
            v = vmax * i / ticks
            gy = y0 - v * ch_h / vmax
            label = self._fmt_num(v)
            t = Text(pid=f"{p['id']}-ytick-{i}", x=cx - 8, y=gy - 6, text=label,
                     size=S_TICK, color=MUTED, align="right")
            layer.items.append(t)
            if i > 0:
                layer.items.append(Line(pid=f"{p['id']}-grid-{i}", x1=cx, y1=gy,
                                        x2=cx + cw, y2=gy, stroke="#ECECEC", stroke_w=1))
            else:
                layer.items.append(Line(pid=f"{p['id']}-baseline", x1=cx, y1=gy,
                                        x2=cx + cw, y2=gy, stroke=INK, stroke_w=1.5,
                                        desc="zero baseline"))
        if unit:
            layer.items.append(Text(pid=f"{p['id']}-unit", x=cx - 8, y=cy - 4,
                                    text=unit, size=S_TICK, bold=True, color=MUTED,
                                    align="left"))
        return ch_h / vmax if vmax else 1.0

    def _fmt_num(self, v):
        return f"{v:g}" if abs(v - round(v)) > 1e-9 else str(int(round(v)))

    def _chart_bar(self, layer, p, area, ch_cfg):
        cx, cy, cw, ch = area
        unit = ch_cfg.get("unit", "")
        series = ch_cfg["series"]
        vmax_cfg = ch_cfg.get("y_max")
        vmax = float(vmax_cfg) if vmax_cfg else self._nice(max(s["value"] for s in series) * 1.15)
        if vmax <= 0:
            vmax = 1.0
        x_label_h = 40.0
        y0 = cy + ch - x_label_h
        ch_h = ch - x_label_h - 6
        scale = self._y_axis(layer, p, area, vmax, unit, ch_h, y0)
        n = len(series)
        slot = cw / n
        bw = min(64.0, slot * 0.55)
        highlight = set(ch_cfg.get("highlight") or [])
        base = OKABE_ITO["blue"]
        hl = OKABE_ITO["vermillion"]
        for i, s in enumerate(series):
            bx = cx + slot * i + (slot - bw) / 2
            bh = s["value"] * scale
            color = hl if s["id"] in highlight else base
            src = self._value_source(s, ch_cfg, p["id"], s.get("label", s["id"]))
            bar = Rect(pid=s["id"], x=bx, y=y0 - bh, w=bw, h=bh, fill=color,
                       stroke="none", stroke_w=0, rx=3,
                       desc=self._srd({"source": src}, "datum"))
            layer.items.append(bar)
            self.track(s["id"], p["id"], "datum", f"{s.get('label')} = {self._fmt_num(s['value'])}{unit}",
                       src, {"channel": "length", "value": s["value"], "unit": unit,
                             "scale_px_per_unit": round(scale, 3), "zero_baseline": True,
                             "color": color}, [bx, y0 - bh, bw, bh])
            if ch_cfg.get("show_values", True):
                vt = self._fmt_num(s["value"]) + (unit if unit else "")
                t = Text(pid=s["id"] + "-value", x=bx + bw / 2, y=y0 - bh - 20,
                         text=vt, size=S_VALUE, bold=True, color=INK, align="center")
                t.meta["max_width"] = slot - 6
                layer.items.append(t)
            lbl = wrap_text(s.get("label", s["id"]), S_TICK, slot - 8, max_lines=2)
            ty = y0 + 8
            t = Text(pid=s["id"] + "-xlabel", x=cx + slot * i + slot / 2, y=ty,
                     text="\n".join(lbl), size=S_TICK, color=INK, align="center")
            t.meta["max_width"] = slot - 8
            layer.items.append(t)
        self.track(f"{p['id']}-baseline", p["id"], "axis", "0" + (f" {unit}" if unit else ""),
                   None, {"channel": "position", "detail": "zero baseline of the length encoding"},
                   [cx, y0, cw, 1.5])

    def _chart_grouped(self, layer, p, area, ch_cfg):
        cx, cy, cw, ch = area
        unit = ch_cfg.get("unit", "")
        cats = ch_cfg["categories"]
        groups = ch_cfg["groups"]
        values = ch_cfg["values"]  # [cat][group] -> number | {value, source}
        flat = []
        for row in values:
            for v in row:
                flat.append(v["value"] if isinstance(v, dict) else v)
        vmax_cfg = ch_cfg.get("y_max")
        vmax = float(vmax_cfg) if vmax_cfg else self._nice(max(flat) * 1.15)
        x_label_h = 40.0
        y0 = cy + ch - x_label_h
        ch_h = ch - x_label_h - 6
        scale = self._y_axis(layer, p, area, vmax, unit, ch_h, y0)
        ng = len(groups)
        slot = cw / len(cats)
        gw_all = min(88.0, slot * 0.7)
        bw = gw_all / ng
        for ci, cat in enumerate(cats):
            for gi, g in enumerate(groups):
                v = values[ci][gi]
                item = v if isinstance(v, dict) else {"value": v}
                color = OKABE_ITO.get(g.get("color") or SERIES_ORDER[gi % len(SERIES_ORDER)])
                bx = cx + slot * ci + (slot - gw_all) / 2 + bw * gi
                bh = item["value"] * scale
                gid_ = f"{cat['id']}--{g['id']}"
                src = self._value_source(item, g, p["id"], f"{cat.get('label')}/{g['label']}")
                layer.items.append(Rect(pid=gid_, x=bx, y=y0 - bh, w=bw, h=bh,
                                        fill=color, stroke="none", stroke_w=0, rx=2,
                                        desc=self._srd({"source": src}, "datum")))
                self.track(gid_, p["id"], "datum",
                           f"{cat.get('label')} / {g['label']} = {self._fmt_num(item['value'])}{unit}",
                           src, {"channel": "length", "value": item["value"], "unit": unit,
                                 "scale_px_per_unit": round(scale, 3), "zero_baseline": True,
                                 "color": color, "series": g["label"]},
                           [bx, y0 - bh, bw, bh])
                if ch_cfg.get("show_values", True):
                    vt = self._fmt_num(item["value"])
                    t = Text(pid=gid_ + "-value", x=bx + bw / 2, y=y0 - bh - 18, text=vt,
                             size=S_TICK, bold=True, color=INK, align="center")
                    t.meta["max_width"] = bw + 16
                    layer.items.append(t)
            lbl = wrap_text(cat.get("label", cat["id"]), S_TICK, slot - 8, max_lines=2)
            t = Text(pid=cat["id"] + "-xlabel", x=cx + slot * ci + slot / 2, y=y0 + 8,
                     text="\n".join(lbl), size=S_TICK, color=INK, align="center")
            t.meta["max_width"] = slot - 8
            layer.items.append(t)

    def _chart_line(self, layer, p, area, ch_cfg):
        cx, cy, cw, ch = area
        unit = ch_cfg.get("unit", "")
        xlabels = ch_cfg["x_labels"]
        series = ch_cfg["series"]
        vmax_cfg = ch_cfg.get("y_max")
        vmax = float(vmax_cfg) if vmax_cfg else self._nice(
            max(pt["value"] if isinstance(pt, dict) else pt
                for s in series for pt in s["values"]) * 1.15)
        x_label_h = 36.0
        y0 = cy + ch - x_label_h
        ch_h = ch - x_label_h - 6
        scale = self._y_axis(layer, p, area, vmax, unit, ch_h, y0)
        n = len(xlabels)
        for xi, xl in enumerate(xlabels):
            xx = cx + (cw if n == 1 else cw * xi / (n - 1))
            t = Text(pid=f"{p['id']}-x-{xi}", x=xx, y=y0 + 8, text=xl, size=S_TICK,
                     color=INK, align="center")
            t.meta["max_width"] = cw / max(1, n - 1)
            layer.items.append(t)
        for si, s in enumerate(series):
            color = OKABE_ITO.get(s.get("color") or SERIES_ORDER[si % len(SERIES_ORDER)])
            pts = []
            for xi, pt in enumerate(s["values"]):
                v = pt["value"] if isinstance(pt, dict) else pt
                xx = cx + (cw if n == 1 else cw * xi / (n - 1))
                pts.append((xx, y0 - v * scale))
            layer.items.append(Polyline(pid=s["id"] + "-line", pts=pts, stroke=color,
                                        stroke_w=2.6, desc=self._srd(s, "series")))
            for xi, pt in enumerate(s["values"]):
                v = pt["value"] if isinstance(pt, dict) else pt
                xx = cx + (cw if n == 1 else cw * xi / (n - 1))
                did = f"{s['id']}-pt{xi}"
                layer.items.append(Circle(pid=did, cx=xx, cy=y0 - v * scale, r=4.5,
                                          fill=color, desc=self._srd(
                                              {"source": (pt.get("source") if isinstance(pt, dict) else None)
                                               or s.get("source") or ch_cfg.get("series_source")},
                                              "datum")))
                self.track(did, p["id"], "datum",
                           f"{s['label']} @ {xlabels[xi]} = {self._fmt_num(v)}{unit}",
                           (pt.get("source") if isinstance(pt, dict) else None)
                           or s.get("source") or ch_cfg.get("series_source"),
                           {"channel": "position(y)", "value": v, "unit": unit,
                            "scale_px_per_unit": round(scale, 3), "zero_baseline": True,
                            "color": color, "series": s["label"]},
                           [xx - 4.5, y0 - v * scale - 4.5, 9, 9])

    def _chart_hbar(self, layer, p, area, ch_cfg):
        cx, cy, cw, ch = area
        unit = ch_cfg.get("unit", "")
        series = ch_cfg["series"]
        vmax_cfg = ch_cfg.get("y_max")
        vmax = float(vmax_cfg) if vmax_cfg else self._nice(max(s["value"] for s in series) * 1.15)
        label_w = min(150.0, cw * 0.38)
        bar_w_max = cw - label_w - 56
        scale = bar_w_max / vmax
        n = len(series)
        row_h = min(40.0, (ch - 10) / n)
        highlight = set(ch_cfg.get("highlight") or [])
        base = OKABE_ITO["blue"]
        for i, s in enumerate(series):
            by = cy + 10 + row_h * i + (row_h - 22) / 2
            lbl = wrap_text(s.get("label", s["id"]), S_TICK, label_w - 10, max_lines=2)
            t = Text(pid=s["id"] + "-hlabel", x=cx, y=by - 2, text="\n".join(lbl),
                     size=S_TICK, color=INK, align="left")
            t.meta["max_width"] = label_w - 10
            layer.items.append(t)
            bl = s["value"] * scale
            color = OKABE_ITO["vermillion"] if s["id"] in highlight else base
            src = self._value_source(s, ch_cfg, p["id"], s.get("label", s["id"]))
            layer.items.append(Rect(pid=s["id"], x=cx + label_w, y=by, w=bl, h=22,
                                    fill=color, stroke="none", stroke_w=0, rx=3,
                                    desc=self._srd({"source": src}, "datum")))
            self.track(s["id"], p["id"], "datum",
                       f"{s.get('label')} = {self._fmt_num(s['value'])}{unit}", src,
                       {"channel": "length", "value": s["value"], "unit": unit,
                        "scale_px_per_unit": round(scale, 3), "zero_baseline": True,
                        "color": color, "direction": "horizontal"},
                       [cx + label_w, by, bl, 22])
            vt = self._fmt_num(s["value"]) + (unit if unit else "")
            t = Text(pid=s["id"] + "-value", x=cx + label_w + bl + 8, y=by + 3,
                     text=vt, size=S_VALUE, bold=True, color=INK, align="left")
            layer.items.append(t)
        y_axis_x = cx + label_w
        layer.items.append(Line(pid=f"{p['id']}-baseline", x1=y_axis_x, y1=cy + 6,
                                x2=y_axis_x, y2=cy + 10 + row_h * n, stroke=INK,
                                stroke_w=1.5, desc="zero baseline"))
        if unit:
            layer.items.append(Text(pid=f"{p['id']}-unit", x=y_axis_x + 4, y=cy - 6,
                                    text=unit, size=S_TICK, bold=True, color=MUTED,
                                    align="left"))

    def _nice(self, v):
        import math
        if v <= 0:
            return 1.0
        exp = math.floor(math.log10(v))
        f = v / (10 ** exp)
        nf = 1 if f <= 1 else 2 if f <= 2 else 2.5 if f <= 2.5 else 5 if f <= 5 else 10
        return nf * (10 ** exp)

    # -- stats / text panels ---------------------------------------------------
    def _panel_stats(self, layer, p, rect):
        x, y, w, h = rect
        cx, cy, cw, ch = self._panel_frame(layer, p, rect)
        stats = p.get("stats", [])
        cols = min(len(stats), 2)
        rows = (len(stats) + cols - 1) // cols
        cell_w, cell_h = cw / cols, ch / rows
        for i, s in enumerate(stats):
            r, c = divmod(i, cols)
            # center an odd trailing item across the full row width
            in_row = len(stats) - r * cols
            if in_row == 1 and cols > 1:
                scx = cx + cw / 2
                half_w = cw / 2
            else:
                scx = cx + cell_w * c + cell_w / 2
                half_w = cell_w
            scy = cy + cell_h * r + cell_h / 2
            accent = OKABE_ITO.get(s.get("accent", "blue"), OKABE_ITO["blue"])
            t = Text(pid=s["id"], x=scx, y=scy - 34, text=s["value"], size=S_STAT,
                     bold=True, color=accent, align="center",
                     desc=self._srd(s, "datum"))
            t.meta["max_width"] = half_w - 16
            layer.items.append(t)
            self.track(s["id"], p["id"], "datum", f"{s['value']} {s.get('label', '')}",
                       s.get("source"),
                       {"channel": "text+size", "detail": f"big-number callout, color {accent}"},
                       [scx - half_w / 2, scy - 40, half_w, 60])
            lbl = wrap_text(s.get("label", ""), S_STATLBL, half_w - 20, max_lines=3)
            t2 = Text(pid=s["id"] + "-label", x=scx, y=scy + 20, text="\n".join(lbl),
                      size=S_STATLBL, color=INK, align="center")
            t2.meta["max_width"] = half_w - 20
            layer.items.append(t2)

    def _panel_text(self, layer, p, rect):
        x, y, w, h = rect
        cx, cy, cw, ch = self._panel_frame(layer, p, rect)
        bullets = p.get("bullets", [])
        yy = cy + 6
        accent = OKABE_ITO[ROLE_COLORS.get(p.get("role", "conclusion"), "purple")]
        for i, b in enumerate(bullets):
            lines = wrap_text(b["text"], S_BULLET, cw - 30)
            blk = len(lines) * S_BULLET * 1.34
            layer.items.append(Rect(pid=b["id"] + "-marker", x=cx, y=yy + 5, w=9, h=9,
                                    fill=accent, stroke="none", stroke_w=0))
            t = Text(pid=b["id"], x=cx + 22, y=yy, text=b["text"], size=S_BULLET,
                     color=INK, align="left", desc=self._srd(b, "claim"))
            t.meta["max_width"] = cw - 30
            layer.items.append(t)
            self.track(b["id"], p["id"], "claim", b["text"], b.get("source"),
                       {"channel": "text", "detail": "bullet conclusion claim"},
                       [cx, yy, cw, blk])
            yy += blk + 14
        if yy - 14 > cy + ch + 0.5:
            self.note("error", "panel-content-overflow",
                      f"panel '{p['id']}' bullets need {yy - cy:.0f}px but {ch:.0f}px available; "
                      f"shorten text or enlarge canvas.height")

    # -- legend -----------------------------------------------------------------
    def _legend(self, layer, items, W, y):
        total = 0.0
        widths = []
        for it in items:
            lw = text_width(it.get("label", ""), S_LEGEND) + 34
            widths.append(lw)
            total += lw
        x = max(20.0, (W - total) / 2)
        for it, lw in zip(items, widths):
            color = OKABE_ITO.get(it.get("color", "blue"), OKABE_ITO["blue"])
            layer.items.append(Rect(pid=it["id"], x=x, y=y, w=20, h=13, fill=color,
                                    stroke="none", stroke_w=0, rx=2,
                                    desc=self._srd(it, "legend")))
            self.track(it["id"], None, "legend_item", it.get("label", ""),
                       it.get("source"),
                       {"channel": "color", "detail": f"swatch color {color} means: {it.get('meaning', it.get('label', ''))}"},
                       [x, y, 20, 13])
            t = Text(pid=it["id"] + "-label", x=x + 26, y=y - 1, text=it.get("label", ""),
                     size=S_LEGEND, color=INK, align="left")
            t.meta["max_width"] = lw - 30
            layer.items.append(t)
            x += lw
        if total > W - 40:
            self.note("warning", "legend-overflow",
                      f"legend row is {total:.0f}px wide on a {W:.0f}px canvas; shorten labels")


def build_from_model(model: dict) -> tuple[Scene, dict, list[dict]]:
    b = Builder(model)
    scene, report = b.build()
    return scene, report, b.elements
