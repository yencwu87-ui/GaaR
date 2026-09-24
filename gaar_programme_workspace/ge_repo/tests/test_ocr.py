"""Local OCR for image-only PDF pages (kit v21): never silently blank, never sent anywhere."""
import fitz
from pypdf import PdfReader
import io

from governance import ocr


def _pdf():
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Guidelines on AI risk management for financial institutions. " * 4)
    scan = fitz.open()
    scan.new_page().insert_text((72, 72), "SCANNED BOARD MINUTES")
    image_only = doc.new_page()
    image_only.insert_image(image_only.rect, pixmap=scan[0].get_pixmap(dpi=100))
    return doc.tobytes()


def test_an_image_only_page_is_marked_not_blank_when_no_engine_is_installed():
    result = ocr.extract_pdf(_pdf(), engine=(None, None))
    assert [p["method"] for p in result["pages"]] == ["text", "not_extracted"] and result["not_extracted"] == [2]
    assert "[page 2: image-only, not extracted." in result["text"]


def test_an_image_only_page_goes_to_the_local_engine():
    seen = []
    result = ocr.extract_pdf(_pdf(), engine=("fake", lambda png: seen.append(png[:8]) or "Recognised minutes"))
    assert [p["method"] for p in result["pages"]] == ["text", "ocr:fake"] and seen == [b"\x89PNG\r\n\x1a\n"]
    assert "Recognised minutes" in result["text"]


def test_text_pages_read_exactly_as_before_so_existing_anchors_still_match():
    data = _pdf()
    before = (PdfReader(io.BytesIO(data)).pages[0].extract_text() or "")
    assert ocr.extract_pdf(data, engine=(None, None))["text"].split("\n\n")[0] == before


def test_no_engine_is_started_for_a_document_with_a_text_layer(monkeypatch):
    started = []
    monkeypatch.setattr(ocr, "available_engine", lambda preferred=None: started.append(1) or (None, None))
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "A normal text page with plenty of characters on it. " * 3)
    ocr.extract_pdf(doc.tobytes())
    assert started == []
