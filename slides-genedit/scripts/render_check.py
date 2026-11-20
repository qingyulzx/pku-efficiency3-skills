"""Render a .pptx to PDF (LibreOffice / office-renderer) and check the result.

Usage:
    python render_check.py --pptx deck.pptx --outdir render/

Finds soffice via $SOFFICE, PATH, or common install locations. Writes
render-report.json with: render status, PDF path, PDF page count vs slide
count, declared fonts. Failures are reported honestly (never faked):
a render failure is recorded and exits non-zero so the agent handles it as
an exception path.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pptx_tools as T
from pptx import Presentation


def find_soffice(explicit=None):
    cands = []
    if explicit:
        cands.append(explicit)
    if os.environ.get("SOFFICE"):
        cands.append(os.environ["SOFFICE"])
    for exe in ("soffice", "libreoffice"):
        found = shutil.which(exe)
        if found:
            cands.append(found)
    cands += [
        "/usr/bin/soffice", "/usr/local/bin/soffice",
        "/opt/libreoffice/program/soffice",
        "/usr/lib/libreoffice/program/soffice",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    cands += glob.glob("/opt/libreoffice*/program/soffice")
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def pdf_page_count(pdf_path):
    """Count '/Type /Page' objects. Classic xref PDFs only; reports the method
    honestly. Returns (count, method, confidence)."""
    with open(pdf_path, "rb") as f:
        data = f.read()
    n = len(re.findall(rb"/Type\s*/Page[^s]", data))
    if n > 0:
        return n, "regex /Type /Page object scan", "high (uncompressed xref)"
    return None, "regex scan found no page objects", "low (PDF may use object streams)"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pptx", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--soffice", default=None)
    ap.add_argument("--timeout", type=int, default=240, help="seconds")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    report = {"pptx": os.path.abspath(args.pptx), "render_status": "not_attempted"}

    prs = Presentation(args.pptx)
    slide_count = len(prs.slides._sldIdLst)
    report["slide_count"] = slide_count
    report["fonts_declared"] = T.declared_fonts(prs)

    soffice = find_soffice(args.soffice)
    if soffice is None:
        report["render_status"] = "failed"
        report["error"] = (
            "no LibreOffice/office-renderer executable found; install one or "
            "point $SOFFICE at it. Deliver the .pptx and record this honestly."
        )
        _write(report, args.outdir)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    report["soffice"] = soffice
    cmd = [soffice, "--headless", "--norestore", "--convert-to", "pdf",
           "--outdir", os.path.abspath(args.outdir), os.path.abspath(args.pptx)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        report["render_status"] = "failed"
        report["error"] = "soffice timed out after %ss" % args.timeout
        _write(report, args.outdir)
        raise SystemExit(1)

    expected_pdf = os.path.join(
        os.path.abspath(args.outdir),
        os.path.splitext(os.path.basename(args.pptx))[0] + ".pdf",
    )
    if proc.returncode != 0 or not os.path.isfile(expected_pdf):
        report["render_status"] = "failed"
        report["error"] = "soffice exit %s; stderr tail: %s" % (
            proc.returncode, proc.stderr.decode("utf-8", "replace")[-500:]
        )
        _write(report, args.outdir)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    count, method, confidence = pdf_page_count(expected_pdf)
    report.update({
        "render_status": "ok",
        "pdf_path": expected_pdf,
        "pdf_size_bytes": os.path.getsize(expected_pdf),
        "pdf_page_count": count,
        "page_count_method": method,
        "page_count_confidence": confidence,
        "page_count_match": (count == slide_count) if count is not None else None,
        "issues": [],
    })
    if count is not None and count != slide_count:
        report["issues"].append(
            "PDF has %s pages but deck has %s slides" % (count, slide_count)
        )
    _write(report, args.outdir)
    print(json.dumps({
        "render_status": "ok",
        "pdf": expected_pdf,
        "pdf_page_count": count,
        "slide_count": slide_count,
        "page_count_match": report["page_count_match"],
        "fonts_declared": report["fonts_declared"],
    }, ensure_ascii=False, indent=2))


def _write(report, outdir):
    with open(os.path.join(outdir, "render-report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
