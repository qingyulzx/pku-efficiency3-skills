#!/usr/bin/env python3
"""parse_sources.py — build a verifiable inventory of source materials.

Reads every material file the case provides (PDF / Markdown / plain text /
DOCX / PPTX template / images), extracts text and structure, and writes a
JSON inventory that the agent uses to design the page-level outline.

Design rules:
  * Never fabricate content: whatever cannot be parsed is recorded as a gap.
  * Every extracted piece keeps a locator (file, page/section, line range).
  * Pure parsing only — all content decisions stay with the agent.

Usage:
  python parse_sources.py --input <file-or-dir> --out materials_index.json
                         [--workdir <dir>] [--max-pages N]
"""
import argparse
import hashlib
import json
import os
import re
import sys

CAPTION_RE = re.compile(
    r"^\s*((?:Figure|Fig\.|Table|图|表|Algorithm|算法)\s*[A-Za-z0-9.:\-]+)[:.，。]?\s*(.{0,160})",
    re.IGNORECASE)
SECTION_RE = re.compile(
    r"^\s*((?:\d+\.){0,3}\s?\d*\s?[A-Z][A-Za-z \-]{2,60})\s*$")
MD_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
DOLLAR_RE = re.compile(r"\$[^$]{2,}\$|\\\(|\\\[")
MAX_TEXT_PER_PAGE = 6000


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def split_sections(lines):
    """Light structural pass over plain lines -> sections + captions + equations."""
    sections, cur = [], {"heading": "(front matter)", "lines": []}
    captions, equations = [], []
    for i, line in enumerate(lines):
        m = MD_HEADING_RE.match(line)
        if m:
            if cur["lines"] or len(sections) > 1 or sections:
                sections.append(cur)
            cur = {"heading": m.group(2).strip(), "lines": []}
            continue
        cm = CAPTION_RE.match(line)
        if cm and len(cm.group(1)) <= 14:
            captions.append({"label": cm.group(1).strip(),
                             "caption": cm.group(2).strip(), "line": i + 1})
        if DOLLAR_RE.search(line):
            equations.append({"line": i + 1, "text": line.strip()[:200]})
        cur["lines"].append(line)
    sections.append(cur)
    for s in sections:
        s["text"] = "".join(s["lines"]).strip()
        s["n_lines"] = len(s["lines"])
        s["locator"] = "lines %d-%d" % (
            1, s["n_lines"]) if s["text"] else "empty"
        del s["lines"]
    return sections, captions, equations


def parse_pdf(path, max_pages):
    pages, captions = [], []
    try:
        try:
            import pdfplumber as reader_lib  # preferred, richer
            backend = "pdfplumber"
        except ImportError:
            from pypdf import PdfReader as reader_lib  # noqa: N813
            backend = "pypdf"
        if backend == "pdfplumber":
            with reader_lib.open(path) as pdf:
                for pno, page in enumerate(pdf.pages[:max_pages], 1):
                    try:
                        txt = page.extract_text() or ""
                    except Exception as e:  # noqa: BLE001
                        txt = ""
                        pages.append({"page": pno, "chars": 0, "error": str(e)})
                        continue
                    pages.append(_pdf_page(pno, txt, captions))
        else:
            reader = reader_lib(path)
            for pno, page in enumerate(reader.pages[:max_pages], 1):
                try:
                    txt = page.extract_text() or ""
                except Exception as e:  # noqa: BLE001
                    txt = ""
                    pages.append({"page": pno, "chars": 0, "error": str(e)})
                    continue
                pages.append(_pdf_page(pno, txt, captions))
    except ImportError:
        return {"status": "error",
                "reason": "no PDF backend available (install pdfplumber or pypdf)"}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "reason": "cannot open PDF: %s" % e}
    total_chars = sum(p.get("chars", 0) for p in pages)
    out = {"status": "ok", "backend": backend, "pages": pages,
           "figures_tables": captions}
    if total_chars < 200 * len(pages) and pages:
        out["status"] = "warning"
        out["reason"] = ("very little text per page — likely a scanned PDF; "
                         "flag for OCR before designing pages")
    return out


def _pdf_page(pno, txt, captions):
    lines = [l for l in txt.splitlines() if l.strip()]
    for line in lines:
        cm = CAPTION_RE.match(line)
        if cm and len(cm.group(1)) <= 14:
            captions.append({"label": cm.group(1).strip(),
                             "caption": cm.group(2).strip(), "page": pno})
    return {"page": pno, "chars": len(txt),
            "text": txt[:MAX_TEXT_PER_PAGE],
            "first_lines": lines[:3]}


def parse_text_like(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    lines = raw.splitlines()
    sections, captions, equations = split_sections(lines)
    return {"status": "ok", "n_lines": len(lines), "n_chars": len(raw),
            "sections": sections, "figures_tables": captions,
            "equations": equations[:80]}


def parse_docx(path):
    try:
        import docx
    except ImportError:
        return {"status": "error", "reason": "python-docx not installed"}
    try:
        d = docx.Document(path)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "reason": "cannot open docx: %s" % e}
    sections, cur = [], {"heading": "(front matter)", "text_parts": []}
    captions = []
    for p in d.paragraphs:
        style = (p.style.name or "").lower()
        if "heading" in style or "title" in style:
            if cur["text_parts"]:
                sections.append(cur)
            cur = {"heading": p.text.strip() or style, "text_parts": []}
        else:
            if p.text.strip():
                cur["text_parts"].append(p.text.strip())
                cm = CAPTION_RE.match(p.text)
                if cm and len(cm.group(1)) <= 14:
                    captions.append({"label": cm.group(1).strip(),
                                     "caption": cm.group(2).strip()})
    sections.append(cur)
    out_sections = [{"heading": s["heading"],
                     "text": "\n".join(s["text_parts"])[:MAX_TEXT_PER_PAGE],
                     "locator": "docx paragraphs"}
                    for s in sections if s["text_parts"]]
    return {"status": "ok", "sections": out_sections, "figures_tables": captions}


def parse_pptx(path):
    """Extract text + layout inventory from a PPTX (template or starting deck)."""
    try:
        from pptx import Presentation
    except ImportError:
        return {"status": "error", "reason": "python-pptx not installed"}
    try:
        prs = Presentation(path)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "reason": "cannot open pptx: %s" % e}
    layouts = []
    for master in prs.slide_masters:
        for lay in master.slide_layouts:
            layouts.append({"master": master.name, "layout": lay.name,
                            "placeholders": [
                                {"idx": ph.placeholder_format.idx,
                                 "type": str(ph.placeholder_format.type),
                                 "name": ph.name}
                                for ph in lay.placeholders]})
    slides = []
    for i, s in enumerate(prs.slides, 1):
        slides.append({"slide": i, "layout": s.slide_layout.name,
                       "texts": [sh.text_frame.text[:500] for sh in s.shapes
                                 if sh.has_text_frame and sh.text_frame.text.strip()]})
    return {"status": "ok", "slide_size": [prs.slide_width, prs.slide_height],
            "layouts": layouts, "slides": slides}


def classify(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return "pdf"
    if ext in (".md", ".markdown"):
        return "markdown"
    if ext in (".txt", ".tex", ".bib"):
        return "text"
    if ext == ".docx":
        return "docx"
    if ext == ".pptx":
        return "pptx"
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".eps"):
        return "image"
    if ext == ".json":
        return "json"
    return "other"


def parse_one(path, max_pages):
    kind = classify(path)
    entry = {"path": path, "kind": kind, "bytes": os.path.getsize(path),
             "sha256": sha256_file(path)}
    try:
        if kind == "pdf":
            entry.update(parse_pdf(path, max_pages))
        elif kind in ("markdown", "text"):
            entry.update(parse_text_like(path))
        elif kind == "docx":
            entry.update(parse_docx(path))
        elif kind == "pptx":
            entry.update(parse_pptx(path))
        elif kind == "image":
            entry.update({"status": "ok",
                          "note": "image asset — usable as a figure if the "
                                  "outline binds it to a page"})
        elif kind == "json":
            with open(path, "r", encoding="utf-8") as f:
                entry.update({"status": "ok", "payload": json.load(f)})
        else:
            entry.update({"status": "warning",
                          "reason": "unsupported extension; not parsed"})
    except Exception as e:  # noqa: BLE001
        entry.update({"status": "error", "reason": "unexpected failure: %s" % e})
    return entry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="case material file or directory")
    ap.add_argument("--out", required=True, help="output inventory JSON path")
    ap.add_argument("--max-pages", type=int, default=60,
                    help="max PDF pages to parse (default 60)")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        print(json.dumps({"status": "error",
                          "reason": "input not found: %s" % args.input},
                         ensure_ascii=False))
        sys.exit(2)

    paths = []
    if os.path.isdir(args.input):
        for root, _dirs, files in os.walk(args.input):
            for name in sorted(files):
                p = os.path.join(root, name)
                if not os.path.islink(p):
                    paths.append(p)
    else:
        paths = [args.input]

    files = [parse_one(p, args.max_pages) for p in paths]
    n_err = sum(1 for f in files if f.get("status") == "error")
    n_warn = sum(1 for f in files if f.get("status") == "warning")
    inventory = {
        "input": args.input,
        "n_files": len(files),
        "n_errors": n_err,
        "n_warnings": n_warn,
        "files": files,
        "usage_note": "locators reference file path + page/section; keep them "
                      "verbatim in the page evidence map",
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(inventory, f, ensure_ascii=False, indent=1)
    print(json.dumps({"status": "ok" if n_err == 0 else "partial",
                      "n_files": len(files), "n_errors": n_err,
                      "n_warnings": n_warn, "out": args.out},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
