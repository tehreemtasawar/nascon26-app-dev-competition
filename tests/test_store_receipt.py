import base64
from app.store import generate_receipt_pdf

def test_pdf_receipt_generation():
    pdf_b64 = generate_receipt_pdf("ord-001", 450000)
    pdf_bytes = base64.b64decode(pdf_b64)
    # Must start with %PDF
    assert pdf_bytes.startswith(b"%PDF")
    # Must contain order_id and formatted total
    assert b"ord-001" in pdf_bytes
    assert b"PKR 4500.00" in pdf_bytes
