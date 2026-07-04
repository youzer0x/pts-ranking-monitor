"""check_gate.py の CLI 出力契約（SESSION= / SKIP）の単体テスト。

ルーチンはこの標準出力を見て SKIP なら生成をスキップする。check_gate.py は
__main__ のみなので、固定日付を引数に渡してサブプロセス実行し出力を検証する
（ネットワーク非接触・別プロセスなので pytest-socket の遮断とも干渉しない）。
"""
import subprocess
import sys
from pathlib import Path

GATE = Path(__file__).resolve().parents[1] / "scripts" / "check_gate.py"


def _run(date_arg):
    r = subprocess.run([sys.executable, str(GATE), date_arg],
                       capture_output=True, text=True)
    assert r.returncode == 0
    return r.stdout.strip()


def test_gate_emits_session_for_business_prev_day():
    # 金 07-03 の朝 → 前日 木 07-02 のセッション
    assert _run("2026-07-03") == "SESSION=2026-07-02"


def test_gate_emits_skip_when_no_session():
    # 月 07-06 の朝 → 前日 日曜（休場）→ SKIP
    assert _run("2026-07-06") == "SKIP"
