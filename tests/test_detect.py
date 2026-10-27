"""The six patterns. Each one is a duplicate an ERP's own check lets through."""
from datetime import date

import pytest

from app.detect import Payment, blocks, candidates
from app.judge import in_band


def p(doc, vid, name, inv, amt, paid, cc="IN01", po="", cur="INR", inv_date="2026-01-01"):
    return Payment(doc, vid, name, inv, amt, cur, date.fromisoformat(inv_date),
                   date.fromisoformat(paid), cc, po, "PO" if po else "non-PO")


def only(ps):
    c = candidates(ps)
    assert len(c) == 1, [x.pattern for x in c]
    return c[0]


def test_exact_duplicate_is_what_the_erp_already_blocks():
    c = only([p("1", "V1", "Acme", "INV-12", 100.0, "2026-01-05", po="PO1"),
              p("2", "V1", "Acme", "INV-12", 100.0, "2026-01-06", po="PO1")])
    assert c.pattern == "exact"
    assert c.score >= 0.95


def test_formatting_variance_survives_the_erp_check():
    """INV-0012 and inv 12 are different strings. The check passes. It gets paid twice."""
    c = only([p("1", "V1", "Acme", "INV-0012", 128000.0, "2026-04-18", po="PO1"),
              p("2", "V1", "Acme", "inv 12", 128000.0, "2026-05-27")])
    assert c.pattern == "normalised_invoice"
    assert c.exposure == 128000.0


def test_one_supplier_under_two_vendor_ids_fires_no_check_at_all():
    c = only([p("1", "V1", "Thermo Scientific India Pvt Ltd", "TS-41209", 964000.0, "2026-05-14", po="PO1"),
              p("2", "V2", "Thermo Scientific India Limited", "TS41209", 964000.0, "2026-07-03")])
    assert c.pattern == "duplicate_vendor_master"


def test_same_invoice_paid_from_two_company_codes():
    c = only([p("1", "V1", "Merck Life Science", "MK-55820", 744000.0, "2026-06-14", cc="IN01"),
              p("2", "V2", "Merck Life Science", "MK-55820", 744000.0, "2026-08-01", cc="SG01")])
    assert c.pattern == "cross_entity"


def test_paid_once_on_the_po_and_once_as_a_non_po_invoice():
    """Three-way match cannot stop this: only one of the two ever had a PO."""
    c = only([p("1", "V1", "Acme", "AB-1", 5000.0, "2026-01-05", po="PO1"),
              p("2", "V1", "Acme", "CD-2", 5000.0, "2026-02-05")])
    assert c.pattern == "po_and_non_po"


def test_shared_digits_score_into_the_band_a_human_reads():
    c = only([p("1", "V1", "Agilent", "A-4471", 412800.0, "2026-03-11", po="PO1"),
              p("2", "V1", "Agilent", "4471/B", 412800.0, "2026-06-19")])
    assert c.pattern == "digits_only"
    assert in_band(c.score), "weakest signal must land in the review band, not the claim tray"


def test_different_amounts_are_never_a_candidate():
    assert candidates([p("1", "V1", "Acme", "INV-12", 100.0, "2026-01-05"),
                       p("2", "V1", "Acme", "INV-12", 100.01, "2026-01-06")]) == []


def test_different_currencies_are_never_a_candidate():
    """Two payments of 100 in different currencies are not the same money."""
    assert candidates([p("1", "V1", "Acme", "INV-12", 100.0, "2026-01-05", cur="USD"),
                       p("2", "V1", "Acme", "INV-12", 100.0, "2026-01-06", cur="EUR")]) == []


def test_a_recurring_charge_of_equal_value_is_not_flagged():
    """Rent every month, same amount, different invoice numbers. The commonest
    false positive in every duplicate-payment tool, and it must not reach a claim."""
    assert candidates([p("1", "V1", "Labcon", "RENT-0126", 95000.0, "2026-01-05"),
                       p("2", "V1", "Labcon", "RENT-0226", 95000.0, "2026-02-05")]) == []


def test_sequential_invoice_numbers_of_equal_value_are_not_flagged():
    assert candidates([p("1", "V1", "Qiagen", "QG-20114", 540000.0, "2026-02-27", po="PO1"),
                       p("2", "V1", "Qiagen", "QG-20115", 540000.0, "2026-03-27", po="PO1")]) == []


def test_exposure_is_the_smaller_side_because_one_payment_was_legitimate():
    c = only([p("1", "V1", "Acme", "INV-0012", 100.0, "2026-01-05", po="PO1"),
              p("2", "V1", "Acme", "inv 12", 100.0, "2026-02-05")])
    assert c.exposure == 100.0


def test_blocking_never_hides_a_real_candidate():
    """Every pattern requires an exact amount match, so blocking on amount is
    safe. If a pattern ever stops requiring it, this test must fail."""
    import app.detect as d
    ps = [p("1", "V1", "Acme", "INV-0012", 100.0, "2026-01-05", po="PO1"),
          p("2", "V1", "Acme", "inv 12", 100.0, "2026-02-05"),
          p("3", "V1", "Acme", "ZZ-9", 999.0, "2026-03-05")]
    assert sum(len(b) for b in blocks(ps)) == 2       # the odd amount is dropped
    assert len(d.candidates(ps)) == 1


def test_only_the_strongest_pattern_is_reported_per_pair():
    c = candidates([p("1", "V1", "Acme", "INV-12", 100.0, "2026-01-05", po="PO1"),
                    p("2", "V1", "Acme", "INV-12", 100.0, "2026-01-06")])
    assert len(c) == 1 and c[0].pattern == "exact"


def test_two_vendor_ids_across_two_entities_route_to_the_entities_not_master_data():
    """A supplier legitimately has one vendor record per company code, so the
    entity split is the useful signal, not the duplicate ID."""
    c = only([p("1", "V1", "Merck Life Science", "MK-55820", 744000.0, "2026-06-14", cc="IN01"),
              p("2", "V2", "Merck Life Science", "MK-55820", 744000.0, "2026-08-01", cc="SG01")])
    assert c.pattern == "cross_entity"


def test_two_vendor_ids_inside_one_entity_is_master_data_gone_wrong():
    c = only([p("1", "V1", "Thermo Scientific India Pvt Ltd", "TS-41209", 964000.0, "2026-05-14", cc="IN01", po="PO1"),
              p("2", "V2", "Thermo Scientific India Limited", "TS41209", 964000.0, "2026-07-03", cc="IN01")])
    assert c.pattern == "duplicate_vendor_master"


def test_an_identical_pair_across_two_entities_is_not_called_exact():
    """An ERP duplicate check is scoped to the company code, so it never sees
    this pair. Reporting it as `exact` would overstate what the ERP catches."""
    c = only([p("1", "V1", "Merck", "MK-55820", 744000.0, "2026-06-14", cc="IN01"),
              p("2", "V1", "Merck", "MK-55820", 744000.0, "2026-08-01", cc="SG01")])
    assert c.pattern == "cross_entity"


def test_one_huge_block_is_reported_not_scanned():
    """50,000 payments of the same amount would be 1.2 billion pairs. The block is
    skipped and reported, never silently dropped: a block that size is itself a
    finding and hiding it would understate exposure."""
    import app.detect as d
    ps = [p(str(i), "V1", "Acme", f"INV-{i}", 1000.0, "2026-01-05") for i in range(d.MAX_BLOCK + 5)]
    assert d.oversized(ps) == [("INR", 100000, d.MAX_BLOCK + 5)]
    assert d.candidates(ps) == []


def test_a_normal_sized_block_is_still_scanned():
    import app.detect as d
    ps = [p("1", "V1", "Acme", "INV-0012", 1000.0, "2026-01-05", po="PO1"),
          p("2", "V1", "Acme", "inv 12", 1000.0, "2026-02-05")]
    assert d.oversized(ps) == []
    assert len(d.candidates(ps)) == 1
