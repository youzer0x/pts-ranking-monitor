"""営業日ゲート: 朝 D に報告すべき PTS ナイトのセッション日を判定して出力する。

  - 前日（D-1）が東証営業日 → `SESSION=YYYY-MM-DD`（=D-1）を出力し exit 0。
  - 前日が休場（=新規ナイトセッション無し） → `SKIP` を出力し exit 0。

ルーチンはこの出力を見て、SKIP のときは生成せず終了する。
TZ=Asia/Tokyo を前提（クラウド環境変数で設定）。
"""
import os, sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import business_day

if __name__ == "__main__":
    today = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    s = business_day.session_date_for(today)
    print(f"SESSION={s.isoformat()}" if s else "SKIP")
