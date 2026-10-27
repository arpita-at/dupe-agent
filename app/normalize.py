"""Canonical forms. Deterministic. No model is called in this file.

This is the whole reason near-duplicates survive an ERP's own duplicate check.

SAP's standard check (and every ERP's) compares vendor, invoice number, amount
and date as stored. `INV-0012` and `inv 12` are different strings, so the check
passes and the invoice is paid twice. The exact duplicates are already blocked.
The money is in the ones that only look different.
"""
from __future__ import annotations

import re
import unicodedata

#: Words that carry no identity in a vendor name. "Acme Ltd" and "ACME Limited"
#: are the same counterparty and should land in the same block.
LEGAL_FORMS = {
    "ltd", "limited", "llp", "llc", "inc", "incorporated", "plc", "pvt", "private",
    "gmbh", "sa", "sas", "bv", "nv", "ag", "co", "company", "corp", "corporation",
    "pte", "srl", "spa", "oy", "ab", "as",
}


def invoice_key(raw: str) -> str:
    """Canonical invoice number.

    Strips separators, case and leading zeros, so every one of these collapses
    to the same key: `INV-0012`, `inv 12`, `INV0012`, `inv/12`, `12`.

    Leading zeros go last and only on the trailing numeric run, so `INV-0012`
    becomes `inv12` while `007-A` keeps its shape where the digits are not a
    pure suffix.
    """
    s = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]", "", s).lower()
    return re.sub(r"(\D*?)0*(\d+)$", r"\1\2", s) if s else ""


def vendor_key(raw: str) -> str:
    """Canonical vendor name, for catching one invoice billed to two vendor
    master records. Duplicate vendor masters are the single most common cause
    of a duplicate that survives every automated check, because to the ERP the
    two payments went to two different suppliers."""
    s = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9\s]", " ", s).lower()
    parts = [w for w in s.split() if w and w not in LEGAL_FORMS]
    return " ".join(parts)


def amount_key(value: float, cents: bool = True) -> int:
    """Amount in minor units, so float noise never decides a match."""
    return round(value * 100) if cents else round(value)


def digits(raw: str) -> str:
    """Just the digits of an invoice number. Catches `A-4471` against `4471/B`,
    where the alphabetic prefix differs because two clerks typed it differently."""
    return re.sub(r"\D", "", raw).lstrip("0")
