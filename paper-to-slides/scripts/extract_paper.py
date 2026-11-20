#!/usr/bin/env python3
"""extract_paper.py -- turn a research PDF into a structured per-page JSON inventory.

Output JSON shape (this is the contract consumed by the deck-planning step):
{
  "pdf_path": ..., "sha256": ..., "num_pages": N,
  "engine": "pypdf|pymupdf|pdfplumber",
  "pages": [
    {"page": 1, "text": "...", "char_count": 1234,
     "captions": [{"kind": "figure|table", "label": "Figure 1", "snippet": "...", "page": 3}],
     "images": [{"name": "...", "page": 3, "bytes": 45678, "extracted_to": "figs/p3_img0.png"}]}
  ],
  "figure_index": [{"label": "Figure 1", "page": 3, "snippet": "..."}],
  "table_index":  [...],
  "warnings": [...]
}

Backends are tried in order (pypdf -> pymupdf -> pdfplumber). If none is
installed, exit code 3 tells the agent to use the container pdf-text-tool /
pdf-render-tool instead and produce the same JSON shape manually.

Usage:
  python extract_paper.py --pdf <paper.pdf> --out <paper_pages.json> [--figdir <dir>]
                          [--pages 1-15] [--extract-images]
"""
import argparse
import hashlib
import json
import os
import re
import sys

CAPTION_RE = re.compile(
    r"(Figure|Fig\.|Table)\s+(\d+)[\.:]\s*([^\n]{0,200})", re.IGNORECASE)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pick_backend():
    try:
        import pypdf  # noqa: F401
        return "pypdf"
    except ImportError:
        pass
    try:
        import fitz  # noqa: F401
        return "pymupdf"
    except ImportError:
        pass
    try:
        import pdfplumber  # noqa: F401
        return "pdfplumber"
    except ImportError:
        pass
    return None


def parse_pages(spec, total):
    """'1-3,5' -> [1,2,3,5] (1-based). None -> all pages."""
    if not spec:
        return list(range(1, total + 1))
    out = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return [p for p in out if 1 <= p <= total]


def find_captions(text, page_no):
    caps = []
    for m in CAPTION_RE.finditer(text):
        kind = "figure" if m.group(1).lower().startswith("fig") else "table"
        label = ("Figure " if kind == "figure" else "Table ") + m.group(2)
        snippet = re.sub(r"\s+", " ", m.group(3)).strip()
        caps.append({"kind": kind, "label": label, "snippet": snippet,
                     "page": page_no})
    return caps


def extract_with_pypdf(pdf_path, pages_wanted, figdir, extract_images):
    from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    total = len(reader.pages)
    pages, warnings = [], []
    for pno in range(1, total + 1):
        page = reader.pages[pno - 1]
        try:
            text = page.extract_text() or ""
        except Exception as e:  # real failure path: unreadable page
            text = ""
            warnings.append(f"page {pno}: text extraction failed: {e}")
        entry = {"page": pno, "text": text, "char_count": len(text),
                 "captions": find_captions(text, pno), "images": []}
        if extract_images and pno in pages_wanted:
            try:
                for i, img in enumerate(page.images):
                    out_name = None
                    if figdir:
                        os.makedirs(figdir, exist_ok=True)
                        ext = os.path.splitext(img.name)[1] or ".png"
                        out_name = os.path.join(
                            figdir, f"p{pno}_img{i}{ext}")
                        with open(out_name, "wb") as f:
                            f.write(img.data)
                    entry["images"].append(
                        {"name": img.name, "page": pno,
                         "bytes": len(img.data), "extracted_to": out_name})
            except Exception as e:
                warnings.append(f"page {pno}: image extraction failed: {e}")
        pages.append(entry)
    return pages, warnings, total


def extract_with_pymupdf(pdf_path, pages_wanted, figdir, extract_images):
    import fitz
    doc = fitz.open(pdf_path)
    total = doc.page_count
    pages, warnings = [], []
    for pno in range(1, total + 1):
        page = doc[pno - 1]
        text = page.get_text()
        entry = {"page": pno, "text": text, "char_count": len(text),
                 "captions": find_captions(text, pno), "images": []}
        if extract_images and pno in pages_wanted:
            try:
                for i, info in enumerate(page.get_images(full=True)):
                    xref = info[0]
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n - pix.alpha > 3:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    out_name = None
                    if figdir:
                        os.makedirs(figdir, exist_ok=True)
                        out_name = os.path.join(figdir, f"p{pno}_img{i}.png")
                        pix.save(out_name)
                    entry["images"].append(
                        {"name": f"xref{xref}", "page": pno,
                         "bytes": pix.width * pix.height, "extracted_to": out_name})
                    pix = None
            except Exception as e:
                warnings.append(f"page {pno}: image extraction failed: {e}")
        pages.append(entry)
    return pages, warnings, total


def extract_with_pdfplumber(pdf_path, pages_wanted, figdir, extract_images):
    import pdfplumber
    pages, warnings = [], []
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        for pno, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            entry = {"page": pno, "text": text, "char_count": len(text),
                     "captions": find_captions(text, pno),
                     "images": [{"name": "region", "page": pno,
                                 "bytes": 0, "extracted_to": None}
                                for _ in (page.images or [])]}
            pages.append(entry)
    return pages, warnings, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--figdir", default=None)
    ap.add_argument("--pages", default=None,
                    help="subset like 1-5,8 (images only extracted for these)")
    ap.add_argument("--extract-images", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(args.pdf):
        print(json.dumps({"error": f"pdf not found: {args.pdf}"}))
        sys.exit(2)

    backend = pick_backend()
    if backend is None:
        print(json.dumps({
            "error": "no python pdf backend available (pypdf/pymupdf/pdfplumber)",
            "fallback": "use container pdf-text-tool for text and "
                        "pdf-render-tool for figure regions, then write the "
                        "same JSON shape as extract_paper.py output"}))
        sys.exit(3)

    total = None
    # cheap pre-count for page parsing
    if backend == "pypdf":
        from pypdf import PdfReader
        total = len(PdfReader(args.pdf).pages)
    elif backend == "pymupdf":
        import fitz
        total = fitz.open(args.pdf).page_count
    else:
        import pdfplumber
        with pdfplumber.open(args.pdf) as pdf:
            total = len(pdf.pages)
    pages_wanted = set(parse_pages(args.pages, total))

    fn = {"pypdf": extract_with_pypdf, "pymupdf": extract_with_pymupdf,
          "pdfplumber": extract_with_pdfplumber}[backend]
    pages, warnings, total = fn(args.pdf, pages_wanted, args.figdir,
                                args.extract_images)

    figure_index, table_index, seen = [], [], set()
    for p in pages:
        for c in p["captions"]:
            key = (c["kind"], c["label"])
            if key in seen:
                continue
            seen.add(key)
            (figure_index if c["kind"] == "figure" else table_index).append(c)

    result = {
        "pdf_path": os.path.abspath(args.pdf),
        "sha256": sha256_file(args.pdf),
        "num_pages": total,
        "engine": backend,
        "pages": pages,
        "figure_index": figure_index,
        "table_index": table_index,
        "warnings": warnings,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps({
        "ok": True, "engine": backend, "num_pages": total,
        "figures": len(figure_index), "tables": len(table_index),
        "image_files": sum(1 for p in pages for i in p["images"]
                           if i["extracted_to"]),
        "warnings": warnings, "out": os.path.abspath(args.out)},
        ensure_ascii=False))


if __name__ == "__main__":
    main()
