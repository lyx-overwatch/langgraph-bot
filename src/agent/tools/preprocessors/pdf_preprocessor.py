"""PDF skill preprocessor: handles Chinese / CJK font limitations in ReportLab."""

from __future__ import annotations

import re
from typing import Any

from agent.tools.preprocessors.registry import register

# ---------------------------------------------------------------------------
# Known limitations
# ---------------------------------------------------------------------------
# ReportLab's built-in fonts (Helvetica, Times) do NOT include CJK glyphs.
# Using Unicode subscript/superscript characters (₀₁₂₃₄…) renders as black boxes.
# PDF.js / pypdf / pdfplumber handle UTF-8 text natively; ReportLab needs care.
#
# We inject a "Before You Start" block at the TOP of the skill body so the
# agent sees it before generating any code.
# ---------------------------------------------------------------------------

# Sections in the PDF SKILL.md where we inject guidance.
_REPORTLAB_BLOCK_RE = re.compile(
    r"(## ReportLab[\s\S]*?)(```python\nfrom reportlab[\s\S]*?```)",
    re.IGNORECASE,
)

# Font families that support CJK (available in most Linux / LibreOffice environments).
CJK_FONT_NOTO = "Noto Sans CJK SC"
CJK_FONTS_FALLBACK = ["Noto Sans CJK SC", "WenQuanYi Micro Hei", "SimHei", "Arial Unicode MS"]


def _build_cjk_notice() -> str:
    """Markdown block injected at the top of the skill body."""
    return """

## \U0001F4D8 CJK / Chinese Text Handling (Important)

When creating or modifying a PDF that will contain **any Chinese characters**
(中文、日文汉字、韩文等), follow these rules **instead of** the generic
ReportLab instructions below:

### Fonts

| Situation | Font to use |
|-----------|-------------|
| Chinese text in `canvas.Canvas` | `canvas.setFont("{font}", size)` with one of the CJK fonts below |
| Chinese text in `Paragraph` | Pass `fontName="{font}"` via `Style(..., fontName="{font}")` |
| Available CJK fonts (try in order) | {fallback} |

If **none** of the above fonts are available, install them:
```bash
# Debian / Ubuntu
sudo apt-get install fonts-noto-cjk

# macOS
brew install font-noto-sans-cjk-sc   # or use Font Book

# Check available fonts at runtime
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
pdfmetrics.registerFont(TTFont("Noto Sans CJK SC", "/path/to/NotoSansCJKsc-Regular.ttc"))
```

### Forbidden: Unicode sub/superscript characters

**Never** paste Unicode subscript or superscript characters into ReportLab text:
`₀ ₁ ₂ ₃ ₄ ₅ ₆ ₇ ₈ ₉ ⁺ ⁻ ⁼ ⁿ ₀₁₂₃₄₅₆₇₈₉` — they render as solid black boxes.

**Instead**, use ReportLab XML markup inside `Paragraph`:
```python
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet

styles = getSampleStyleSheet()
styles["Normal"].fontName = "{font}"
p = Paragraph("H<super>2</super>O  x<super>2</super>+y<super>2</super>", styles["Normal"])
```

### Canvas-drawn Chinese text

For low-level `canvas.drawString` calls, use `setFont` with a CJK font and `drawString`:
```python
canvas.setFont("{font}", 12)
canvas.drawString(100, 700, "中文测试")
```

### Detection helper

Use this snippet before creating the PDF to check CJK font availability:
```python
def ensure_cjk_font(pdfmetrics, preferred="{font}"):
    available = [n for n, _ in pdfmetrics.fontName2pyfileName if preferred in n]
    if not available:
        raise RuntimeError(
            f"Preferred CJK font '{{preferred}}' not found. "
            "Please install fonts-noto-cjk or choose a fallback font."
        )
    return available[0]
```

---
""".format(font=CJK_FONT_NOTO, fallback=", ".join(CJK_FONTS_FALLBACK))


def _patch_reportlab_section(body: str) -> str:
    """Insert CJK notice before the first ReportLab code block so the agent sees it first."""
    cjk_notice = _build_cjk_notice()

    # Find "## ReportLab" heading and insert notice after it
    m = re.search(r"(## ReportLab[\s]*?\n)", body, re.IGNORECASE)
    if m:
        return body[: m.end()] + cjk_notice + body[m.end() :]

    # Fallback: prepend at very top
    return cjk_notice + body


@register("pdf")
def pdf_preprocessor(name: str, body: str, context: dict[str, Any]) -> str:
    """Inject CJK handling guidance into the PDF skill body."""
    return _patch_reportlab_section(body)
