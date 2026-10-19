from __future__ import annotations

import pytest

from nps_pipeline import catalog


def test_catalog_v1_has_23_drivers_in_the_four_buckets():
    assert len(catalog.DRIVERS) == 23
    assert {d.bucket for d in catalog.DRIVERS.values()} == set(catalog.BUCKETS)


def test_every_bucket_has_an_other_driver():
    others = {d.bucket for d in catalog.DRIVERS.values() if d.name == "Other"}
    assert others == set(catalog.BUCKETS)


def test_default_controllable_values_are_valid():
    values = {d.default_controllable for d in catalog.DRIVERS.values()}
    assert values <= set(catalog.CONTROLLABLE_VALUES)


def test_valid_label_passes():
    catalog.validate_label(
        "CUS_HIGH_BILL", "AGT_BILL_EXPLANATION", "negative", "partly"
    )
    catalog.validate_label("AGT_EMPATHY", None, "positive", "yes")


def test_invalid_label_names_every_problem():
    with pytest.raises(catalog.InvalidLabel) as e:
        catalog.validate_label("AGT_RUDE", "XYZ", "angry", "maybe")
    msg = str(e.value)
    for part in ("AGT_RUDE", "XYZ", "angry", "maybe"):
        assert part in msg
