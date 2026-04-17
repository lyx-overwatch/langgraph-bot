"""PDF skill preprocessor: handles Chinese / CJK font limitations in ReportLab."""

from __future__ import annotations

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

# Prefer ReportLab built-in CID fonts first because they do not rely on host OS font files.
CJK_FONT_PRIMARY = "STSong-Light"
CJK_FONTS_FALLBACK = [
    "STSong-Light",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
    "SimHei",
    "Arial Unicode MS",
]


def _build_cjk_notice() -> str:
    """Markdown block injected at the top of the skill body."""
    return """

## Final Deliverable and Source-of-Truth Rules (Mandatory)

- Unless the user explicitly asks to keep helper files, produce exactly one final PDF deliverable.
- If you extract raw PDF text to `.txt` and also create a Markdown summary `.md`, the `.txt` file is the source of truth for final PDF content selection and wording verification.
- Do not typeset Markdown syntax directly into the final PDF. Remove heading markers (`#`), bullet markers (`-`, `*`), code fences, and emphasis markers (`**`) before rendering.
- A Markdown file may be used as an intermediate planning or summarization artifact, but it must not remain in the workspace after a successful build unless the user asked to keep it.
- If both `pdf_content.txt` and `pdf_summary.md` exist, use `pdf_content.txt` to verify the final wording and delete `pdf_summary.md` after the final PDF is produced unless the user requested the markdown file.
- If a temporary extraction or helper script is created solely to build the PDF, delete it after the final PDF is successfully generated unless the user requested the source file.

## \U0001F4D8 CJK / Chinese Text Handling (Important)

When creating or modifying a PDF that will contain **any Chinese characters**
(中文、日文汉字、韩文等), the rules in this section are **mandatory** and override the
generic ReportLab examples below.

### Mandatory requirements

1. If the final PDF contains any Chinese text, do **not** use Helvetica, Times,
    Courier, or any other Latin-only built-in font for those text nodes.
2. Prefer ReportLab's built-in CID font `{font}` first, because it does not
    require an OS font file.
3. If `{font}` cannot be used for the chosen API, register a TrueType/OpenType
    CJK font explicitly before writing any Chinese text.
4. If no usable CJK font can be registered, stop and return a clear error.
    Do **not** generate a PDF that will render Chinese as boxes or mojibake.
5. Before finishing, verify the generated code contains both font registration
    and font assignment for every Chinese `Paragraph`, `Table`, or
    `canvas.drawString` call.

### Fonts

| Situation | Font to use |
|-----------|-------------|
| Preferred for Chinese text | Register and use ReportLab CID font `{font}` |
| Chinese text in `canvas.Canvas` | `canvas.setFont("{font}", size)` or a registered fallback font |
| Chinese text in `Paragraph` | Pass `fontName="{font}"` via `Style(..., fontName="{font}")` |
| Available CJK fonts (try in order) | {fallback} |

Use the built-in CID font first:
```python
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

pdfmetrics.registerFont(UnicodeCIDFont("{font}"))
```

If you must use a system font instead, register it explicitly:
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

For Platypus styles, assign the same registered font explicitly:
```python
styles = getSampleStyleSheet()
styles["Title"].fontName = "{font}"
styles["Normal"].fontName = "{font}"
styles["Heading1"].fontName = "{font}"
```

### Forbidden fallback behavior

If Chinese text is present, these are invalid implementations and must be
rewritten before saving the PDF:

- `styles["Normal"].fontName = "Helvetica"`
- `styles["Title"].fontName = "Helvetica-Bold"`
- `canvas.drawString(..., "中文")` without first calling `setFont` with a CJK font
- Generating the PDF first and hoping downstream tools will "fix" garbled text

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
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont


def ensure_cjk_font(preferred="{font}", fallback_path=None, fallback_name="Noto Sans CJK SC"):
    try:
        pdfmetrics.getFont(preferred)
    except KeyError:
        try:
            pdfmetrics.registerFont(UnicodeCIDFont(preferred))
        except Exception:
            if not fallback_path:
                raise RuntimeError(
                    "No built-in or external CJK font is available. "
                    "Register a font explicitly before generating the PDF."
                )
            from reportlab.pdfbase.ttfonts import TTFont

            pdfmetrics.registerFont(TTFont(fallback_name, fallback_path))
            return fallback_name
    return preferred
```

### Temporary files and cleanup

When building a PDF, keep intermediate files out of the main workspace unless
the user explicitly asks to keep them.

- Use `tempfile.TemporaryDirectory()` or a dedicated temp subdirectory for
  extracted text, images, one-off scripts, and intermediate PDFs.
- Move or copy only the final deliverables requested by the user into the
  workspace.
- Always clean up in a `finally` block with `shutil.rmtree(...)` or
  `Path.unlink(missing_ok=True)`.
- Close file handles before cleanup.
- If you created a helper script only to build the final PDF, delete it after a
  successful build unless the user asked to retain source files.

Minimal pattern:
```python
from pathlib import Path
from shutil import rmtree
from tempfile import TemporaryDirectory


with TemporaryDirectory(prefix="pdf-build-") as temp_dir:
    temp_root = Path(temp_dir)
    temp_text = temp_root / "summary.txt"
    temp_pdf = temp_root / "summary.pdf"
    # build artifacts in temp_root
    final_pdf = Path("summary.pdf")
    final_pdf.write_bytes(temp_pdf.read_bytes())
```

### Final checklist before you finish

- Exactly one final PDF deliverable remains unless the user requested more
- If a `.txt` extraction exists, it was used as the source of truth for final text selection
- No Markdown markers (`#`, `-`, `*`, `**`, ``` ) appear in the final PDF content
- Chinese text present -> CJK font registered
- Chinese styles and canvas calls use that font
- No Helvetica/Times/Courier on Chinese content
- Final PDF opens successfully
- Temporary files removed unless the user asked to keep them

---
""".format(font=CJK_FONT_PRIMARY, fallback=", ".join(CJK_FONTS_FALLBACK))


def _patch_reportlab_section(body: str) -> str:
    """Insert CJK notice before the first ReportLab code block so the agent sees it first."""
    cjk_notice = _build_cjk_notice()

    return cjk_notice + body


@register("pdf")
def pdf_preprocessor(name: str, body: str, context: dict[str, Any]) -> str:
    """Inject CJK handling guidance into the PDF skill body."""
    return _patch_reportlab_section(body)
