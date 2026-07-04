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
