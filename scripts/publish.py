"""Stage 2（公開）: 変動要因を埋めたランキング JSON を受け取り、
GitHub Pages（docs/index.html + docs/data/*.json + manifest）を更新し Gmail 通知を送る。

usage:
  python publish.py path/to/ranking_filled.json            # 公開 + メール送信
  python publish.py path/to/ranking_filled.json --no-email # 公開のみ（テスト用）

公開データは build_ranking.py の出力に各行 factor / factor_kind を埋めたもの。
Pages URL は環境変数 PAGES_URL、無ければ GITHUB_REPOSITORY_OWNER / GITHUB_REPOSITORY から推定。
"""
import os, sys, glob, json, argparse
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ranking_json")
    ap.add_argument("--no-email", action="store_true")
    args = ap.parse_args()

    with open(args.ranking_json, encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("rows", [])
    if "session_date" not in data:
        sys.exit("invalid ranking json: missing session_date")
    print(f"Publishing {data['session_date']} ({len(rows)} rows) ...")

    save_data(data)
    cleanup_old()
    update_manifest()
    write_index()

    url = pages_url()
    if args.no_email:
        print("  (--no-email) skip Gmail.")
    else:
        import gmail_sender
        email_html = html_generator.generate_email_html(data, url)
        gmail_sender.send_gmail(email_html, data["session_date"], len(rows))
    print(f"Done. Pages: {url}")


if __name__ == "__main__":
    main()
