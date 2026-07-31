"""build_research_plan の圧縮・ルーティング・バッチ詰めのテスト。

ここで守っているのは「LLM に渡す量」そのもの。窓外ニュースの除去・prior の上限・
dropped_* の非混入が崩れると、バッチ化しても入力が膨らんで上限到達が再発する。
"""
import json

import pytest

from build_research_plan import (
    INITIAL_DISPATCH_LIMIT,
    PER_BATCH_DISPATCH_LIMIT,
    PRIOR_NEWS_LIMIT,
    TOTAL_DISPATCH_LIMIT,
    build_research_plan,
    compact_disclosures,
    compact_news,
    risk_reasons,
    window_for,
)

SESSION = "2026-07-09"
NEXT = "2026-07-10"

IN_WINDOW = f"{SESSION}T17:00"      # 引け後・窓内
PRE_WINDOW = f"{SESSION}T10:00"     # 日中＝織り込み済み
POST_WINDOW = f"{NEXT}T09:00"       # 翌日の寄り後＝当該セッションの材料ではない


def _news(stamp, title="見出し", category="材料", url=None):
    return {"datetime": stamp, "category": category, "title": title,
            "url": url or f"https://example.com/{title}"}


def _row(code, pct=5.0, turnover_m=100.0, disclosures=None, news=None, rank=1):
    return {
        "code": code, "name": f"銘柄{code}", "rank": rank, "pct": pct, "pts": 1000,
        "close": 950, "turnover_m": turnover_m, "mcap_oku": 500,
        # 調査に使わない Stage1 の内部フィールド。バッチへ漏れてはいけない。
        "volume": 12345, "shoutfy_jq": 999999, "corr": 1.0, "cur_end": "2026-03",
        "disclosures": disclosures or [], "kabutan_news": news or [],
        "factor": "", "factor_kind": "",
    }


def _ranking(rows):
    return {
        "session_date": SESSION, "next_date": NEXT, "rows": rows,
        "dropped_turnover": [{"code": "9999", "name": "薄商い銘柄"}],
        "dropped_mcap": [{"code": "8888", "name": "小型銘柄"}],
    }


def _disclosure(title, time="16:00", pdf="https://tdnet.example/1.pdf"):
    return {"time": time, "code": "1234", "name": "銘柄", "title": title, "pdf_url": pdf}


# --- 材料窓 ---------------------------------------------------------------

def test_window_is_session_1530_to_next_0600():
    start, end = window_for(_ranking([]))
    assert (start.hour, start.minute) == (15, 30)
    assert start.date().isoformat() == SESSION
    assert (end.hour, end.minute) == (6, 0)
    assert end.date().isoformat() == NEXT


def test_window_rejects_inverted_dates():
    with pytest.raises(ValueError):
        window_for({"session_date": NEXT, "next_date": SESSION, "rows": []})


# --- ニュース圧縮 ---------------------------------------------------------

def test_compact_news_buckets_by_window_and_drops_post_window():
    start, end = window_for(_ranking([]))
    row = _row("1234", news=[
        _news(IN_WINDOW, "窓内材料"),
        _news(PRE_WINDOW, "日中材料"),
        _news(POST_WINDOW, "翌日材料"),
    ])
    news, counts = compact_news(row, start, end)
    assert [i["title"] for i in news["material_window"]] == ["窓内材料"]
    assert [i["title"] for i in news["prior"]] == ["日中材料"]
    assert counts["post_window_omitted"] == 1


def test_compact_news_caps_prior_headlines():
    start, end = window_for(_ranking([]))
    row = _row("1234", news=[_news(PRE_WINDOW, f"古い材料{i}") for i in range(5)])
    news, counts = compact_news(row, start, end)
    assert len(news["prior"]) == PRIOR_NEWS_LIMIT
    assert counts["prior_retained"] == PRIOR_NEWS_LIMIT
    assert counts["prior_omitted_by_cap"] == 5 - PRIOR_NEWS_LIMIT


def test_compact_news_drops_tdnet_duplicates():
    start, end = window_for(_ranking([]))
    row = _row("1234", news=[
        _news(IN_WINDOW, "開示の焼き直し", category="開示"),
        _news(IN_WINDOW, "開示URL", url="https://kabutan.jp/disclosures/123"),
        _news(IN_WINDOW, "本物の材料"),
    ])
    news, counts = compact_news(row, start, end)
    assert [i["title"] for i in news["material_window"]] == ["本物の材料"]
    assert counts["tdnet_duplicates_omitted"] == 2


def test_compact_news_dedupes_identical_entries():
    start, end = window_for(_ranking([]))
    entry = _news(IN_WINDOW, "同じ材料")
    news, counts = compact_news(_row("1234", news=[entry, dict(entry)]), start, end)
    assert len(news["material_window"]) == 1
    assert counts["duplicates_omitted"] == 1


def test_compact_news_keeps_undated_headlines_as_prior():
    """時刻を解釈できない見出しは窓内と断定できないが、調査の手掛かりとして残す。"""
    start, end = window_for(_ranking([]))
    news, counts = compact_news(_row("1234", news=[_news("いつか", "壊れた時刻")]), start, end)
    assert counts["undated"] == 1
    assert [i["title"] for i in news["prior"]] == ["壊れた時刻"]
    assert news["material_window"] == []


# --- 開示圧縮 -------------------------------------------------------------

def test_compact_disclosures_dedupes_and_strips_redundant_fields():
    row = _row("1234", disclosures=[
        _disclosure("決算短信"),
        _disclosure("決算短信"),      # 同一 (title, pdf_url)
        _disclosure("業績予想の修正", pdf="https://tdnet.example/2.pdf"),
    ])
    items, omitted = compact_disclosures(row)
    assert [i["title"] for i in items] == ["決算短信", "業績予想の修正"]
    assert omitted == 1
    # code / name は item 側にあるので開示ごとに繰り返さない
    assert set(items[0]) == {"time", "title", "pdf_url"}


# --- リスク判定 -----------------------------------------------------------

@pytest.mark.parametrize("term", ["TOB", "公開買付", "完全子会社"])
def test_risk_reasons_flags_m_and_a(term):
    assert "m_and_a" in risk_reasons(_row("1234"), f"当社株式に対する{term}の開始")


def test_risk_reasons_flags_large_move_and_high_turnover():
    assert "large_move" in risk_reasons(_row("1234", pct=20.0), "")
    assert "high_turnover" in risk_reasons(_row("1234", turnover_m=50_000.0), "")
    assert risk_reasons(_row("1234", pct=5.0, turnover_m=100.0), "") == []


# --- ルーティング ---------------------------------------------------------

def test_normal_row_with_disclosure_is_inline_not_delegated():
    _, batches, inline = build_research_plan(
        _ranking([_row("1234", disclosures=[_disclosure("決算短信")])]))
    assert [i["code"] for i in inline] == ["1234"]
    assert batches == []


def test_high_risk_row_is_delegated_even_with_disclosure():
    """TOB 等は開示があっても EDINET の裏取りが要るので委譲側に回す。"""
    _, batches, inline = build_research_plan(
        _ranking([_row("1234", disclosures=[_disclosure("公開買付けの開始に関するお知らせ")])]))
    assert inline == []
    assert len(batches) == 1
    item = batches[0]["items"][0]
    assert item["risk"] == "high"
    assert item["requires_edinet"] is True


def test_row_without_material_is_routed_deep():
    _, batches, _ = build_research_plan(_ranking([_row("1234")]))
    assert batches[0]["items"][0]["route"] == "deep"


# --- バッチ詰め -----------------------------------------------------------

def test_normal_news_rows_pack_five_per_batch():
    rows = [_row(f"100{i}", news=[_news(IN_WINDOW, f"材料{i}")]) for i in range(7)]
    _, batches, _ = build_research_plan(_ranking(rows))
    assert [len(b["items"]) for b in batches] == [5, 2]
    assert all(b["route"] == "news" for b in batches)


def test_deep_rows_pack_three_per_batch():
    rows = [_row(f"200{i}") for i in range(7)]
    _, batches, _ = build_research_plan(_ranking(rows))
    assert [len(b["items"]) for b in batches] == [3, 3, 1]


def test_high_risk_rows_pack_three_per_batch():
    rows = [_row(f"300{i}", pct=20.0) for i in range(4)]
    _, batches, _ = build_research_plan(_ranking(rows))
    assert [len(b["items"]) for b in batches] == [3, 1]
    assert all(b["risk"] == "high" for b in batches)


# --- 死荷重の非混入（削減の要） -------------------------------------------

def test_batches_never_carry_dropped_rows_or_internal_fields():
    rows = [_row(f"400{i}", news=[_news(IN_WINDOW)]) for i in range(3)]
    _, batches, _ = build_research_plan(_ranking(rows))
    blob = json.dumps(batches, ensure_ascii=False)
    # dropped_turnover / dropped_mcap の中身は調査に使わないので一切渡さない
    assert "9999" not in blob and "8888" not in blob
    assert "dropped_turnover" not in blob and "dropped_mcap" not in blob
    # Stage1 の内部フィールドも渡さない
    for field in ("shoutfy_jq", "corr", "cur_end", "volume"):
        assert field not in blob


def test_inline_items_are_not_duplicated_into_batches():
    rows = [_row("1234", disclosures=[_disclosure("決算短信")]),
            _row("5678", news=[_news(IN_WINDOW)])]
    _, batches, inline = build_research_plan(_ranking(rows))
    batched_codes = {i["code"] for b in batches for i in b["items"]}
    assert batched_codes.isdisjoint({i["code"] for i in inline})


# --- manifest -------------------------------------------------------------

def test_manifest_records_budget_and_stats():
    rows = [_row(f"500{i}", news=[_news(IN_WINDOW)]) for i in range(6)]
    manifest, batches, _ = build_research_plan(_ranking(rows))
    budget = manifest["dispatch_budget"]
    assert budget["initial_pending"] == len(batches)
    assert budget["initial_limit"] == INITIAL_DISPATCH_LIMIT
    assert budget["total_limit"] == TOTAL_DISPATCH_LIMIT
    assert budget["per_batch_limit"] == PER_BATCH_DISPATCH_LIMIT
    assert manifest["ledger"] == {"reservations": {}, "total_reserved": 0}
    assert manifest["stats"]["rows"] == 6
    assert manifest["stats"]["batch_input_bytes_total"] > 0
    assert all(entry["status"] == "pending" for entry in manifest["batches"])


def test_manifest_digest_is_stable_for_identical_input():
    rows = [_row("1234", news=[_news(IN_WINDOW)])]
    first, _, _ = build_research_plan(_ranking(rows))
    second, _, _ = build_research_plan(_ranking(rows))
    assert first["input_digest"] == second["input_digest"]


def test_ranking_codes_cover_every_row():
    rows = [_row("1234", disclosures=[_disclosure("決算短信")]), _row("5678")]
    manifest, _, _ = build_research_plan(_ranking(rows))
    assert manifest["ranking_codes"] == ["1234", "5678"]


def test_rejects_row_without_code():
    with pytest.raises(ValueError):
        build_research_plan(_ranking([{"name": "コード無し"}]))
