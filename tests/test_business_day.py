"""business_day.py（東証営業日・PTS ナイトセッション日の判定）の単体テスト。

PTS 版の肝は session_date_for：朝 D に報告すべきセッション日は「D-1（前日）が
営業日ならその日、さもなくば None（新規セッション無し＝スキップ）」。tse 版の
tse_session_date_for（当日）とは別物なので、ここで前日ロジックを固定する。
日付はすべて過去の確定日を固定値で渡す。
"""
from datetime import date

import pytest

import business_day as bd


def test_is_business_day_weekday():
    assert bd.is_business_day(date(2026, 7, 3)) is True    # 金


def test_is_business_day_weekend():
    assert bd.is_business_day(date(2026, 7, 4)) is False   # 土
    assert bd.is_business_day(date(2026, 7, 5)) is False   # 日


def test_is_business_day_year_end_new_year():
    for d in [date(2026, 12, 31), date(2027, 1, 1), date(2027, 1, 2), date(2027, 1, 3)]:
        assert bd.is_business_day(d) is False


@pytest.mark.skipif(not bd._HAS_JP, reason="jpholiday 未導入時は祝日を判定できない")
def test_is_business_day_national_holiday():
    assert bd.is_business_day(date(2026, 7, 20)) is False  # 海の日（月）


def test_prev_business_day_skips_weekend():
    assert bd.prev_business_day(date(2026, 7, 6)) == date(2026, 7, 3)


# ── PTS 固有：session_date_for（前日ロジック）──────────────────
def test_session_date_for_weekday_returns_prev_day():
    # 金曜の朝に報告するのは木曜のナイトセッション
    assert bd.session_date_for(date(2026, 7, 3)) == date(2026, 7, 2)


def test_session_date_for_tuesday_returns_monday():
    # 火曜の朝 → 月曜（営業日）のナイト
    assert bd.session_date_for(date(2026, 7, 7)) == date(2026, 7, 6)


def test_session_date_for_monday_morning_is_none():
    # 月曜の朝：前日は日曜（休場）＝土日にナイトは立たない → None
    assert bd.session_date_for(date(2026, 7, 6)) is None


@pytest.mark.skipif(not bd._HAS_JP, reason="jpholiday 未導入時は祝日を判定できない")
def test_session_date_for_morning_after_holiday_is_none():
    # 火曜 07-21 の朝：前日は 07-20（海の日＝休場）→ 祝日夜にナイト無し → None
    assert bd.session_date_for(date(2026, 7, 21)) is None
