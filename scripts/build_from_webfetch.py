"""WebFetch で取得した kabutan モバイル版データを使い、J-Quants + TDnet で ranking.json を生成する。
kabutan.jp デスクトップ版へのアクセスがブロックされている場合の代替スクリプト。
"""
import sys, os, json, time, datetime
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jquants, tdnet

SESSION = "2026-06-19"
MIN_PCT = 3.0
MIN_TURNOVER = 5_000_000
MIN_MCAP = 100

# WebFetch で取得した kabutan モバイル版データ（page1〜3、≥3%の全銘柄）
RAW_CANDIDATES = [
    # page1
    {"code": "149A", "name": "シンカ",      "badge": "東G", "close_k": 700,    "pts": 850,    "pct": 21.43, "volume": 2300},
    {"code": "6897", "name": "ツインバード", "badge": "東S", "close_k": 391,    "pts": 471,    "pct": 20.46, "volume": 2400},
    {"code": "3544", "name": "サツドラHD",  "badge": "東S", "close_k": 813,    "pts": 963,    "pct": 18.45, "volume": 2500},
    {"code": "5803", "name": "フジクラ",    "badge": "東P", "close_k": 5161,   "pts": 6079,   "pct": 17.79, "volume": 2127600},
    {"code": "4667", "name": "アイサンテク", "badge": "東S", "close_k": 1864,   "pts": 2186,   "pct": 17.27, "volume": 8900},
    {"code": "485A", "name": "PowerX",      "badge": "東G", "close_k": 1800,   "pts": 2080,   "pct": 15.56, "volume": 522400},
    {"code": "9449", "name": "GMO",         "badge": "東P", "close_k": 3000,   "pts": 3420,   "pct": 14.00, "volume": 7600},
    {"code": "6217", "name": "津田駒",      "badge": "東S", "close_k": 1113,   "pts": 1259.9, "pct": 13.20, "volume": 34000},
    {"code": "6613", "name": "QDレーザ",    "badge": "東G", "close_k": 2520,   "pts": 2850,   "pct": 13.10, "volume": 371400},
    {"code": "3444", "name": "菊池製作",    "badge": "東S", "close_k": 922,    "pts": 1040,   "pct": 12.80, "volume": 12300},
    {"code": "6433", "name": "ヒーハイスト","badge": "東S", "close_k": 1141,   "pts": 1242,   "pct": 8.85,  "volume": 9400},
    {"code": "3976", "name": "シャノン",    "badge": "東G", "close_k": 570,    "pts": 610,    "pct": 7.02,  "volume": 500},
    {"code": "5216", "name": "倉元",        "badge": "東S", "close_k": 127,    "pts": 135.9,  "pct": 7.01,  "volume": 153300},
    {"code": "9256", "name": "サクシード",  "badge": "東G", "close_k": 2540,   "pts": 2715,   "pct": 6.89,  "volume": 14700},
    {"code": "7383", "name": "ネットプロ",  "badge": "東P", "close_k": 338,    "pts": 361,    "pct": 6.80,  "volume": 20600},
    {"code": "5816", "name": "オーナンバ",  "badge": "東S", "close_k": 1829,   "pts": 1950,   "pct": 6.62,  "volume": 300},
    {"code": "9501", "name": "東電HD",      "badge": "東P", "close_k": 514,    "pts": 547,    "pct": 6.42,  "volume": 377600},
    {"code": "3189", "name": "ANAPAHD",     "badge": "東S", "close_k": 103,    "pts": 109,    "pct": 5.83,  "volume": 400},
    {"code": "3907", "name": "シリコンスタ","badge": "東S", "close_k": 849,    "pts": 895,    "pct": 5.42,  "volume": 6200},
    # page2
    {"code": "6338", "name": "タカトリ",    "badge": "東S", "close_k": 1719,   "pts": 1810,   "pct": 5.29,  "volume": 1200},
    {"code": "5817", "name": "JMACS",       "badge": "東S", "close_k": 1049,   "pts": 1104,   "pct": 5.24,  "volume": 63600},
    {"code": "8836", "name": "RISE",        "badge": "東S", "close_k": 26,     "pts": 27.3,   "pct": 5.00,  "volume": 67600},
    {"code": "6629", "name": "Tホライゾン", "badge": "東S", "close_k": 991,    "pts": 1039,   "pct": 4.84,  "volume": 15100},
    {"code": "9310", "name": "トランシティ","badge": "東P", "close_k": 1127,   "pts": 1180,   "pct": 4.70,  "volume": 100},
    {"code": "7779", "name": "サイバダイン", "badge": "東G", "close_k": 246,    "pts": 257.5,  "pct": 4.67,  "volume": 12400},
    {"code": "3086", "name": "Jフロント",   "badge": "東P", "close_k": 2506.5, "pts": 2620,   "pct": 4.53,  "volume": 3700},
    {"code": "9247", "name": "TREHD",       "badge": "東P", "close_k": 2126,   "pts": 2221,   "pct": 4.47,  "volume": 500},
    {"code": "6327", "name": "北川精機",    "badge": "東S", "close_k": 5190,   "pts": 5420,   "pct": 4.43,  "volume": 14300},
    {"code": "5985", "name": "サンコール",  "badge": "東S", "close_k": 2014,   "pts": 2100,   "pct": 4.27,  "volume": 14100},
    {"code": "5471", "name": "大同特鋼",    "badge": "東P", "close_k": 2623.5, "pts": 2734,   "pct": 4.21,  "volume": 4800},
    {"code": "4691", "name": "ワシントンH", "badge": "東S", "close_k": 2534,   "pts": 2640,   "pct": 4.18,  "volume": 1000},
    {"code": "6471", "name": "日精工",      "badge": "東P", "close_k": 1193.5, "pts": 1242,   "pct": 4.06,  "volume": 3200},
    {"code": "3266", "name": "ファンクリG", "badge": "東S", "close_k": 82,     "pts": 85.3,   "pct": 4.02,  "volume": 100},
    {"code": "6324", "name": "ハーモニック","badge": "東P", "close_k": 7770,   "pts": 8080,   "pct": 3.99,  "volume": 4900},
    {"code": "6506", "name": "安川電",      "badge": "東P", "close_k": 7128,   "pts": 7400,   "pct": 3.82,  "volume": 19000},
    {"code": "5482", "name": "愛知鋼",      "badge": "東P", "close_k": 3025,   "pts": 3140,   "pct": 3.80,  "volume": 200},
    {"code": "4189", "name": "KHネオケム",  "badge": "東P", "close_k": 2800,   "pts": 2906,   "pct": 3.79,  "volume": 1000},
    {"code": "4531", "name": "有機薬",      "badge": "東S", "close_k": 423,    "pts": 439,    "pct": 3.78,  "volume": 184000},
    {"code": "6954", "name": "ファナック",  "badge": "東P", "close_k": 7473,   "pts": 7750,   "pct": 3.71,  "volume": 53100},
    # page3 (≥3%)
    {"code": "9270", "name": "バリュエンス","badge": "東G", "close_k": 2359,   "pts": 2446.1, "pct": 3.69,  "volume": 200},
    {"code": "8226", "name": "理経",        "badge": "東S", "close_k": 386,    "pts": 400,    "pct": 3.63,  "volume": 200},
    {"code": "5721", "name": "Sクリプトエ","badge": "東S", "close_k": 56,     "pts": 58,     "pct": 3.57,  "volume": 184000},
    {"code": "6998", "name": "タングス",    "badge": "東S", "close_k": 2353,   "pts": 2435,   "pct": 3.48,  "volume": 100},
    {"code": "6731", "name": "ピクセラ",    "badge": "東S", "close_k": 103,    "pts": 106.5,  "pct": 3.40,  "volume": 13100},
    {"code": "5381", "name": "マイポックス","badge": "東S", "close_k": 1185,   "pts": 1225,   "pct": 3.38,  "volume": 3700},
    {"code": "6490", "name": "PILLAR",      "badge": "東P", "close_k": 10980,  "pts": 11350,  "pct": 3.37,  "volume": 200},
    {"code": "6666", "name": "リバーエレク","badge": "東S", "close_k": 904,    "pts": 933,    "pct": 3.21,  "volume": 600},
    {"code": "6480", "name": "トムソン",    "badge": "東P", "close_k": 2230,   "pts": 2301.5, "pct": 3.21,  "volume": 2900},
    {"code": "2693", "name": "YKT",         "badge": "東S", "close_k": 359,    "pts": 370,    "pct": 3.06,  "volume": 500},
    {"code": "4425", "name": "Kudan",       "badge": "東G", "close_k": 1863,   "pts": 1920,   "pct": 3.06,  "volume": 3400},
    {"code": "5244", "name": "jig.jp",      "badge": "東G", "close_k": 165,    "pts": 170,    "pct": 3.03,  "volume": 800},
    {"code": "4840", "name": "トライアイズ","badge": "東S", "close_k": 631,    "pts": 650,    "pct": 3.01,  "volume": 10200},
]

def log(*a):
    print(*a, file=sys.stderr)

def main():
    session_iso = SESSION
    sd = date.fromisoformat(session_iso)

    # 売買代金計算
    for r in RAW_CANDIDATES:
        r["turnover_yen"] = round(r["pts"] * r["volume"])

    # J-Quants master / bars 取得
    log(f"# J-Quants master/bars for {session_iso} ...")
    master = jquants.master_by_date(session_iso)
    bars   = jquants.bars_by_date(session_iso)
    log(f"# master={len(master)} bars={len(bars)}")

    qualifying, dropped_turnover, dropped_mcap = [], [], []

    for r in RAW_CANDIDATES:
        c5 = jquants.code5(r["code"])
        m  = master.get(c5)

        if not jquants.is_tse_individual(m):
            log(f"# SKIP non-TSE-individual: {r['code']} {r['name']}")
            continue

        if r["turnover_yen"] < MIN_TURNOVER:
            dropped_turnover.append({
                "code": r["code"],
                "name": m.get("CoName") or r["name"],
                "pct":  r["pct"],
                "turnover_m": round(r["turnover_yen"] / 1e6, 1),
                "volume": r["volume"],
            })
            continue

        b = bars.get(c5)
        close = b.get("C") if b else r["close_k"]

        mcap, shoutfy, cur_end, corr = jquants.market_cap_oku(r["code"], close, session_iso)
        time.sleep(0.2)

        if mcap is None or mcap < MIN_MCAP:
            dropped_mcap.append({
                "code": r["code"],
                "name": m.get("CoName") or r["name"],
                "pct":  r["pct"],
                "turnover_m": round(r["turnover_yen"] / 1e6, 1),
                "mcap_oku": (round(mcap) if mcap is not None else None),
            })
            continue

        qualifying.append(dict(
            code        = r["code"],
            name        = m.get("CoName") or r["name"],
            market      = m.get("MktNm"),
            mcap_oku    = round(mcap),
            mcap_flag   = "",
            pct         = r["pct"],
            pts         = r["pts"],
            close       = close,
            volume      = r["volume"],
            turnover_yen= r["turnover_yen"],
            turnover_m  = round(r["turnover_yen"] / 1e6, 1),
            shoutfy_jq  = shoutfy,
            cur_end     = cur_end,
            corr        = round(corr, 6),
            disclosures = [],
            factor      = "",
            factor_kind = "",
        ))

    qualifying.sort(key=lambda x: -x["pct"])
    for i, row in enumerate(qualifying, 1):
        row["rank"] = i

    log(f"# qualifying={len(qualifying)}  dropped_turnover={len(dropped_turnover)}  dropped_mcap={len(dropped_mcap)}")

    # TDnet 15:30以降の開示
    log(f"# TDnet disclosures (>=15:30) for {session_iso} ...")
    try:
        by = tdnet.disclosures_by_code(session_iso)
    except Exception as e:
        log(f"# WARN tdnet: {type(e).__name__}: {e}")
        by = {}
    for row in qualifying:
        row["disclosures"] = by.get(row["code"], [])

    data = {
        "session_date":   session_iso,
        "next_date":      (sd + timedelta(days=1)).isoformat(),
        "session_window": f"{session_iso} 17:00 → {(sd + timedelta(days=1)).isoformat()} 06:00 JST",
        "generated_at":   datetime.datetime.now().strftime("%Y-%m-%d %H:%M JST"),
        "criteria":       {"min_pct": MIN_PCT, "min_turnover_yen": MIN_TURNOVER, "min_mcap_oku": MIN_MCAP},
        "counts":         {"qualifying": len(qualifying), "dropped_turnover": len(dropped_turnover), "dropped_mcap": len(dropped_mcap)},
        "rows":           qualifying,
        "dropped_turnover": sorted(dropped_turnover, key=lambda x: -x["pct"]),
        "dropped_mcap":     sorted(dropped_mcap,    key=lambda x: -x["pct"]),
    }

    out_path = "docs/tmp/ranking.json"
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log(f"# wrote {out_path} ({len(qualifying)} qualifying)")

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
