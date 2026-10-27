"""Canonical forms. If these are wrong, every later stage is wrong."""
import pytest

from app.normalize import amount_key, digits, invoice_key, vendor_key


@pytest.mark.parametrize("raw", ["INV-0012", "inv 12", "INV0012", "inv/12", "Inv_0012", "  INV-0012  "])
def test_every_way_a_clerk_types_one_invoice_number_collapses_to_one_key(raw):
    assert invoice_key(raw) == "inv12"


def test_leading_zeros_only_go_from_the_trailing_number():
    assert invoice_key("0012") == "12"
    assert invoice_key("INV-007-A") == invoice_key("inv007a")   # not a pure numeric suffix


def test_two_different_invoices_do_not_collide():
    assert invoice_key("INV-12") != invoice_key("INV-13")
    assert invoice_key("A-4471") != invoice_key("B-4471")


@pytest.mark.parametrize("a,b", [
    ("Thermo Scientific India Pvt Ltd", "Thermo Scientific India Limited"),
    ("Acme Co.", "ACME Company"),
    ("Sartorius Lab Supplies Ltd", "sartorius lab supplies"),
])
def test_legal_form_does_not_change_who_the_supplier_is(a, b):
    assert vendor_key(a) == vendor_key(b)


def test_different_suppliers_stay_different():
    assert vendor_key("Merck Life Science") != vendor_key("Merck KGaA Chemicals")


def test_amounts_compare_in_minor_units_so_float_noise_never_decides():
    assert amount_key(0.1 + 0.2) == amount_key(0.3)
    assert amount_key(128000.00) == 12800000


def test_digits_only_strips_prefixes_and_leading_zeros():
    assert digits("A-4471") == digits("4471/B") == "4471"
    assert digits("INV-0012") == "12"
    assert digits("ABC") == ""
