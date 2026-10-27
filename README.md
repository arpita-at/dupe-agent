# dupe-agent

**dupe-agent finds duplicate supplier payments that your ERP's own duplicate check does not stop.** It normalises invoice numbers and vendor names, scores six near-duplicate patterns deterministically, and asks a model one question only: is there an innocent explanation? The output is a claim file a person works. It recovers nothing by itself.

Sample data is synthetic. There are no real suppliers or payments in this repo.

```
AP payment ledger (one year)
   │
   ├─► normalise          (rules)   invoice number, vendor name, amount in minor units
   ├─► block by amount    (rules)   turns an O(n²) scan into one that runs on a full year
   ├─► score six patterns (rules)   each one survives a standard ERP duplicate check
   ├─► argue against it   (claude)  only the 0.50–0.90 band, and only to find the innocent reason
   └─► claim / review / dismissed   (human)  nothing is recovered automatically
```

---

## How much money is this?

APQC's Open Standards Benchmarking puts duplicate or erroneous payments at **0.8% of annual disbursements for top performers and 2% for bottom performers**. On $1B of disbursements that is $8M to $20M a year.

Two caveats worth stating, because they get dropped everywhere else: that figure is a share of **disbursements**, and it includes **erroneous** payments, not only true duplicates. Anyone quoting it as "2% of spend is duplicate payments" is overstating it.

## The point: the duplicates your ERP blocks are not where the money is

SAP's standard check, and every other ERP's, compares vendor, invoice number, amount and date **as stored**, scoped to **one company code**. So it reliably stops the obvious case. What it never sees:

| # | Pattern | Why the ERP check misses it |
|---|---|---|
| 1 | `normalised_invoice` | `INV-0012` and `inv 12` are different strings |
| 2 | `duplicate_vendor_master` | Two vendor records in one entity, so to the ERP these are two different suppliers |
| 3 | `cross_entity` | The check is scoped to a company code and this pair spans two |
| 4 | `po_and_non_po` | Three-way match cannot fire, because only one of the two ever had a PO |
| 5 | `digits_only` | `A-4471` and `4471/B`: two clerks, two prefixes, one invoice |
| 6 | `exact` | It does catch this one. Included so the report shows how little sits here |

On the synthetic sample, **93.2% of the exposure is in patterns 1 to 5**:

| Pattern | Pairs | Exposure |
|---|---:|---:|
| `normalised_invoice` | 3 | 2,175,500 |
| `duplicate_vendor_master` | 1 | 964,000 |
| `cross_entity` | 1 | 744,000 |
| `digits_only` | 1 | 412,800 |
| `exact` (ERP would catch) | 1 | 312,500 |

## Why the model argues against the flag

A model asked *"is this a duplicate?"* will find duplicates, because that is what it was asked for. This one is asked *"what would make this legitimate?"*:

> Your job is NOT to confirm the duplicate. It is to find the innocent explanation if one exists. Argue against the flag.

That framing surfaces the recurring monthly retainer, the deposit and balance of equal value on one order, and the genuine reissue after a credit note. Those are the false positives that cost a supplier relationship, and they are what makes a duplicate-payment report get ignored after the second bad claim.

The model can only ever argue a flag **down**. It never promotes one past what the rules found:

```python
def test_a_legitimate_verdict_dismisses_even_a_high_rule_score():
    assert tray(0.95, "likely_legitimate") == "dismissed"
    assert tray(0.95, None) == "claim"
```

It is called only in the **0.50 to 0.90** band. Below that the rules are too weak to act on; above it they are strong enough that a model adds nothing.

## What is deliberately never flagged

The two commonest false positives in every duplicate-payment tool, both tested:

- **A recurring charge of equal value.** Rent, retainer or licence, same amount every month, different invoice numbers.
- **Sequential invoice numbers of equal value.** `QG-20114` and `QG-20115` are two real invoices that happen to match.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000     # then open http://127.0.0.1:8000
pytest -q                                      # 43 passed
```

Optional, for the innocent-explanation pass: `export ANTHROPIC_API_KEY=sk-ant-...`

## Input format

Export paid AP documents to CSV:

```
doc_id,vendor_id,vendor_name,invoice_no,amount,currency,invoice_date,paid_on,company_code,po,source
```

Leave `po` empty for a non-PO invoice. Amounts compare in minor units, so float noise never decides a match.

## FAQ

**Does this touch SAP or my bank?** No. It reads a CSV export and returns a report. There is no connector and nothing initiates, reverses or claws back a payment.

**Why not let a model find the duplicates?** Because matching is arithmetic and string normalisation, and both are testable. A model right 99% of the time, on a year of AP, produces hundreds of wrong claims against real suppliers.

**Why block on amount?** Every pattern requires an exact amount match, so two payments in different amount blocks can never be a candidate. That is what makes a full year of AP scannable instead of O(n²). There is a test asserting blocking never hides a real candidate, and it must fail if a pattern ever stops requiring the amount.

**How do I use the output?** Three trays. `claim` is strong enough to raise with the supplier. `review` is a human read. `dismissed` is where the model found an innocent explanation. Work the claim tray by exposure, largest first.

**Deploying it?** Set `DUPE_API_TOKEN` and send `Authorization: Bearer <token>`. The input is a full AP ledger, which is commercially sensitive on its own. Limits: `DUPE_MAX_BYTES` (8 MB), `DUPE_MAX_ROWS` (100,000), `DUPE_MAX_JUDGE` (50 model calls per run).

## Licence

Apache-2.0.

---

Built by [Arpita Tiwari](https://www.linkedin.com/in/arpita-tiwari-5b955a307). FP&A and record to report by day, agents for finance workflows in my own time. Tell me where the logic breaks.
