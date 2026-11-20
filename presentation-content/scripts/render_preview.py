#!/usr/bin/env python3
"""render_preview.py — export a render of the deck and audit it.

Two jobs:
  1. Convert deck.pptx -> PDF (and PNGs when a rasterizer exists) using a
     headless LibreOffice/soffice found on the machine.
  2. Round-trip audit with python-pptx: slide count, notes coverage, text
     presence, figure markers, fonts referenced — so a failed conversion still
     leaves a checkable record instead of silent nothing.

Honesty contract: if rendering is impossible in this environment the report
says so explicitly (render_gap) and the agent must surface it in result.json
instead of claiming a preview that does not exist.

Usage:
  python render_preview.py --pptx deck.pptx --outdir previews [--timeout 120]
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

SOFFICE_CANDIDATES = [
    "soffice", "libreoffice",
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice", "/opt/libreoffice/program/soffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
]


def find_soffice():
    for cand in SOFFICE_CANDIDATES:
        try:
            p = shutil.which(cand) or (cand if os.path.isfile(cand) else None)
        except OSError:
            p = None
        if p:
            return p
    # last resort: glob for LibreOffice on Windows
    for pat in (r"C:\Program Files*\LibreOffice*\program\soffice.exe",):
        hits = glob.glob(pat)
        if hits:
            return hits[0]
    return None


def convert(pptx, outdir, timeout):
    soffice = find_soffice()
    if not soffice:
        return {"status": "unavailable",
                "render_gap": "no soffice/LibreOffice found in this "
                              "environment; PDF preview could not be produced "
                              "here — record this honestly in result.json"}
    os.makedirs(outdir, exist_ok=True)
    try:
        r = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir",
             outdir, pptx],
            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "error",
                "render_gap": "soffice conversion timed out after %ss" % timeout}
    except OSError as e:
        return {"status": "error", "render_gap": "soffice failed to run: %s" % e}
    base = os.path.splitext(os.path.basename(pptx))[0] + ".pdf"
    pdf_path = os.path.join(outdir, base)
    if r.returncode != 0 or not os.path.isfile(pdf_path):
        return {"status": "error",
                "render_gap": "soffice exited %s; stderr: %s" % (
                    r.returncode, (r.stderr or "")[:400])}
    out = {"status": "ok", "pdf": pdf_path,
           "soffice": soffice, "stdout": (r.stdout or "")[:200]}
    # rasterize if pdftoppm exists (optional)
    if shutil.which("pdftoppm"):
        try:
            subprocess.run(["pdftoppm", "-png", "-r", "80", pdf_path,
                            os.path.join(outdir, "slide")],
                           check=True, capture_output=True, timeout=timeout)
            out["pngs"] = sorted(glob.glob(os.path.join(outdir, "slide*.png")))
        except Exception as e:  # noqa: BLE001
            out["png_note"] = "pdftoppm failed: %s" % e
    return out


def audit(pptx):
    from pptx import Presentation
    prs = Presentation(pptx)
    slides = []
    fonts = set()
    for i, s in enumerate(prs.slides, 1):
        texts = 0
        has_notes = False
        gap_markers = []
        try:
            if s.has_notes_slide and s.notes_slide.notes_text_frame.text.strip():
                has_notes = True
        except Exception:  # noqa: BLE001
            pass
        for sh in s.shapes:
            if sh.has_text_frame:
                t = sh.text_frame.text
                texts += len(t.strip())
                if "[图缺失]" in t:
                    gap_markers.append(t.strip()[:80])
                for p in sh.text_frame.paragraphs:
                    for r in p.runs:
                        if r.font.name:
                            fonts.add(r.font.name)
        slides.append({"slide": i, "layout": s.slide_layout.name,
                       "text_chars": texts, "notes": has_notes,
                       "gap_markers": gap_markers})
    n_no_notes = sum(1 for s in slides if not s["notes"])
    return {"status": "ok", "n_slides": len(slides),
            "slides_without_notes": n_no_notes, "fonts_used": sorted(fonts),
            "gap_marker_count": sum(len(s["gap_markers"]) for s in slides),
            "slides": slides}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pptx", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args()
    if not os.path.isfile(args.pptx):
        print(json.dumps({"status": "error",
                          "reason": "pptx not found: %s" % args.pptx}))
        sys.exit(2)
    report = {"pptx": args.pptx, "render": convert(args.pptx, args.outdir,
                                                   args.timeout),
              "audit": audit(args.pptx)}
    os.makedirs(args.outdir, exist_ok=True)
    with open(os.path.join(args.outdir, "render_report.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    ok = report["render"]["status"] == "ok" and report["audit"]["status"] == "ok"
    print(json.dumps({"status": "ok" if ok else report["render"]["status"],
                      "render": report["render"]["status"],
                      "n_slides": report["audit"].get("n_slides"),
                      "slides_without_notes":
                          report["audit"].get("slides_without_notes"),
                      "report": os.path.join(args.outdir,
                                             "render_report.json")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
