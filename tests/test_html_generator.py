"""html_generator.py の書式関数とメール HTML 生成の単体テスト（純粋変換・ネット非接触）。"""
import html_generator as hg


# ── 書式関数 ──────────────────────────────────────────────
def test_fmt_mcap():
    assert hg.fmt_mcap(None) == "—"
    assert hg.fmt_mcap(1234) == "1,234"
    assert hg.fmt_mcap(1234, "†") == "1,234†"   # 株数乖離フラグ付き


def test_fmt_pct():
    assert hg.fmt_pct(None) == "—"
    assert hg.fmt_pct(15.09) == "+15.09%"
    assert hg.fmt_pct(3.0) == "+3.00%"


# ── linkify_factor ────────────────────────────────────────
def test_linkify_factor_converts_markdown_link():
    out = hg.linkify_factor("材料は[日経新聞](https://www.nikkei.com/article/123)による報道。")
    assert '<a href="https://www.nikkei.com/article/123" target="_blank" rel="noopener noreferrer">日経新聞</a>' in out
    assert "[日経新聞]" not in out
    assert "](https://www.nikkei.com/article/123)" not in out


def test_linkify_factor_handles_multiple_links():
    out = hg.linkify_factor("（[Bloomberg](https://a.example/x)、[Reuters via Investing.com](https://b.example/y)）。")
    assert out.count("<a href=") == 2
    assert "[Bloomberg]" not in out and "[Reuters via Investing.com]" not in out
    assert "https://a.example/x)" not in out  # 生URLが本文側に露出していない


def test_linkify_factor_escapes_plain_text():
    out = hg.linkify_factor("A<b>&テスト</b>")
    assert "<b>" not in out
    assert "&lt;b&gt;" in out


def test_linkify_factor_ignores_non_http_scheme():
    out = hg.linkify_factor("[悪意](javascript:alert(1))")
    assert "<a href=" not in out


# ── generate_email_html ──────────────────────────────────────
def _data(n_rows):
    return {
        "session_date": "2026-07-02",
        "session_window": "2026-07-02 17:00 → 2026-07-03 06:00",
        "rows": [
            {"rank": i + 1, "code": f"700{i}", "name": f"テスト銘柄{i}",
             "mcap_oku": 1000 + i, "mcap_flag": "", "pct": 3.0 + i,
             "factor": f"材料{i}", "factor_kind": "開示"}
            for i in range(n_rows)
        ],
    }


def test_generate_email_html_contains_names_and_link():
    html = hg.generate_email_html(_data(3), "https://example.github.io/x/")
    assert "テスト銘柄0" in html and "テスト銘柄2" in html
    assert "https://example.github.io/x/" in html
    assert "PTS 夜間 値上がり率ランキング" in html


def test_generate_email_html_respects_max_items():
    html = hg.generate_email_html(_data(5), "https://x/", max_items=2)
    assert "テスト銘柄0" in html and "テスト銘柄1" in html
    assert "テスト銘柄2" not in html and "テスト銘柄4" not in html


def test_generate_email_html_handles_empty_rows():
    html = hg.generate_email_html(_data(0), "https://x/")
    assert "PTS 夜間 値上がり率ランキング" in html


def test_generate_email_html_linkifies_factor_sources():
    data = _data(1)
    data["rows"][0]["factor"] = "材料は[日経新聞](https://www.nikkei.com/article/123)による。"
    html = hg.generate_email_html(data, "https://x/")
    assert '<a href="https://www.nikkei.com/article/123"' in html
    assert "[日経新聞](https://www.nikkei.com/article/123)" not in html


# ── generate_pages_html ──────────────────────────────────────
def test_generate_pages_html_uses_editorial_design():
    """東証版（tse-ranking-monitor）と統一した金融紙エディトリアルデザインであること。"""
    html = hg.generate_pages_html()
    assert "--bg:#f5f2ea" in html            # 生成りの紙面風背景
    assert "Noto+Serif+JP" in html           # 明朝見出しフォント
    assert "tabular-nums" in html
    assert "https://youzer0x.github.io/tse-ranking-monitor/" in html  # 東証版への相互リンク


def test_generate_pages_html_tab_order_matches_tse():
    """ヘッダーは両サイト共通の固定順「東証 → 市場分析 → PTS」であること。"""
    html = hg.generate_pages_html()
    assert 'href="https://youzer0x.github.io/tse-ranking-monitor/#market">市場分析</a>' in html
    i_tse = html.index(">東証 値上がり率ランキング</a>")
    i_market = html.index(">市場分析</a>")
    i_pts = html.index('<h1 class="tab active">PTS 夜間 値上がり率ランキング</h1>')
    assert i_tse < i_market < i_pts


def test_generate_pages_html_keeps_spa_shell():
    """SPA の要（manifest 取得・日付セレクタ・描画先）が維持されていること。"""
    html = hg.generate_pages_html()
    assert "data/manifest.json" in html
    assert 'id="dateSelect"' in html
    assert 'id="tableArea"' in html
    assert 'id="droppedArea"' in html
    assert 'id="viewRanking"' in html        # レスポンシブ CSS のスコープ用ラッパー


def test_generate_pages_html_meta_moved_into_info_modal():
    """対象日時・生成日時・抽出条件はファーストビューから撤去し、
    該当社数横の「データ情報」ボタンからモーダルで表示する。"""
    html = hg.generate_pages_html()
    assert 'id="infoModal"' in html and 'id="infoBody"' in html
    assert "openInfo" in html and "showModal" in html
    assert 'id="note"' not in html               # 抽出条件の常時表示を廃止
    assert 'chip">生成 ' not in html             # 生成日時チップを廃止
    assert "session_window" in html              # モーダル側で継続表示
    assert "社該当" in html                      # 該当社数チップは維持


def test_generate_pages_html_has_no_market_view():
    """市場分析ビューは東証版のみ（PTS にはデータが無い）。誤移植を検知する。"""
    html = hg.generate_pages_html()
    assert "viewMarket" not in html
    assert "renderMarket" not in html
    assert "pct5" not in html                # 5営業日騰落も PTS データに無い
