"""Unit conversions: kg/g, litres/ml, pieces, packets, cartons (1 CTN = 20 PKT)."""
from decimal import Decimal

import pytest

from app.core.errors import BusinessRuleError
from app.models import UnitConversion
from app.services.units import convert
from tests.factories import benchmark_materials, unit


@pytest.fixture
def mats(db):
    return benchmark_materials(db)


def c(db, qty, frm, to, item=None):
    return convert(db, Decimal(qty), unit(db, frm), unit(db, to), item.id if item else None)


@pytest.mark.parametrize(("qty", "frm", "to", "expected"), [
    ("40", "KG", "G", "40000"),
    ("1200", "G", "KG", "1.2"),
    ("10.5", "L", "ML", "10500"),
    ("10500", "ML", "L", "10.5"),
    ("0.001", "KG", "G", "1"),
    ("7", "KG", "KG", "7"),
])
def test_global_conversions(db, qty, frm, to, expected):
    assert c(db, qty, frm, to) == Decimal(expected)


def test_carton_of_20_packets_both_directions(db, mats):
    mur = mats["murukku"]
    assert c(db, "9", "CTN", "PKT", mur) == Decimal("180")
    assert c(db, "180", "PKT", "CTN", mur) == Decimal("9")
    # 188 good packets = 9.4 cartons: 9 full cartons + 8 loose packets (benchmark).
    assert c(db, "188", "PKT", "CTN", mur) == Decimal("9.4")


def test_item_specific_packing_does_not_leak_to_other_items(db, mats):
    with pytest.raises(BusinessRuleError, match="No conversion"):
        c(db, "1", "CTN", "PKT", mats["pouch"])  # pouches have no carton packing defined
    with pytest.raises(BusinessRuleError, match="No conversion"):
        c(db, "1", "CTN", "PKT")  # and there is no global CTN->PKT


def test_cross_dimension_refused_without_item_edge(db):
    with pytest.raises(BusinessRuleError, match="No conversion"):
        c(db, "1", "KG", "L")


def test_multi_hop_chain_via_item_and_global_edges(db, mats):
    mur = mats["murukku"]
    # 1 PKT = 200 G (item-specific); with 1 CTN = 20 PKT and global 1 KG = 1000 G:
    db.add(UnitConversion(from_unit_id=unit(db, "PKT").id, to_unit_id=unit(db, "G").id,
                          factor=Decimal("200"), item_id=mur.id))
    db.flush()
    assert c(db, "1", "CTN", "KG", mur) == Decimal("4")  # CTN -> PKT -> G -> KG


def test_inexact_conversion_is_refused_not_rounded(db, mats):
    pouch = mats["pouch"]
    db.add(UnitConversion(from_unit_id=unit(db, "CTN").id, to_unit_id=unit(db, "PCS").id,
                          factor=Decimal("3"), item_id=pouch.id))
    db.flush()
    assert c(db, "3", "PCS", "CTN", pouch) == Decimal("1")
    with pytest.raises(BusinessRuleError, match="cannot be expressed exactly"):
        c(db, "1", "PCS", "CTN", pouch)


def test_item_specific_overrides_global_for_same_pair(db, mats):
    flour = mats["flour"]
    # Silly but explicit: for this item "1 KG = 999 G" overrides the global 1000.
    db.add(UnitConversion(from_unit_id=unit(db, "KG").id, to_unit_id=unit(db, "G").id,
                          factor=Decimal("999"), item_id=flour.id))
    db.flush()
    assert c(db, "1", "KG", "G", flour) == Decimal("999")
    assert c(db, "1", "KG", "G") == Decimal("1000")
