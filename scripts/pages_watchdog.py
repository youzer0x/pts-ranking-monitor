"""GitHub Pages 反映の番犬：main の docs/data/manifest.json の最新日付が Pages で配信されるまで見張り、
Pages ビルドが詰まって（queued/building のまま）いたり errored だったりしたら再ビルドを要求する。

背景（2026-10-27 分の事故）：ルーチンは 10/28 06:32 に main へ push したが、GitHub 側の
レガシー Pages ビルドが `building` のまま止まり（pages-build-deployment の Actions run が
起動されなかった）、`publish.py --notify` は5分待って「sending anyway」でメールを送った。
ページは手動で `POST /pages/builds` するまで前営業日のままだった。

GitHub Actions（.github/workflows/pages-watchdog.yml）から GITHUB_TOKEN（pages: write）で実行する。
本体は stdlib のみ。判定は純粋関数 `decide` に切り出してテストする。

usage:
  python scripts/pages_watchdog.py [--max-wait 1500] [--interval 60] [--max-rebuilds 2]
exit: 0 = 配信確認 / 1 = max-wait 内に配信を確認できず（Actions を赤くして通知させる）
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publish import DATA, pages_url

STUCK_AFTER = 600        # queued/building がこの秒数を超えたら詰まりとみなす（通常は1分前後で built）
BUILT_STALE_AFTER = 1200  # built 後もこの秒数ライブが古いまま＝CDN キャッシュ(max-age=600)では説明できない


def decide(expected, live, build_status, build_age):
    """次の行動を返す："ok"（配信済み）/ "wait"（待つ）/ "rebuild"（再ビルドを要求）。

    expected: main の manifest の最新日付 / live: Pages が返す manifest の最新日付（取得失敗は None）
    build_status: 最新 Pages ビルドの status（取得失敗は None）/ build_age: そのビルド作成からの経過秒
    """
    if live is not None and live >= expected:
        return "ok"
    if build_status == "errored":
        return "rebuild"
    if build_status in ("queued", "building") and build_age >= STUCK_AFTER:
        return "rebuild"
    if build_status == "built" and build_age >= BUILT_STALE_AFTER:
        return "rebuild"
    return "wait"


def expected_newest(data_dir=DATA):
    with open(os.path.join(data_dir, "manifest.json"), encoding="utf-8") as f:
        dates = json.load(f).get("dates", [])
    if not dates:
        sys.exit("manifest.json has no dates")
    return dates[0]


def build_age(created_at, now):
    """GitHub API の created_at（ISO8601, 末尾Z）から now までの経過秒。"""
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return (now - created).total_seconds()


def live_newest(base):
    url = f"{base.rstrip('/')}/data/manifest.json?cb={int(time.time())}"
    req = urllib.request.Request(url, headers={
        "Cache-Control": "no-cache", "Pragma": "no-cache",
        "User-Agent": "pts-ranking-monitor-watchdog"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            dates = json.loads(r.read()).get("dates", [])
        return dates[0] if dates else None
    except Exception as e:
        print(f"  live-check {type(e).__name__}: {e}")
        return None


def github_api(method, path):
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    req = urllib.request.Request(f"{api}/repos/{os.environ['GITHUB_REPOSITORY']}{path}", method=method,
                                 headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                                          "Accept": "application/vnd.github+json",
                                          "User-Agent": "pts-ranking-monitor-watchdog"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read() or b"{}")


def latest_build():
    try:
        b = github_api("GET", "/pages/builds/latest")
        return b.get("status"), build_age(b["created_at"], datetime.now(timezone.utc))
    except Exception as e:
        print(f"  build-check {type(e).__name__}: {e}")
        return None, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-wait", type=int, default=1500, help="配信確認を待つ最大秒（既定1500）")
    ap.add_argument("--interval", type=int, default=60, help="確認間隔秒（既定60）")
    ap.add_argument("--max-rebuilds", type=int, default=2, help="再ビルド要求の上限回数（既定2）")
    args = ap.parse_args()

    expected = expected_newest()
    base = pages_url()
    print(f"Watch Pages {base}: expect newest={expected}")
    deadline = time.monotonic() + args.max_wait
    rebuilds = 0
    while True:
        live = live_newest(base)
        status, age = latest_build()
        action = decide(expected, live, status, age)
        print(f"  live={live} build={status} age={int(age)}s -> {action}")
        if action == "ok":
            print(f"  live confirmed: Pages newest={live}")
            return 0
        if action == "rebuild" and rebuilds < args.max_rebuilds:
            rebuilds += 1
            github_api("POST", "/pages/builds")
            print(f"  requested Pages rebuild ({rebuilds}/{args.max_rebuilds})")
        if time.monotonic() >= deadline:
            break
        time.sleep(args.interval)
    print(f"ERROR: Pages still not serving {expected} after {args.max_wait}s (rebuilds={rebuilds})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
