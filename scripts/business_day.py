"""東証の営業日判定と PTS ナイトセッション日付の導出。

PTS ナイトタイムは「前営業日 17:00 → 当日 06:00」。朝 D に取得できる最新セッションは
D-1（前日）の夕方に始まったもの。したがって朝 D に報告すべきセッション日は:
    session = D - 1日（ただし D-1 が東証営業日のとき。さもなくば新規セッション無し＝スキップ）

jpholiday があれば祝日を考慮、無ければ土日のみ判定（スキル単体実行向けフォールバック）。
"""
from datetime import date, timedelta

try:
    import jpholiday
    _HAS_JP = True
except ImportError:
    _HAS_JP = False


def is_business_day(d):
    """東証営業日か（土日・祝日・年末年始 12/31〜1/3 を除外）。"""
    if d.weekday() >= 5:
        return False
    if (d.month, d.day) in [(12, 31), (1, 1), (1, 2), (1, 3)]:
        return False
    if _HAS_JP and jpholiday.is_holiday(d):
        return False
    return True


def prev_business_day(d):
    """d より前の直近営業日。"""
    x = d - timedelta(days=1)
    while not is_business_day(x):
        x -= timedelta(days=1)
    return x


def session_date_for(run_day):
    """朝 run_day に報告すべき PTS ナイトのセッション日（=run_day-1 が営業日なら、その日）。

    新規セッションが無い朝（run_day-1 が休場）は None を返す＝ルーチンはスキップ。
    """
    prev = run_day - timedelta(days=1)
    return prev if is_business_day(prev) else None


if __name__ == "__main__":
    import sys
    today = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    print(f"jpholiday={'on' if _HAS_JP else 'OFF (weekday-only)'}")
    print(f"today={today} business_day={is_business_day(today)}")
    print(f"prev_business_day={prev_business_day(today)}")
    print(f"session_date_for(today)={session_date_for(today)}")
