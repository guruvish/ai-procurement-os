from io import BytesIO

import pandas as pd
import pymupdf as fitz
import pytest

from app.services.document_parser import DocumentError, parse_document


def _pdf_with_text(text: str) -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


def test_text_pdf_extracts_with_page_numbers():
    d = parse_document("Supplier_A.pdf", _pdf_with_text("Price: INR 185 per kg. Purity 99.8% minimum."))
    assert d.pages[0][0] == 1
    assert "INR 185" in d.pages[0][1]
    assert d.needs_vision is False
    assert len(d.sha256) == 64


def test_blank_pdf_is_flagged_as_scanned():
    doc = fitz.open()
    doc.new_page()
    d = parse_document("scan.pdf", doc.tobytes())
    assert d.needs_vision is True
    assert d.warnings


def test_fake_pdf_rejected_with_clear_message():
    with pytest.raises(DocumentError, match="not a real PDF"):
        parse_document("quote.pdf", b"hello I am not a pdf")


def test_corrupted_pdf_rejected():
    with pytest.raises(DocumentError):
        parse_document("broken.pdf", b"%PDF-1.4\n garbage garbage")


def test_unsupported_extension_rejected():
    with pytest.raises(DocumentError, match="unsupported"):
        parse_document("virus.exe", b"MZ....")


def test_xlsx_parsed_per_sheet():
    buf = BytesIO()
    pd.DataFrame({"Item": ["Paracetamol API"], "Price/kg": [190]}).to_excel(buf, index=False)
    d = parse_document("Supplier_B.xlsx", buf.getvalue())
    assert "Paracetamol API" in d.pages[0][1]


def test_csv_parsed():
    d = parse_document("s.csv", b"item,price\nParacetamol,180\n")
    assert "180" in d.pages[0][1]
