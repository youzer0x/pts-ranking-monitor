"""build_ranking の掲載上限と株探ニュース事前取得のテスト。

外部 I/O は全て monkeypatch する（pytest-socket が通信を遮断するため、実行日時にも
ネットワークにも依存させない）。上限は「掲載を絞る」だけでなく、後続の TDnet 突合・
株探アクセス・Stage2 の調査対象も同時に絞るのが狙いなので、取得回数も検証する。
"""
import pytest

import build_ranking
import jquants
import kabutan_pts
import tdnet

SESSION = "2026-07-09"


@pytest.fixture
def stub_sources(monkeypatch):
    """株探・J-Quants・TDnet を差し替え、pct 降順に並ぶ n 銘柄を返せるようにする。"""
    state = {"news_calls": [], "shares_calls": []}

    def install(n_rows):
        raw = []
        for i in range(n_rows):
            code = f"{1000 + i}"
            raw.append({"code": code, "name": f"銘柄{code}", "badge": "東P",
                        # pct を降順にして、上限が「上位から」採ることを検証できるようにする
                        "pct": 50.0 - i, "pts": 1000, "volume": 10_000,
                        "turnover_yen": 50_000_000})
        master = {jquants.code5(r["code"]): {"CoName": r["name"], "MktNm": "プライム"}
                  for r in raw}
        bars = {jquants.code5(r["code"]): {"C": 950} for r in raw}

        monkeypatch.setattr(kabutan_pts, "fetch_gainers",
                            lambda min_pct=3.0, verbose=True: list(raw))
        monkeypatch.setattr(kabutan_pts, "_is_tse_badge", lambda badge: True)
        monkeypatch.setattr(jquants, "master_by_date", lambda d: master)
        monkeypatch.setattr(jquants, "bars_by_date", lambda d: bars)
        monkeypatch.setattr(jquants, "is_tse_individual", lambda m: True)
        monkeypatch.setattr(jquants, "market_cap_oku",
                            lambda code, close, session: (500.0, 100_000, "2026-03", 1.0))
        monkeypatch.setattr(tdnet, "disclosures_by_code", lambda d: {})

        def fake_news(code, max_items=12):
            state["news_calls"].append(code)
            return [{"datetime": f"{SESSION}T17:00", "category": "材料",
                     "title": f"{code} の材料", "url": f"https://example.com/{code}"}]

        def fake_shares(code):
            state["shares_calls"].append(code)
            return None

        monkeypatch.setattr(kabutan_pts, "kabutan_news", fake_news)
        monkeypatch.setattr(kabutan_pts, "kabutan_shares", fake_shares)
        monkeypatch.setattr(build_ranking.time, "sleep", lambda *_: None)
        return state

    return install


def test_caps_publication_to_max_rows(stub_sources):
    stub_sources(25)
    data = build_ranking.build(SESSION, max_rows=20, do_kabutan_shares=False, verbose=False)

    assert len(data["rows"]) == 20
    assert data["counts"] == {"qualifying": 25, "published": 20, "capped": 5,
                              "dropped_turnover": 0, "dropped_mcap": 0}
    assert data["criteria"]["max_rows"] == 20


def test_cap_keeps_the_highest_gainers_and_renumbers_ranks(stub_sources):
    stub_sources(25)
    data = build_ranking.build(SESSION, max_rows=20, do_kabutan_shares=False, verbose=False)

    pcts = [row["pct"] for row in data["rows"]]
    assert pcts == sorted(pcts, reverse=True)
    assert pcts[0] == 50.0                       # 最上位は落とさない
    assert min(pcts) == 50.0 - 19                # 21位以降だけが落ちる
    assert [row["rank"] for row in data["rows"]] == list(range(1, 21))


def test_cap_does_not_engage_below_the_limit(stub_sources):
    stub_sources(9)
    data = build_ranking.build(SESSION, max_rows=20, do_kabutan_shares=False, verbose=False)

    assert len(data["rows"]) == 9
    assert data["counts"]["capped"] == 0
    assert data["counts"]["qualifying"] == data["counts"]["published"] == 9


def test_no_cap_when_max_rows_is_none(stub_sources):
    stub_sources(25)
    data = build_ranking.build(SESSION, max_rows=None, do_kabutan_shares=False, verbose=False)

    assert len(data["rows"]) == 25
    assert data["counts"]["capped"] == 0


def test_kabutan_news_is_prefilled_only_for_published_rows(stub_sources):
    """上限は通信量も抑える。落とした行の株探ページは取りに行かない。"""
    state = stub_sources(25)
    data = build_ranking.build(SESSION, max_rows=20, do_kabutan_shares=False, verbose=False)

    assert len(state["news_calls"]) == 20
    assert state["news_calls"] == [row["code"] for row in data["rows"]]
    assert all(row["kabutan_news"] for row in data["rows"])


def test_kabutan_news_can_be_disabled(stub_sources):
    state = stub_sources(5)
    data = build_ranking.build(SESSION, max_rows=20, do_kabutan_shares=False,
                               do_kabutan_news=False, verbose=False)

    assert state["news_calls"] == []
    assert all(row["kabutan_news"] == [] for row in data["rows"])


def test_shares_cross_check_also_respects_the_cap(stub_sources):
    state = stub_sources(25)
    build_ranking.build(SESSION, max_rows=20, do_kabutan_shares=True, verbose=False)

    assert len(state["shares_calls"]) == 20


def test_rows_carry_empty_factor_fields_for_stage2(stub_sources):
    stub_sources(3)
    data = build_ranking.build(SESSION, max_rows=20, do_kabutan_shares=False, verbose=False)

    assert all(row["factor"] == "" and row["factor_kind"] == "" for row in data["rows"])
