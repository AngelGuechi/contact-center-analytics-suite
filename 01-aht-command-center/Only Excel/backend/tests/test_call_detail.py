"""Reading the call-detail export: hand-made text rows, a real .xlsx, the shared sample."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import polars as pl
import pytest
import xlsxwriter

from aht_pipeline import call_detail


def raw(**overrides) -> pl.DataFrame:
    """Two calls and one U0 call, as `read_raw` hands them over: text, our names."""
    base = {
        "transaction_id": ["TXN1", "TXN2", "TXN3"],
        "login_id": [" U200001 ", "U200002", "U0"],
        "call_started_at": ["2026-08-14T09:30:00"] * 3,
        "talk_seconds": ["502", "0", "10"],
        "hold_seconds": ["10", "48", "0"],
        "wrap_seconds": ["153", "175", "0"],
    }
    base.update(overrides)
    return pl.DataFrame(base, schema={k: pl.String for k in base})


def test_u0_is_dropped_and_counted_and_logins_are_trimmed():
    result = call_detail.clean(raw())
    assert result.excluded_unknown_login == 1
    assert result.calls["login_id"].to_list() == ["U200001", "U200002"]


def test_start_time_is_read_in_cdmx_time_and_stored_in_utc():
    calls = call_detail.clean(raw()).calls
    assert calls.schema["call_started_at"] == pl.Datetime("us", "UTC")
    assert calls["call_started_at"][0] == datetime(2026, 8, 14, 15, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("502", 502),
        ("502.0", 502),
        ("8:22", 502),
        ("0:08:22", 502),
        ("1:00:36", 3636),
        ("1899-12-31 00:08:22", 502),  # an Excel time cell, read as text
        ("1899-12-31 00:08:21.9996", 502),
    ],
)
def test_duration_formats_become_whole_seconds(text, seconds):
    calls = call_detail.clean(raw(talk_seconds=[text, "0", "0"])).calls
    assert calls["talk_seconds"][0] == seconds


@pytest.mark.parametrize(
    "text", ["21.57", "0.0058", "N/A", "--", "-5", "1900-01-01 01:00:00"]
)
def test_an_ambiguous_or_unreadable_duration_is_rejected_with_its_value(text):
    expected = rf"unreadable values in hold_seconds \(1: {re.escape(text)}\)"
    with pytest.raises(ValueError, match=expected):
        call_detail.clean(raw(hold_seconds=[text, "0", "0"]))


@pytest.mark.parametrize(
    ("text", "utc"),
    [
        ("2026-08-14 09:30:00", datetime(2026, 8, 14, 15, 30, tzinfo=UTC)),
        ("2026-08-14T23:30:00.5", datetime(2026, 8, 15, 5, 30, 0, 500000, tzinfo=UTC)),
    ],
)
def test_start_time_formats(text, utc):
    calls = call_detail.clean(raw(call_started_at=[text] * 3)).calls
    assert calls["call_started_at"][0] == utc


@pytest.mark.parametrize("text", ["08/14/2026 9:30", "2026-08-14"])
def test_an_unreadable_start_time_is_rejected(text):
    with pytest.raises(ValueError, match=r"unreadable values in call_started_at"):
        call_detail.clean(raw(call_started_at=[text] * 3))


def test_a_u0_call_is_not_checked():
    calls = call_detail.clean(raw(talk_seconds=["502", "0", "N/A"])).calls
    assert calls.height == 2


def test_blank_cells_are_rejected_with_counts():
    with pytest.raises(ValueError, match=r"blank cells in wrap_seconds \(1\)"):
        call_detail.clean(raw(wrap_seconds=["153", "  ", "0"]))


def test_a_blank_login_is_rejected():
    with pytest.raises(ValueError, match="1 calls have a blank login_id"):
        call_detail.clean(raw(login_id=["U200001", None, "U0"]))


def test_a_repeated_call_is_rejected():
    with pytest.raises(ValueError, match="transaction_id repeated: TXN1"):
        call_detail.clean(raw(transaction_id=["TXN1", "TXN1", "TXN3"]))


# ---------------------------------------------------------------- a real .xlsx
def write_xlsx(path, talk_cells) -> None:
    """Headers in another case and order, an extra column, and Excel-native cells."""
    wb = xlsxwriter.Workbook(path)
    ws = wb.add_worksheet()
    when = wb.add_format({"num_format": "yyyy-mm-dd hh:mm:ss"})
    clock = wb.add_format({"num_format": "hh:mm:ss"})
    elapsed = wb.add_format({"num_format": "[h]:mm:ss"})
    ws.write_row(0, 0, ["login id", "Transaction ID", "Queue", "START DATE TIME"])
    ws.write_row(0, 4, ["Talk Time", "Hold Time", "Wrap Time"])
    for r, talk in enumerate(talk_cells, start=1):
        ws.write_row(r, 0, [f"U20000{r}", f"TXN{r}", "BILLING"])
        ws.write_datetime(r, 3, datetime(2026, 8, 14, 9, r), when)
        if isinstance(talk, str):
            ws.write_string(r, 4, talk)
        else:
            ws.write_number(r, 4, talk)
        ws.write_number(r, 5, 48 / 86400, clock)  # 00:00:48 as a time of day
        ws.write_number(r, 6, 3636 / 86400, elapsed)  # 1:00:36 as elapsed time
    wb.close()


def test_an_xlsx_export_with_native_excel_cells(tmp_path):
    path = tmp_path / "export.xlsx"
    write_xlsx(path, [502, 120, "0:01:00"])
    calls = call_detail.read_call_detail(path).calls
    assert calls["talk_seconds"].to_list() == [502, 120, 60]
    assert calls["hold_seconds"].to_list() == [48] * 3
    assert calls["wrap_seconds"].to_list() == [3636] * 3
    assert calls["call_started_at"][0] == datetime(2026, 8, 14, 15, 1, tzinfo=UTC)


def test_a_stray_word_in_a_number_column_is_never_read_as_blank(tmp_path):
    path = tmp_path / "export.xlsx"
    write_xlsx(path, [502, 120, "N/A", 60])
    with pytest.raises(ValueError, match=r"talk_seconds \(1: N/A\)"):
        call_detail.read_call_detail(path)


# ---------------------------------------------------------------- shared sample
def test_the_shared_sample():
    result = call_detail.read_call_detail()
    assert (result.calls.height, result.excluded_unknown_login) == (12426, 74)
    assert result.calls.schema == pl.Schema(
        {
            "transaction_id": pl.String,
            "login_id": pl.String,
            "call_started_at": pl.Datetime("us", "UTC"),
            "talk_seconds": pl.Int64,
            "hold_seconds": pl.Int64,
            "wrap_seconds": pl.Int64,
        }
    )
