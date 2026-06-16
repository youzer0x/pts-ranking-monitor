"""J-Quants V2 API クライアント（時価総額・市場区分・終値・発行済株式数）。

- 認証: ヘッダ `x-api-key`（環境変数 JQUANTS_API_KEY）。Light プラン以上で当日値が取れる。
- 時価総額(億円) = 取引所終値 × 発行済株式数(ShOutFY) × 分割/併合補正(AdjFactor) / 1e8。
- 東証個別株の権威判定: master の ProdCat=="011"（内国株券）かつ Mkt∈{0111,0112,0113}
  （プライム/スタンダード/グロース）。地方単独上場は bars/daily 非収録で自動除外。
- AdjFactor は株式分割・併合のみ補正。増資・自己株消却は非対象 → 株探の最新株数と
  クロスチェックして乖離が大きい銘柄は呼び出し側で「†」注記する。

stdlib のみ（urllib）。
"""
import os, json, time, urllib.request, urllib.error, urllib.parse
from datetime import date, timedelta

API = "https://api.jquants.com/v2"


def _key():
    k = os.environ.get("JQUANTS_API_KEY")
    if not k:
        raise SystemExit("JQUANTS_API_KEY not set")
    return k


def get(path, params, max_pages=80):
    """V2 を呼び pagination_key を連結して data 配列を返す（429 リトライ込み）。"""
    key = _key()
    out, pk = [], None
    for _ in range(max_pages):
        p = dict(params)
        if pk:
            p["pagination_key"] = pk
        url = f"{API}{path}?" + urllib.parse.urlencode(p)
        req = urllib.request.Request(url, headers={"x-api-key": key})
        body = None
        for attempt in range(9):
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    body = json.load(r)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(min(1.5 * (attempt + 1), 12)); continue
                raise
            except Exception:
                if attempt == 8:
                    raise
                time.sleep(1.5 ** attempt)
        if body is None:
            raise RuntimeError(f"empty/429-exhausted: {path} {params}")
        out.extend(body.get("data", []))
        pk = body.get("pagination_key")
        if not pk:
            break
    return out


def code5(code4):
    """株探/TDnet の4桁（または英数）コードを J-Quants の5桁へ。9760→97600, 285A→285A0。"""
    return code4 + "0" if len(code4) == 4 else code4


def master_by_date(target_iso):
    return {r["Code"]: r for r in get("/equities/master", {"date": target_iso})}


def bars_by_date(target_iso):
    return {r["Code"]: r for r in get("/equities/bars/daily", {"date": target_iso})}


def is_tse_individual(m):
    """master 行が東証本則の内国株券か。"""
    return bool(m) and m.get("ProdCat") == "011" and m.get("Mkt") in ("0111", "0112", "0113")


def latest_shares(code4):
    """最新の (期末日 CurFYEn, 期末発行済株式数 ShOutFY) を返す。無ければ None。"""
    data = get("/fins/summary", {"code": code4})
    cands = []
    for r in data:
        sh = r.get("ShOutFY"); disc = r.get("DiscDate"); cur = r.get("CurFYEn") or disc
        if sh in (None, "", 0) or not disc:
            continue
        cands.append((disc, cur, sh))
    if not cands:
        return None
    cands.sort(key=lambda x: x[0])
    _disc, cur, sh = cands[-1]
    try:
        return cur, int(float(sh))
    except (ValueError, TypeError):
        return None


def split_corr(code4, since_iso, target_iso):
    """since の翌日〜target の AdjFactor 累積積の逆数（分割・併合の株数補正係数）。"""
    try:
        since = date.fromisoformat(since_iso); tgt = date.fromisoformat(target_iso)
    except (ValueError, TypeError):
        return 1.0
    if since >= tgt:
        return 1.0
    data = get("/equities/bars/daily",
               {"code": code4, "from": (since + timedelta(days=1)).isoformat(), "to": target_iso})
    corr = 1.0
    for r in data:
        f = r.get("AdjFactor")
        if f and float(f) != 1.0:
            corr /= float(f)
    return corr


def market_cap_oku(code4, close, target_iso):
    """1銘柄の時価総額(億円)を算出して返す。返り値: (mcap_oku|None, shoutfy|None, cur_end|None, corr)。"""
    if close is None:
        return None, None, None, 1.0
    sh = latest_shares(code4)
    if not sh:
        return None, None, None, 1.0
    cur_end, shoutfy = sh
    try:
        corr = split_corr(code4, cur_end, target_iso)
    except Exception:
        corr = 1.0
    return close * shoutfy * corr / 1e8, shoutfy, cur_end, corr
