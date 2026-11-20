"""Text measurement shared by every renderer.

Uses the standard Adobe Helvetica AFM advance widths (per 1000 units of em)
so that SVG, matplotlib and Pillow outputs agree on text metrics. CJK and
full-width characters are measured at 1.0 em, which matches most CJK fonts
closely enough for layout decisions.
"""
from __future__ import annotations

# Adobe Helvetica AFM widths, chars 32..126 (units/1000).
_W = [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,  #   !"#$%&'()*+,-./
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,  #  0-9:;<=>?
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,  #  @A-O
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,  #  P-Z [\]^_
    333, 556, 556, 556, 556, 556, 278, 556, 556, 222, 222, 556, 222, 833, 556, 556,  #  `a-o
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,       #  p-z {|}~
]
_TABLE = {chr(c): _W[c - 32] for c in range(32, 127)}
_BOLD_BIAS = 1.08  # Helvetica-Bold is ~5-10% wider; be conservative.


def char_width(ch: str, bold: bool = False) -> float:
    """Advance width of one character as a fraction of the font size."""
    cp = ord(ch)
    if 0x2E80 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF or 0xFF00 <= cp <= 0xFFEF or 0x3000 <= cp <= 0x303F:
        w = 1.0  # CJK ideographs & fullwidth forms
    elif ch in _TABLE:
        w = _TABLE[ch] / 1000.0
    elif ch == "\u2014" or ch == "\u2013":
        w = 1.0
    else:
        w = 0.6
    return w * (_BOLD_BIAS if bold else 1.0)


def text_width(text: str, size: float, bold: bool = False) -> float:
    """Estimated rendered width of `text` at font size `size` (same units)."""
    return sum(char_width(c, bold) for c in text) * size


def wrap_text(text: str, size: float, max_width: float, bold: bool = False,
              max_lines: int | None = None) -> list[str]:
    """Greedy word wrap using the shared metrics.

    Returns the list of lines. If a single word exceeds max_width it is kept
    on its own line (overflow is reported by the validator, not silently
    mangled). When max_lines is given and exceeded, the last kept line is
    truncated with an ellipsis and True-overflow is signalled by the caller
    comparing content length.
    """
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split(" ")
        cur = ""
        for w in words:
            cand = w if not cur else cur + " " + w
            if text_width(cand, size, bold) <= max_width or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    if max_lines is not None and len(lines) > max_lines:
        cut = lines[:max_lines]
        last = cut[-1]
        while last and text_width(last + "\u2026", size, bold) > max_width:
            last = last[:-1]
        cut[-1] = last + "\u2026"
        return cut
    return lines


def text_block_height(n_lines: int, size: float, line_gap: float = 1.28) -> float:
    return n_lines * size * line_gap
