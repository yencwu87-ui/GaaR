"""Local OCR for image-only PDF pages. Nothing leaves the machine.

A scanned page has no text layer, so plain extraction returns nothing for it and the document silently looks empty.
Here each page is read from its text layer first; a page with (almost) no text is rendered and passed to a local OCR
engine if one is installed, and otherwise reported as not extracted. It is never silently blank.

Engines, tried in order, all local and free of quotas:

- ``vision``    macOS Vision framework via the ``ocrmac`` package (pip install ocrmac), fast on Apple silicon;
- ``paddle``    PaddleOCR, Baidu's open-source engine, run locally (pip install paddleocr paddlepaddle);
- ``tesseract`` Tesseract via ``pytesseract`` (brew install tesseract; pip install pytesseract).

Cloud OCR (including Baidu's hosted API) is deliberately not wired in: evidence would leave the institution, and
hosted free tiers are quota-limited.
"""
from __future__ import annotations

import io
from typing import Callable

MIN_TEXT_CHARS = 25


def _vision():
    import importlib.util
    if importlib.util.find_spec("ocrmac") is None:
        raise ImportError("ocrmac is not installed")
    from PIL import Image

    def run(png: bytes) -> str:
        from ocrmac import ocrmac as o
        return "\n".join(t for t, _conf, _box in o.OCR(Image.open(io.BytesIO(png))).recognize())
    return run


def _paddle():
    from paddleocr import PaddleOCR
    engine = PaddleOCR(lang="en", show_log=False)

    def run(png: bytes) -> str:
        import numpy as np
        from PIL import Image
        result = engine.ocr(np.array(Image.open(io.BytesIO(png)).convert("RGB")))
        return "\n".join(line[1][0] for block in (result or []) for line in (block or []))
    return run


def _tesseract():
    import pytesseract
    from PIL import Image
    pytesseract.get_tesseract_version()                     # raises if the binary is missing

    def run(png: bytes) -> str:
        return pytesseract.image_to_string(Image.open(io.BytesIO(png)))
    return run


ENGINES: dict[str, Callable[[], Callable[[bytes], str]]] = {"vision": _vision, "paddle": _paddle, "tesseract": _tesseract}


def available_engine(preferred: str | None = None) -> tuple[str | None, Callable[[bytes], str] | None]:
    names = [preferred] if preferred else list(ENGINES)
    for name in names:
        try:
            return name, ENGINES[name]()
        except Exception:
            continue
    return None, None


def extract_pdf(data: bytes, *, engine: tuple[str | None, Callable[[bytes], str] | None] | None = None,
                min_chars: int = MIN_TEXT_CHARS, dpi: int = 200) -> dict:
    """Text for every page, with how each page was read: 'text', 'ocr:<engine>' or 'not_extracted'."""
    import fitz
    from pypdf import PdfReader
    resolved = engine                                   # started only when a page needs it (PaddleOCR loads models)
    pages, texts = [], []
    # The text layer is read with pypdf, exactly as before, so verbatim anchors drafted from earlier extractions
    # still match. PyMuPDF is used only to render a page that needs OCR.
    layer = [(p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages]
    with fitz.open(stream=data, filetype="pdf") as doc:
        for number, page in enumerate(doc, start=1):
            text = layer[number - 1] if number <= len(layer) else ""
            method = "text"
            if len(text.strip()) < min_chars:
                if resolved is None:
                    resolved = available_engine()
                name, run = resolved
                if run is not None:
                    text = run(page.get_pixmap(dpi=dpi).tobytes("png")) or ""
                    method = f"ocr:{name}" if text.strip() else "not_extracted"
                else:
                    method = "not_extracted"
            if method == "not_extracted":
                text = (f"[page {number}: image-only, not extracted. Install a local OCR engine "
                        "(see governance/ocr.py) and re-run.]")
            pages.append({"page": number, "method": method, "chars": len(text.strip())})
            texts.append(text)
    return {"text": "\n\n".join(texts), "pages": pages, "engine": resolved[0] if resolved else None,
            "not_extracted": [p["page"] for p in pages if p["method"] == "not_extracted"],
            "ocr_pages": [p["page"] for p in pages if p["method"].startswith("ocr:")]}
