"""TDnet 適時開示情報の取得（一次情報）。

ソース: https://www.release.tdnet.info/inbs/I_list_{NNN}_{YYYYMMDD}.html
  - 1ページ100件・NNN=001,002,... のページネーション。UTF-8。
  - 行は kjTime / kjCode(5桁) / kjName / kjTitle(<a href=...pdf>) / kjPlace。
  - 開示一覧は当日を含め概ね31日分のみ公開（過去日は取得不可になりうる）。

PTS ナイト（前営業日17:00→当日06:00）の変動要因候補は、前営業日の「15:30以降」の開示。
stdlib のみ（urllib + 正規表現、bs4 不要）。
"""
import re, time, urllib.request
from datetime import date

BASE = "https://www.release.tdnet.info/inbs"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_ROW = re.compile(
    r'kjTime"[^>]*>\s*(\d{2}:\d{2})\s*</td>.*?'
    r'kjCode"[^>]*>\s*([0-9A-Za-z]+)\s*</td>.*?'
    r'kjName"[^>]*>\s*(.*?)\s*</td>.*?'
    r'kjTitle"[^>]*>(.*?)</td>',
    re.S,
)


def _code4(code5):
    code5 = code5.strip()
    if len(code5) == 5 and code5.endswith("0"):
        return code5[:-1]
    return code5


def _parse(html):
    rows = []
    for m in _ROW.finditer(html):
        t, code5, name, title_cell = m.groups()
        a = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', title_cell, re.S)
        if a:
            href, title = a.group(1), re.sub(r"<.*?>", "", a.group(2)).strip()
            pdf = href if href.startswith("http") else f"{BASE}/{href}"
        else:
            href, title, pdf = "", re.sub(r"<.*?>", "", title_cell).strip(), ""
        rows.append(dict(time=t, code=_code4(code5),
                         name=re.sub(r"<.*?>", "", name).strip(),
                         title=title, pdf_url=pdf))
    return rows


def fetch_disclosures(target, max_pages=30):
    """target（date or 'YYYY-MM-DD'）の適時開示一覧を全件取得する。"""
    if isinstance(target, date):
        ymd = target.strftime("%Y%m%d")
    else:
        ymd = str(target).replace("-", "")
    out = []
    for page in range(1, max_pages + 1):
        url = f"{BASE}/I_list_{page:03d}_{ymd}.html"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status != 200:
                    break
                html = r.read().decode("utf-8", "replace")
        except Exception:
            break
        rows = _parse(html)
        if not rows:
            break
        out.extend(rows)
        time.sleep(0.2)
    return out


def disclosures_by_code(target, since_hhmm="15:30"):
    """{4桁コード: [開示...]}（since_hhmm 以降のみ）。PTSナイト要因候補の突合に使う。"""
    by = {}
    for d in fetch_disclosures(target):
        if d["time"] >= since_hhmm:
            by.setdefault(d["code"], []).append(d)
    for v in by.values():
        v.sort(key=lambda x: x["time"])
    return by


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    tgt = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    by = disclosures_by_code(tgt)
    n = sum(len(v) for v in by.values())
    print(f"# {tgt}: {len(by)} codes with disclosures >=15:30 ({n} items)")
    for code in sorted(by):
        for d in by[code]:
            print(f"{d['time']}\t{d['code']}\t{d['name'][:16]}\t{d['title'][:48]}")
