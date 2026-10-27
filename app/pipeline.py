"""Stages, in order. This is the diagram in the post."""
from __future__ import annotations

import os

from .detect import Candidate, Payment, oversized, scan
from .judge import claude_judge, in_band, wants_model

MAX_JUDGE = int(os.environ.get("DUPE_MAX_JUDGE", 50))

#: Only a person files a claim, and only a person dismisses one.
def tray(score: float, verdict: str | None) -> str:
    """The model can move a pair DOWN out of the claim tray, into review. It can
    never move one to `dismissed`, and it can never promote one to `claim`.

    Dismissal is withheld on purpose. `vendor_name` and `invoice_no` are chosen
    by the supplier and are fed to the model as text. A supplier who writes
    instructions into their own vendor master name could otherwise talk the model
    into dismissing their own duplicate payments. Routing to `review` keeps the
    model's explanation, which is the useful part, and keeps the decision with a
    person, which is the part that has to stay.
    """
    if verdict == "likely_legitimate":
        return "review"
    if score >= 0.90:
        return "claim"
    if in_band(score):
        return "review"
    return "watch"


def run(payments: list[Payment]) -> dict:
    skipped = oversized(payments)
    cands, truncated = scan(payments)
    rows, sent = [], 0
    for c in cands:
        allow = wants_model(c.score) and sent < MAX_JUDGE
        got = claude_judge(c) if allow else None
        if allow:
            sent += 1
        verdict = got["verdict"] if got else None
        rows.append({
            "pattern": c.pattern, "score": c.score, "reason": c.reason,
            "exposure": c.exposure, "tray": tray(c.score, verdict),
            "verdict": verdict,
            "innocent_explanation": (got or {}).get("innocent_explanation"),
            "evidence_needed": (got or {}).get("evidence_needed"),
            "judged_by": "claude" if got else "rules",
            "a": c.a.doc_id, "b": c.b.doc_id,
            "vendor": c.a.vendor_name, "amount": c.a.amount, "currency": c.a.currency,
        })

    by_pattern: dict[str, dict] = {}
    for r in rows:
        p = by_pattern.setdefault(r["pattern"], {"pairs": 0, "exposure": 0.0})
        p["pairs"] += 1
        p["exposure"] = round(p["exposure"] + r["exposure"], 2)

    erp_blocked = sum(r["exposure"] for r in rows if r["pattern"] == "exact")
    beyond = sum(r["exposure"] for r in rows if r["pattern"] != "exact")
    claimable = sum(r["exposure"] for r in rows if r["tray"] == "claim")
    spend = round(sum(abs(p.amount) for p in payments), 2)
    return {
        "summary": {
            "payments": len(payments),
            "spend": spend,
            "pairs": len(rows),
            # The headline. Exact duplicates are what an ERP already stops.
            "exposure_erp_would_catch": round(erp_blocked, 2),
            "exposure_beyond_erp": round(beyond, 2),
            "beyond_erp_share": round(beyond / (erp_blocked + beyond), 4) if (erp_blocked + beyond) else 0.0,
            "claim_tray": round(claimable, 2),
            "claim_as_share_of_spend": round(claimable / spend, 5) if spend else 0.0,
            "sent_to_model": sent,
            # Blocks too large to scan. Not a clean run: these need splitting by
            # vendor or date before the number above means anything.
            "skipped_blocks": [{"currency": c, "amount_minor": a, "payments": n}
                               for c, a, n in skipped],
            # True means the scan stopped early. Every number above is a floor,
            # not a total, and a zero in this report is not a real zero.
            "truncated": truncated,
            "complete": not truncated and not skipped,
        },
        "by_pattern": by_pattern,
        "pairs": rows,
    }
