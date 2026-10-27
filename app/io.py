"""CSV in, Payment objects out."""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .detect import Payment

COLUMNS = ("doc_id", "vendor_id", "vendor_name", "invoice_no", "amount",
           "currency", "invoice_date", "paid_on", "company_code", "po", "source")


def row_to_payment(r: dict) -> Payment:
    return Payment(
        doc_id=r["doc_id"].strip(), vendor_id=r["vendor_id"].strip(),
        vendor_name=r["vendor_name"].strip(), invoice_no=r["invoice_no"].strip(),
        amount=float(r["amount"]), currency=r["currency"].strip().upper(),
        invoice_date=date.fromisoformat(r["invoice_date"].strip()),
        paid_on=date.fromisoformat(r["paid_on"].strip()),
        company_code=r["company_code"].strip(), po=r.get("po", "").strip(),
        source=r.get("source", "").strip() or ("PO" if r.get("po", "").strip() else "non-PO"),
    )


def load(path: str | Path) -> list[Payment]:
    with open(path, newline="", encoding="utf-8") as fh:
        return [row_to_payment(r) for r in csv.DictReader(fh)]
