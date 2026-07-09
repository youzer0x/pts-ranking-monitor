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
