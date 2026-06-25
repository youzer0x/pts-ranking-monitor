"""Stage 2（公開）: 変動要因を埋めたランキング JSON を受け取り、
GitHub Pages（docs/index.html + docs/data/*.json + manifest）を更新し Gmail 通知を送る。

2フェーズ運用（メールのリンク先が「前営業日」止まりになるラグ対策）：
  1) 生成（build）：`python publish.py ranking_filled.json --no-email`
      … docs/ 一式を生成するだけ（メールは送らない）。
  2) この後に git push（GitHub Pages＝main/docs を反映）。
  3) 通知（notify）：`python publish.py ranking_filled.json --notify`
     … Pages が新セッションを実際に配信し始めるまで待ってから Gmail 送信する。
  ※ 引数なし（＝即時送信）は push 前送信になりラグの原因になるため**レガシー**。ルーチンでは使わない。

usage:
  python publish.py path/to/ranking_filled.json --no-email # 生成のみ（送信しない・build フェーズ）
  python publish.py path/to/ranking_filled.json --notify   # push 後にライブ確認→Gmail 送信（推奨）
  python publish.py path/to/ranking_filled.json            # レガシー：公開 + 即メール送信（非推奨）

公開データは build_ranking.py の出力に各行 factor / factor_kind を埋めたもの。
Pages URL は環境変数 PAGES_URL、無ければ GITHUB_REPOSITORY_OWNER / GITHUB_REPOSITORY から推定。
"""
import os, sys, glob, json, argparse, time
import urllib.request, urllib.error
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import html_generator

DOCS = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "docs"))
DATA = os.path.join(DOCS, "data")
KEEP_DAYS = 90


def pages_url():
    if os.environ.get("PAGES_URL"):
        return os.environ["PAGES_URL"].rstrip("/") + "/"
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "USER")
    repo = (os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1]) or "pts-ranking-monitor"
    return f"https://{owner}.github.io/{repo}/"


def save_data(data):
    os.makedirs(DATA, exist_ok=True)
    d = data["session_date"]
    path = os.path.join(DATA, f"{d}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  data saved: {path} ({len(data.get('rows', []))} rows)")


def cleanup_old():
    if not os.path.isdir(DATA):
        return
    cutoff = date.today() - timedelta(days=KEEP_DAYS)
    for fp in glob.glob(os.path.join(DATA, "*.json")):
        name = os.path.basename(fp)
        if name == "manifest.json":
            continue
        try:
            if date.fromisoformat(name[:-5]) < cutoff:
                os.remove(fp)
        except ValueError:
            pass


def update_manifest():
    dates = []
    for fp in sorted(glob.glob(os.path.join(DATA, "*.json")), reverse=True):
        name = os.path.basename(fp)
        if name == "manifest.json":
            continue
        try:
            dates.append(date.fromisoformat(name[:-5]).isoformat())
        except ValueError:
            pass
    with open(os.path.join(DATA, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"dates": dates}, f, ensure_ascii=False)
    print(f"  manifest updated: {len(dates)} dates")
    return dates


def write_index():
    os.makedirs(DOCS, exist_ok=True)
    path = os.path.join(DOCS, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_generator.generate_pages_html())
    print(f"  index.html written: {path}")


def normalize_names(data):
    """銘柄名を J-Quants 正式名称（CoName・株式会社抜き）へ強制的に揃える。

    後段の編集で name が株探の略称に化けても、公開前にここで CoName へ上書きする
    （決定的ガードレール）。J-Quants 取得に失敗した場合は既存の name を維持する。
    """
    try:
        import jquants
        m = jquants.master_by_date(data["session_date"])
    except Exception as e:
        print(f"  (name normalize skipped: {type(e).__name__}: {e})")
        return
    fixed = 0
    for lst in (data.get("rows"), data.get("dropped_turnover"), data.get("dropped_mcap")):
        for r in lst or []:
            co = m.get(jquants.code5(r["code"]), {}).get("CoName")
            if co and r.get("name") != co:
                r["name"] = co
                fixed += 1
    print(f"  names normalized to J-Quants CoName ({fixed} changed)")


def wait_until_live(pages_url, session, timeout=300, interval=10):
    """push 後、GitHub Pages が新セッションを配信し始めるまで待つ（メールのリンク先ラグ対策）。

    Pages の `data/manifest.json` をキャッシュ無効化クエリ（?cb=<epoch>）＋no-cache ヘッダで
    取得し、`dates[0]==session` になったら True を返す（＝SPA が当日分を最新として表示できる状態）。
    pages_url 未設定（"./"）はスキップして False。timeout 内に確認できなければ警告を出して False を
    返すが、**送信は呼び出し側で続行**する（遅れてでも通知する方がよい）。本体は stdlib のみ。
    """
    if not pages_url or pages_url.rstrip("/") in ("", "."):
        print("  (skip live-check: pages-url 未設定)")
        return False
    base = pages_url.rstrip("/")
    deadline = time.monotonic() + timeout
    n = 0
    while time.monotonic() < deadline:
        n += 1
        url = f"{base}/data/manifest.json?cb={int(time.time())}"
        try:
            req = urllib.request.Request(url, headers={
                "Cache-Control": "no-cache", "Pragma": "no-cache",
                "User-Agent": "pts-ranking-monitor-livecheck"})
            with urllib.request.urlopen(req, timeout=15) as r:
                dates = json.loads(r.read()).get("dates", [])
            if dates and dates[0] == session:
                print(f"  live confirmed: Pages newest={session} (checks={n})")
                return True
            print(f"  not live yet (newest={dates[0] if dates else None}); wait {interval}s")
        except urllib.error.HTTPError as e:
            print(f"  live-check HTTP {e.code}; wait {interval}s")
        except Exception as e:
            print(f"  live-check {type(e).__name__}: {e}; wait {interval}s")
        time.sleep(interval)
    print(f"  WARN: Pages not confirmed live within {timeout}s; sending anyway")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ranking_json")
    ap.add_argument("--notify", action="store_true",
                    help="push 後に Pages のライブ反映を待ってから Gmail 送信（生成はしない）。ルーチン推奨")
    ap.add_argument("--no-email", action="store_true",
                    help="生成のみ（Gmail 送信しない）。build フェーズで使う")
    ap.add_argument("--live-timeout", type=int, default=300, help="--notify のライブ確認の最大待機秒（既定300）")
    ap.add_argument("--live-interval", type=int, default=10, help="--notify のライブ確認の間隔秒（既定10）")
    args = ap.parse_args()

    with open(args.ranking_json, encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("rows", [])
    if "session_date" not in data:
        sys.exit("invalid ranking json: missing session_date")

    if args.notify:
        # 通知フェーズ：生成・コミットは済んでいる前提。push 後の Pages 反映を待って送信する。
        url = pages_url()
        print(f"Notify {data['session_date']} ({len(rows)} rows): wait for Pages then send ... Pages: {url}")
        wait_until_live(url, data["session_date"],
                        timeout=args.live_timeout, interval=args.live_interval)
        import gmail_sender
        email_html = html_generator.generate_email_html(data, url)
        gmail_sender.send_gmail(email_html, data["session_date"], len(rows))
        print(f"Done (notify). Pages: {url}")
        return

    print(f"Publishing {data['session_date']} ({len(rows)} rows) ...")

    normalize_names(data)
    save_data(data)
    cleanup_old()
    update_manifest()
    write_index()

    url = pages_url()
    if args.no_email:
        print("  (--no-email) skip Gmail.")
    else:
        # レガシー経路（push 前送信＝リンク先が未反映になりやすい）。ルーチンは push 後に --notify を使う。
        print("  WARN: 引数なしの即時送信は push 前送信のためリンク先ラグの原因。ルーチンでは --no-email で生成→push→--notify。")
        import gmail_sender
        email_html = html_generator.generate_email_html(data, url)
        gmail_sender.send_gmail(email_html, data["session_date"], len(rows))
    print(f"Done. Pages: {url}")


if __name__ == "__main__":
    main()
