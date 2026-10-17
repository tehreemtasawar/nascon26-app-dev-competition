import os
import io
import math
import base64
from datetime import datetime, timezone
from typing import Dict, Any, List
from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

from app.crypto import sign, canonical
from app.errors import APIError

store_router = APIRouter()

def get_salt():
    return os.getenv("DAY1_SALT", "demo-salt")

def generate_receipt_pdf(order_id: str, total_minor: int) -> str:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter, pageCompression=0)
    major_total = f"PKR {total_minor / 100:.2f}"
    c.drawString(100, 750, f"Receipt: {order_id}")
    c.drawString(100, 720, f"Total: {major_total}")
    c.save()
    pdf_bytes = buffer.getvalue()
    return base64.b64encode(pdf_bytes).decode("ascii")


# We import get_db lazily from main or configure it
from app.db import get_db

@store_router.get("/audit/v1/inventory/{variant_id}")
def get_inventory(variant_id: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock, reserved FROM inventory WHERE variant_id = %s", (variant_id,))
            row = cur.fetchone()
            if not row:
                raise APIError(404, "VARIANT_NOT_FOUND", f"Variant {variant_id} does not exist", {"variant_id": variant_id})
            return {
                "variant_id": variant_id,
                "stock": row[0],
                "reserved": row[1]
            }

@store_router.post("/audit/v1/checkout", status_code=201)
def checkout(body: Dict[str, Any], response: Response):
    # 1. Validation (400)
    order_id = body.get("order_id")
    customer_id = body.get("customer_id")
    items = body.get("items")
    discount_code = body.get("discount_code")
    payment = body.get("payment")

    fields = []
    if not isinstance(order_id, str) or not (1 <= len(order_id) <= 64):
        fields.append("order_id")
    if not isinstance(customer_id, str) or not customer_id:
        fields.append("customer_id")
    if not isinstance(items, list) or not (1 <= len(items) <= 10):
        fields.append("items")
    if not isinstance(payment, dict) or not payment.get("token"):
        fields.append("payment")

    if fields:
        raise APIError(400, "VALIDATION_ERROR", "Validation failed", {"fields": fields})

    # Validate items
    variant_ids = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise APIError(400, "VALIDATION_ERROR", "Invalid item structure", {"fields": [f"items[{idx}]"]})
        vid = item.get("variant_id")
        qty = item.get("quantity")
        if not isinstance(vid, str) or not vid:
            fields.append(f"items[{idx}].variant_id")
        if not isinstance(qty, int) or isinstance(qty, bool) or not (1 <= qty <= 10):
            fields.append(f"items[{idx}].quantity")
        if vid:
            variant_ids.append(vid)

    if len(variant_ids) != len(set(variant_ids)):
        fields.append("items.variant_id")

    if discount_code is not None and discount_code != "WELCOME10":
        raise APIError(400, "INVALID_DISCOUNT_CODE", f"Invalid discount code: {discount_code}")

    if fields:
        raise APIError(400, "VALIDATION_ERROR", "Validation failed", {"fields": fields})

    # Idempotency / Stored order check
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT request_body, response_body FROM store_orders WHERE order_id = %s", (order_id,))
            existing = cur.fetchone()
            if existing:
                stored_req, stored_res = existing[0], existing[1]
                # Compare bodies
                if canonical(stored_req) == canonical(body):
                    response.status_code = status.HTTP_200_OK
                    return stored_res
                else:
                    raise APIError(409, "DUPLICATE_ORDER_ID", f"Order {order_id} already exists with different body")

            # 2. Variants exist check (404)
            cur.execute("SELECT variant_id, price_minor, currency FROM variants WHERE variant_id = ANY(%s)", (variant_ids,))
            variant_rows = {row[0]: {"price_minor": row[1], "currency": row[2]} for row in cur.fetchall()}
            for vid in variant_ids:
                if vid not in variant_rows:
                    raise APIError(404, "VARIANT_NOT_FOUND", f"Variant {vid} not found", {"variant_id": vid})

            # 3. Atomically reserve stock for all items
            # Lock rows with SELECT FOR UPDATE
            cur.execute("SELECT variant_id, stock, reserved FROM inventory WHERE variant_id = ANY(%s) FOR UPDATE", (variant_ids,))
            inventory_rows = {row[0]: {"stock": row[1], "reserved": row[2]} for row in cur.fetchall()}

            for item in items:
                vid = item["variant_id"]
                qty = item["quantity"]
                inv = inventory_rows.get(vid)
                if not inv or inv["stock"] < qty:
                    conn.rollback()
                    raise APIError(409, "OUT_OF_STOCK", f"Variant {vid} has no stock left.", {"variant_id": vid})

            # Place reservation
            for item in items:
                vid = item["variant_id"]
                qty = item["quantity"]
                cur.execute(
                    "UPDATE inventory SET stock = stock - %s, reserved = reserved + %s WHERE variant_id = %s",
                    (qty, qty, vid)
                )

            # 4. Mock payment gateway
            token = payment["token"]
            if token == "tok_declined":
                # Release reservation
                for item in items:
                    vid = item["variant_id"]
                    qty = item["quantity"]
                    cur.execute(
                        "UPDATE inventory SET stock = stock + %s, reserved = reserved - %s WHERE variant_id = %s",
                        (qty, qty, vid)
                    )
                conn.commit()
                raise APIError(402, "PAYMENT_DECLINED", "Payment authorization declined by mock gateway")

            if token == "tok_capture_fail":
                for item in items:
                    vid = item["variant_id"]
                    qty = item["quantity"]
                    cur.execute(
                        "UPDATE inventory SET stock = stock + %s, reserved = reserved - %s WHERE variant_id = %s",
                        (qty, qty, vid)
                    )
                conn.commit()
                raise APIError(402, "PAYMENT_CAPTURE_FAILED", "Payment capture failed by mock gateway")

            if token != "tok_success":
                raise APIError(400, "VALIDATION_ERROR", f"Unknown mock payment token: {token}")

            # 5. On success: commit reservation (reserved decreases permanently)
            for item in items:
                vid = item["variant_id"]
                qty = item["quantity"]
                cur.execute(
                    "UPDATE inventory SET reserved = reserved - %s WHERE variant_id = %s",
                    (qty, vid)
                )

            # Calculate totals
            subtotal_minor = 0
            order_items = []
            for item in items:
                vid = item["variant_id"]
                qty = item["quantity"]
                unit_price = variant_rows[vid]["price_minor"]
                subtotal_minor += unit_price * qty
                order_items.append({
                    "variant_id": vid,
                    "quantity": qty,
                    "unit_price_minor": unit_price
                })

            discount_minor = 0
            if discount_code == "WELCOME10":
                discount_minor = math.floor(subtotal_minor * 10 / 100)
            total_minor = subtotal_minor - discount_minor

            paid_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            receipt_payload = {
                "order_id": order_id,
                "customer_id": customer_id,
                "items": order_items,
                "subtotal_minor": subtotal_minor,
                "discount_minor": discount_minor,
                "total_minor": total_minor,
                "currency": "PKR",
                "paid_at": paid_at
            }

            salt = get_salt()
            receipt_signature = sign(salt, order_id, receipt_payload)
            pdf_b64 = generate_receipt_pdf(order_id, total_minor)

            result = {
                "order_id": order_id,
                "status": "paid",
                "currency": "PKR",
                "items": order_items,
                "subtotal_minor": subtotal_minor,
                "discount_minor": discount_minor,
                "total_minor": total_minor,
                "payment": {
                    "authorization_id": f"auth_{order_id}",
                    "capture_id": f"cap_{order_id}",
                    "state": "captured"
                },
                "receipt": {
                    "payload": receipt_payload,
                    "signature": receipt_signature,
                    "pdf_base64": pdf_b64
                }
            }

            cur.execute(
                """
                INSERT INTO store_orders (order_id, variant_id, quantity, total_minor, status, request_body, response_body)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (order_id, items[0]["variant_id"], items[0]["quantity"], total_minor, "Paid", canonical(body), canonical(result))
            )
            conn.commit()

            return result
