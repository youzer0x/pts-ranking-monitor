"""株探（かぶたん）PTS ナイトタイムセッション 値上がり率ランキングの取得・パース。

ソース: https://kabutan.jp/warning/pts_night_price_increase
  - ナイトタイムセッション（17:00〜翌06:00）の「通常取引終値比（=上昇率）」降順ランキング。
  - 1ページ30件・ページャ `?market=0&capitalization=-1&dispmode=normal&stc=&stm=0&page=N`（最終 page=33 程度）。
  - 行の列構成（実地確認 2026-06-16）:
      コード / 銘柄名 / 市場 / [概要アイコン] / [チャートアイコン]
      / 通常取引終値 / PTS気配 / 前日比(差) / 上昇率% / 出来高 / PER / PBR / 利回り
  - 株探は「売買代金」を直接提供しないため、売買代金 ≒ PTS気配 × 夜間出来高 で概算する。

stdlib のみ（urllib）。ネット取得 or 保存済みHTML（argv）から再パースの両対応。

usage:
  python kabutan_pts.py                # ライブ取得して上昇率≥3%を表示
  python kabutan_pts.py page1.html ... # 保存済みHTMLから再パース
"""
import sys, re, json, time, urllib.request, urllib.parse

BASE = "https://kabutan.jp/warning/pts_night_price_increase"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
DEFAULT_MIN_PCT = 3.0          # 上昇率の下限（%）
DEFAULT_MIN_TURNOVER = 5_000_000  # 売買代金の下限（円）
MAX_PAGES = 40

# 1行ぶんの数値列をまとめて取る（通常終値 / PTS気配 / 上昇率 / 出来高）。
# 前日比(差)と up/down は非捕捉。捕捉群は 1=終値 2=PTS気配 3=上昇率 4=出来高。
_ROW_NUM = re.compile(
    r'<td>([\d,\.]+)</td>\s*'                       # 1 通常取引終値
    r'<td>([\d,\.]+)</td>\s*'                       # 2 PTS気配
    r'<td class="w61"><span class="(?:up|down)">[+\-]?[\d,\.]+</span></td>\s*'  # 前日比(差)
    r'<td class="w50"[^>]*><span class="(?:up|down)">([+\-]?[\d.]+)</span>%</td>\s*'  # 3 上昇率
    r'<td>([\d,]+)</td>',                           # 4 出来高
    re.S,
)


def _num(s):
    if s is None:
        return None
    s = s.replace(",", "").replace("＋", "+").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_html(html):
    """1ページ分のHTMLからランキング行（dictのリスト）を返す。"""
    st = html.find("stock_table st_market")
    if st < 0:
        return []
    tb = html.find("<tbody>", st)
    te = html.find("</tbody>", tb)
    if tb < 0 or te < 0:
        return []
    body = html[tb:te]
    rows = []
    parts = re.split(r'(?=<td class="tac"><a href="/stock/\?code=)', body)
    for p in parts:
        mc = re.search(r'/stock/\?code=([0-9A-Za-z]+)', p)
        if not mc:
            continue
        code = mc.group(1)
        mn = re.search(r'<th scope="row" class="tal">(.*?)</th>', p, re.S)
        name = re.sub(r"<.*?>", "", mn.group(1)).strip() if mn else "?"
        mb = re.search(r'<td class="tac">([^<]+)</td>', p)  # コード列は<a>入りで不一致→市場列に当たる
        badge = mb.group(1).strip() if mb else "?"
        mnum = _ROW_NUM.search(p)
        if not mnum:
            continue
        close_k = _num(mnum.group(1))
        pts = _num(mnum.group(2))
        pct = _num(mnum.group(3))
        vol = int(mnum.group(4).replace(",", "")) if mnum.group(4) else 0
        turnover = (pts or 0) * vol
        rows.append(dict(code=code, name=name, badge=badge, close_k=close_k,
                         pts=pts, pct=pct, volume=vol, turnover_yen=turnover))
    return rows


def _is_tse_badge(badge):
    """東証本則の事前フィルタ（権威判定は J-Quants 側で行う）。"""
    return badge.startswith("東") and badge not in ("東Ｅ", "東Ｒ", "東Ｉ")


def fetch_page(page):
    url = BASE + "?" + urllib.parse.urlencode(
        {"market": 0, "capitalization": -1, "dispmode": "normal",
         "stc": "", "stm": 0, "page": page})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if attempt == 4:
                raise
            time.sleep(1.5 ** attempt)
    return ""


_SHARES = re.compile(r'発行済株式数.{0,40}?>([\d,]+)', re.S)


def kabutan_shares(code):
    """株探の個別銘柄ページから最新の発行済株式数（int）を取得。失敗時 None。

    J-Quants の ShOutFY（期末）は期中の増資・自己株消却を反映しないため、
    最新株数との乖離が大きい銘柄に「†」を付すクロスチェック用。
    """
    url = f"https://kabutan.jp/stock/?code={code}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception:
        return None
    m = _SHARES.search(html)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def fetch_gainers(min_pct=DEFAULT_MIN_PCT, max_pages=MAX_PAGES, verbose=True):
    """上昇率降順で取得し、min_pct を下回ったページで停止して該当行を返す。"""
    out = []
    for page in range(1, max_pages + 1):
        html = fetch_page(page)
        rows = parse_html(html)
        if not rows:
            break
        out.extend(rows)
        last_pct = rows[-1].get("pct")
        if verbose:
            print(f"# page {page}: {len(rows)} rows (last pct={last_pct})", file=sys.stderr)
        if last_pct is not None and last_pct < min_pct:
            break
        time.sleep(0.3)
    return [r for r in out if r.get("pct") is not None and r["pct"] >= min_pct]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1:  # 保存済みHTMLから再パース
        rows = []
        for fn in sys.argv[1:]:
            rows.extend(parse_html(open(fn, encoding="utf-8", errors="replace").read()))
        rows = [r for r in rows if r.get("pct") is not None and r["pct"] >= DEFAULT_MIN_PCT]
    else:
        rows = fetch_gainers()
    tse = [r for r in rows if _is_tse_badge(r["badge"])]
    print(f"# total≥{DEFAULT_MIN_PCT}%={len(rows)}  TSE-prefilter={len(tse)}", file=sys.stderr)
    print("CODE\tBADGE\tPCT\tPTS\tCLOSE\tVOL\tTURNOVER_M\tNAME")
    for r in tse:
        tm = r["turnover_yen"] / 1e6
        print(f"{r['code']}\t{r['badge']}\t{r['pct']}\t{r['pts']}\t{r['close_k']}"
              f"\t{r['volume']}\t{tm:.1f}\t{r['name']}")


if __name__ == "__main__":
    main()
