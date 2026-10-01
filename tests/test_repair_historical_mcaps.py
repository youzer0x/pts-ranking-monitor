from copy import deepcopy

import pytest

from repair_historical_mcaps import repair


def test_split_correction_preserves_historical_ranking():
    data = {"session_date": "2026-09-30", "rows": [{
        "code": "8766", "mcap_oku": 10395, "shoutfy_jq": 1934000000,
        "cur_end": "2027-03-31", "corr": 1, "mcap_flag": "†",
        "close": 537.5, "rank": 9, "factor": "original", "name": "東京海上"}],
        "counts": {"published": 1}}
    original = deepcopy(data)
    fixed, audit = repair(data, [{"Date": "2026-09-30", "Code": "87660",
                                 "MktCap": 15318702.0}], "2026-10-01")
    assert data == original
    row = fixed["rows"][0]
    assert row["mcap_oku"] == 153187
    assert row["mcap_source"] == "jquants"
    assert "mcap_flag" not in row and "cur_end" not in row
    assert {k: row[k] for k in ("close", "rank", "factor", "name")} == {
        k: original["rows"][0][k] for k in ("close", "rank", "factor", "name")}
    assert fixed["counts"] == original["counts"]
    assert fixed["mcap_revision"]["original_selection_preserved"]
    assert audit[0]["before"]["mcap_oku"] == 10395


@pytest.mark.parametrize("values", [[], [{"Date": "2026-09-29", "Code": "87660", "MktCap": 100}],
    [{"Date": "2026-09-30", "Code": "87660", "MktCap": -1}]])
def test_no_stale_or_missing_fallback(values):
    with pytest.raises(ValueError):
        repair({"session_date": "2026-09-30", "rows": [{"code": "8766", "mcap_oku": 10395}]},
               values, "2026-10-01")


def test_missing_historical_value_is_not_replaced_with_current_price():
    fixed, audit = repair({"session_date": "2026-09-30", "rows": [
        {"code": "8766", "mcap_oku": 10395}]},
        [{"Date": "2026-09-30", "Code": "87660", "MktCap": None}], "2026-10-01")
    assert fixed["rows"][0]["mcap_oku"] is None
    assert fixed["rows"][0]["mcap_source"] == "unavailable"
    assert audit[0]["before"]["mcap_oku"] == 10395


def test_historical_description_and_trillion_display():
    from html_generator import mcap_description, fmt_mcap_cell
    assert fmt_mcap_cell({"mcap_oku": 153187}) == "15.3兆円"
    data = {"criteria": {"mcap_method": "jquants_valuation"},
            "mcap_revision": {"original_selection_preserved": True}}
    assert "当初の抽出結果を保持" in mcap_description(data)
