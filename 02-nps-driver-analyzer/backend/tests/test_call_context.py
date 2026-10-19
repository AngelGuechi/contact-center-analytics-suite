"""The call context sidecar: exact call-type proportions, determinism, the file."""

from __future__ import annotations

import polars as pl
import pytest

from nps_pipeline import call_context


def test_call_type_counts_are_exact_and_sum_to_the_calls():
    # 12,426 valid calls: 28% is 3,479.28 -> 3,479; the remainders are all < 1
    assert call_context.call_type_counts(12_426) == {
        "Credit": 3479,
        "General Billing": 2982,
        "MIMO": 1988,
        "LPC": 1491,
        "NEM": 1243,
        "CBB": 1243,
    }
    for n in (0, 1, 7, 99, 12_426):
        assert sum(call_context.call_type_counts(n).values()) == n


def test_shares_must_add_up_to_100(monkeypatch):
    monkeypatch.setitem(call_context.CALL_TYPE_SHARES, "CBB", 5)
    with pytest.raises(ValueError, match="add up to 100"):
        call_context.call_type_counts(100)


def test_one_row_per_call_deterministic():
    ids = [f"TXN{i}" for i in range(1000)]
    context = call_context.build_call_context(ids)
    assert context["transaction_id"].to_list() == sorted(ids)
    assert context.equals(call_context.build_call_context(list(reversed(ids))))
    counts = dict(context["call_type"].value_counts().iter_rows())
    assert counts == call_context.call_type_counts(1000)


def test_ivr_time_follows_virtual_assistant_use():
    context = call_context.build_call_context([f"TXN{i}" for i in range(2000)])
    for va, (low, high) in call_context.IVR_SECONDS.items():
        ivr = context.filter(pl.col("virtual_assistant_used") == va)["ivr_seconds"]
        assert low <= ivr.min() and ivr.max() <= high
    share = (context["virtual_assistant_used"] == "Y").mean()
    assert 0.25 < share < 0.35


def test_build_rejects_repeated_calls():
    with pytest.raises(ValueError):
        call_context.build_call_context(["TXN1", "TXN1"])


def test_round_trip_and_bad_call_type(tmp_path):
    path = tmp_path / "call_context.csv"
    built = call_context.build_call_context([f"TXN{i}" for i in range(50)])
    call_context.write_call_context(built, path)
    assert call_context.read_call_context(path).equals(built)
    call_context.write_call_context(built.with_columns(call_type=pl.lit("Gas")), path)
    with pytest.raises(ValueError, match="call_type"):
        call_context.read_call_context(path)
