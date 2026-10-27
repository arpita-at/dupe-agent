"""Candidate generation and scoring. Deterministic. No model is called here.

Six patterns, each one a duplicate an ERP's own check does not stop. Each
returns a score between 0 and 1 and a reason. The scores are deliberately
conservative: this tool produces a claim file a person works, and a false
positive costs a vendor relationship.
"""
from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from itertools import combinations

from .normalize import amount_key, digits, invoice_key, vendor_key


@dataclass(frozen=True)
class Payment:
    doc_id: str
    vendor_id: str
    vendor_name: str
    invoice_no: str
    amount: float
    currency: str
    invoice_date: date
    paid_on: date
    company_code: str
    po: str          # empty string means a non-PO invoice
    source: str      # "PO" | "non-PO" | "manual"


@dataclass(frozen=True)
class Candidate:
    a: Payment
    b: Payment
    pattern: str
    score: float
    reason: str

    @property
    def exposure(self) -> float:
        """What a successful claim would recover. The smaller of the pair, since
        one of the two was a legitimate payment."""
        return round(min(abs(self.a.amount), abs(self.b.amount)), 2)


def _same_amount(a: Payment, b: Payment) -> bool:
    return a.currency == b.currency and amount_key(a.amount) == amount_key(b.amount)


def _days(a: Payment, b: Payment) -> int:
    return abs((a.paid_on - b.paid_on).days)


# Each rule returns (score, reason) or None.
def _exact(a: Payment, b: Payment):
    """What the ERP already blocks. Included so the report can show how little
    of the total sits here.

    Scoped to one company code, because an ERP's duplicate check is. A pair
    spanning two entities is never caught by it, however identical it looks,
    so calling that one `exact` would overstate what the ERP is doing for you.
    """
    if (a.company_code == b.company_code and a.vendor_id == b.vendor_id
            and a.invoice_no == b.invoice_no and _same_amount(a, b)):
        return 0.99, "Same vendor, same invoice number as stored, same amount"
    return None


def _normalised_invoice(a: Payment, b: Payment):
    """`INV-0012` against `inv 12`. Different strings, same invoice."""
    if (a.vendor_id == b.vendor_id and _same_amount(a, b)
            and a.invoice_no != b.invoice_no
            and invoice_key(a.invoice_no) == invoice_key(b.invoice_no)):
        return 0.95, f"Invoice numbers differ only by formatting ({a.invoice_no} vs {b.invoice_no})"
    return None


def _duplicate_vendor_master(a: Payment, b: Payment):
    """One invoice billed to two vendor records inside one company code.

    Scoped to a single entity on purpose. A supplier legitimately has a separate
    vendor record per company code, so two IDs across two entities is normal and
    is `cross_entity` instead. Two IDs inside one entity is master data gone
    wrong, and it fires no duplicate check at all, because to the ERP these are
    two different suppliers.
    """
    if (a.company_code == b.company_code
            and a.vendor_id != b.vendor_id
            and vendor_key(a.vendor_name) == vendor_key(b.vendor_name)
            and _same_amount(a, b)
            and invoice_key(a.invoice_no) == invoice_key(b.invoice_no)):
        return 0.92, f"Same supplier under two vendor IDs ({a.vendor_id} and {b.vendor_id})"
    return None


def _po_and_non_po(a: Payment, b: Payment):
    """Paid once against the PO, once as a non-PO invoice. Classic, and it
    survives three-way match because only one side ever had a PO."""
    if (a.vendor_id == b.vendor_id and _same_amount(a, b)
            and bool(a.po) != bool(b.po) and _days(a, b) <= 90):
        return 0.80, "Paid once against a PO and once as a non-PO invoice"
    return None


def _cross_entity(a: Payment, b: Payment):
    """Same invoice paid out of two company codes. Common after a migration or
    an acquisition, and invisible to any check scoped to one entity."""
    if (a.company_code != b.company_code
            and vendor_key(a.vendor_name) == vendor_key(b.vendor_name)
            and _same_amount(a, b)
            and invoice_key(a.invoice_no) == invoice_key(b.invoice_no)):
        return 0.85, f"Same invoice paid from {a.company_code} and {b.company_code}"
    return None


def _digits_only(a: Payment, b: Payment):
    """`A-4471` against `4471/B`: two clerks, two prefixes, one invoice. The
    weakest signal here, so it scores into the band a human reads."""
    if (a.vendor_id == b.vendor_id and _same_amount(a, b)
            and invoice_key(a.invoice_no) != invoice_key(b.invoice_no)
            and digits(a.invoice_no) and digits(a.invoice_no) == digits(b.invoice_no)
            and _days(a, b) <= 180):
        return 0.55, f"Invoice numbers share their digits ({a.invoice_no} vs {b.invoice_no})"
    return None


RULES = [
    ("exact", _exact),
    ("normalised_invoice", _normalised_invoice),
    # cross_entity first: a pair spanning two company codes almost always also
    # spans two vendor IDs, and the entity split is the more useful routing.
    ("cross_entity", _cross_entity),
    ("duplicate_vendor_master", _duplicate_vendor_master),
    ("po_and_non_po", _po_and_non_po),
    ("digits_only", _digits_only),
]


def blocks(payments: list[Payment]) -> list[list[Payment]]:
    """Group payments so we never compare every row against every other row.

    Blocking on the amount in minor units plus currency is safe here: every
    pattern above requires the amounts to match exactly, so two payments in
    different blocks can never be a candidate. It turns an O(n squared) scan
    into something that runs on a full year of AP.
    """
    buckets: dict[tuple[str, int], list[Payment]] = defaultdict(list)
    for p in payments:
        buckets[(p.currency, amount_key(p.amount))].append(p)
    return [v for v in buckets.values() if len(v) > 1]


#: A block is every payment sharing one currency and amount. Normally tiny. A
#: ledger with 50,000 payments of exactly 1,000.00 would produce 1.2 billion
#: pairs from one block, so both the block and the total pair count are capped.
MAX_BLOCK = int(os.environ.get("DUPE_MAX_BLOCK", 2_000))
MAX_PAIRS = int(os.environ.get("DUPE_MAX_PAIRS", 500_000))


def oversized(payments: list[Payment]) -> list[tuple[str, int, int]]:
    """Blocks too large to scan, as (currency, minor units, size). Reported rather
    than silently truncated: a block of 50,000 identical amounts is itself a
    finding, and quietly dropping it would hide exposure."""
    return [(b[0].currency, amount_key(b[0].amount), len(b))
            for b in blocks(payments) if len(b) > MAX_BLOCK]


def scan(payments: list[Payment]) -> tuple[list[Candidate], bool]:
    """Every scored pair, strongest pattern per pair, and whether the scan was
    cut short.

    The budget counts **comparisons made**, not candidates found. Counting
    candidates would never stop a ledger of 2,000 near-identical payments that
    happen to match no rule: a couple of million comparisons, an empty result,
    and a cap that never fires.

    Truncation is returned, not swallowed. A partial scan reported as a complete
    one is worse than no scan, because the zero you read is not a real zero.
    """
    out: list[Candidate] = []
    seen = 0
    truncated = False
    for block in blocks(payments):
        if len(block) > MAX_BLOCK:
            continue        # reported by oversized(), never silently merged in
        for a, b in combinations(sorted(block, key=lambda p: p.paid_on), 2):
            if seen >= MAX_PAIRS:
                truncated = True
                break
            seen += 1
            for name, rule in RULES:
                hit = rule(a, b)
                if hit:
                    score, reason = hit
                    out.append(Candidate(a, b, name, score, reason))
                    break
        if truncated:
            break
    return sorted(out, key=lambda c: (-c.score, -c.exposure)), truncated


def candidates(payments: list[Payment]) -> list[Candidate]:
    """Candidates only. Use scan() where the truncation flag matters."""
    return scan(payments)[0]
