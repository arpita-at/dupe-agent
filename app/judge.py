"""The only place a model is used.

It never decides that a payment is a duplicate. It reads one candidate pair in
the band where the rules are genuinely unsure, and answers one question: is
there an innocent explanation?

That framing is deliberate. A model asked "is this a duplicate?" will find
duplicates, because that is what it was asked for. A model asked "what would
make this legitimate?" surfaces the recurring monthly retainer, the deposit and
balance on one order, and the genuine resubmission after a credit note. Those
are the false positives that cost a vendor relationship.
"""
from __future__ import annotations

import json
import os

from .detect import Candidate

MODEL = os.environ.get("DUPE_MODEL", "claude-sonnet-5-5")

#: Below this the rules are too weak to act on at all, above it they are strong
#: enough that a model adds nothing. Only the middle band is worth a call.
BAND = (0.50, 0.90)

SYSTEM = """You review one pair of supplier payments that a deterministic rule
flagged as a possible duplicate.

Your job is NOT to confirm the duplicate. It is to find the innocent explanation
if one exists. Argue against the flag.

Common legitimate reasons two payments look identical:
- A recurring charge with the same amount every period (rent, retainer, licence)
- A deposit and a balance of equal value on one order
- A genuine reissue after a credit note or a failed payment
- Two real invoices from one supplier that happen to match in value
- Staged milestone billing at equal values

Answer as JSON only:
{"verdict": "likely_duplicate|likely_legitimate|unclear",
 "innocent_explanation": "<the best one, or null>",
 "evidence_needed": "<the one document that would settle it>",
 "confidence": "high|medium|low"}

Rules:
- Use only the fields given. Do not assume facts about the supplier.
- "unclear" is a correct answer. Prefer it over a confident guess.
- Never recommend recovering, clawing back or contacting the supplier. A claim
  is a human decision.
- Plain English. No em dashes.
"""


def _payload(c: Candidate) -> dict:
    def side(p):
        return {"doc": p.doc_id, "vendor_id": p.vendor_id, "vendor": p.vendor_name,
                "invoice_no": p.invoice_no, "amount": p.amount, "currency": p.currency,
                "invoice_date": p.invoice_date.isoformat(), "paid_on": p.paid_on.isoformat(),
                "company_code": p.company_code, "po": p.po or None, "source": p.source}
    return {"pattern": c.pattern, "rule_reason": c.reason, "rule_score": c.score,
            "a": side(c.a), "b": side(c.b),
            "days_between_payments": abs((c.a.paid_on - c.b.paid_on).days)}


def claude_judge(c: Candidate) -> dict | None:
    """Parsed verdict, or None on any failure. Fails closed to the rule score."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        return None
    try:
        msg = Anthropic(api_key=key).messages.create(
            model=MODEL, max_tokens=320, system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(_payload(c), indent=2)}],
        )
        raw = "".join(b.text for b in msg.content if b.type == "text").strip()
        got = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except Exception:
        return None
    if got.get("verdict") not in {"likely_duplicate", "likely_legitimate", "unclear"}:
        return None
    return got


def in_band(score: float) -> bool:
    return BAND[0] <= score < BAND[1]


def model_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def wants_model(score: float) -> bool:
    return in_band(score) and model_available()
