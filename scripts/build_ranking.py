"""Stage 1（決定的）: PTS ナイト値上がりランキングの素データを組み立てて JSON 出力する。

  株探（PTS気配・上昇率・出来高） + J-Quants V2（市場区分・終値・発行済株式数→時価総額）
  + TDnet（15:30以降の適時開示の突合） を結合する。**変動要因は含めない**（後段で Claude が埋める）。

フィルタ:
  - 東証個別株のみ（J-Quants ProdCat=011 かつ Mkt∈{0111,0112,0113}）。ETF/REIT/地方上場は除外。
  - PTS上昇率 ≥ min_pct（既定 +3%）かつ PTS売買代金 ≥ min_turnover（既定 ¥5,000,000）。
  - 時価総額 ≥ min_mcap 億円（既定 100）。時価総額＝J-Quants 終値×発行済株式数×分割/併合補正。
  - 期中の増資・自己株で J-Quants 株数と株探最新株数が >1% 乖離する銘柄は mcap_flag="†"。

usage:
  python build_ranking.py [--date YYYY-MM-DD] [--out ranking.json]
  python build_ranking.py --files page1.html page2.html   # 保存済み株探HTMLから（要 --date）
"""
import sys, os, json, time, argparse, datetime
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kabutan_pts, jquants, tdnet, business_day


def build(session_iso, min_pct=3.0, min_turnover=5_000_000, min_mcap=100,
          from_files=None, do_kabutan_shares=True, verbose=True):
    def log(*a):
        if verbose:
            print(*a, file=sys.stderr)

    # 1) 株探 PTS ナイト値上がり（上昇率≥min_pct）
    if from_files:
        rows = []
        for fn in from_files:
            rows += kabutan_pts.parse_html(open(fn, encoding="utf-8", errors="replace").read())
        rows = [r for r in rows if r.get("pct") is not None and r["pct"] >= min_pct]
    else:
        rows = kabutan_pts.fetch_gainers(min_pct=min_pct, verbose=verbose)
    cand = [r for r in rows if kabutan_pts._is_tse_badge(r["badge"])]
    log(f"# kabutan≥{min_pct}%={len(rows)}  TSE-prefilter={len(cand)}")

    # 2) J-Quants 一括（master / bars）
    log(f"# J-Quants master/bars for {session_iso} ...")
    master = jquants.master_by_date(session_iso)
    bars = jquants.bars_by_date(session_iso)
    log(f"# master={len(master)} bars={len(bars)}")

    qualifying, dropped_turnover, dropped_mcap, excluded = [], [], [], []
    for r in cand:
        c5 = jquants.code5(r["code"])
        m = master.get(c5)
        if not jquants.is_tse_individual(m):
            excluded.append({"code": r["code"], "name": r["name"], "reason": "not_tse_individual"})
            continue
        if r["turnover_yen"] < min_turnover:
            dropped_turnover.append({"code": r["code"], "name": m.get("CoName") or r["name"],
                                     "pct": r["pct"], "turnover_m": round(r["turnover_yen"] / 1e6, 1),
                                     "volume": r["volume"]})
            continue
        b = bars.get(c5)
        close = b.get("C") if b else None
        mcap, shoutfy, cur_end, corr = jquants.market_cap_oku(r["code"], close, session_iso)
        time.sleep(0.2)
        if mcap is None or mcap < min_mcap:
            dropped_mcap.append({"code": r["code"], "name": m.get("CoName") or r["name"],
                                 "pct": r["pct"], "turnover_m": round(r["turnover_yen"] / 1e6, 1),
                                 "mcap_oku": (round(mcap) if mcap is not None else None)})
            continue
        qualifying.append(dict(
            code=r["code"], name=m.get("CoName") or r["name"], market=m.get("MktNm"),
            mcap_oku=round(mcap), mcap_flag="", pct=r["pct"], pts=r["pts"], close=close,
            volume=r["volume"], turnover_yen=round(r["turnover_yen"]),
            turnover_m=round(r["turnover_yen"] / 1e6, 1),
            shoutfy_jq=shoutfy, cur_end=cur_end, corr=round(corr, 6),
            disclosures=[], factor="", factor_kind=""))

    qualifying.sort(key=lambda x: -x["pct"])
    for i, row in enumerate(qualifying, 1):
        row["rank"] = i
    log(f"# qualifying={len(qualifying)}  dropped_turnover={len(dropped_turnover)}  "
        f"dropped_mcap={len(dropped_mcap)}  excluded={len(excluded)}")

    # 3) TDnet 15:30以降の開示を突合（一次情報の変動要因候補）
    log(f"# TDnet disclosures (>=15:30) for {session_iso} ...")
    try:
        by = tdnet.disclosures_by_code(session_iso)
    except Exception as e:
        log(f"# WARN tdnet: {type(e).__name__}: {e}")
        by = {}
    for row in qualifying:
        row["disclosures"] = by.get(row["code"], [])

    # 4) 株探 最新発行済株式数とのクロスチェック（† 注記）
    if do_kabutan_shares:
        log(f"# kabutan shares cross-check for {len(qualifying)} names ...")
        for row in qualifying:
            shk = kabutan_pts.kabutan_shares(row["code"])
            time.sleep(0.2)
            base = (row["shoutfy_jq"] or 0) * (row["corr"] or 1.0)
            if shk and base > 0 and abs(shk - base) / base > 0.01:
                row["mcap_flag"] = "†"
                row["shares_kabutan"] = shk
                if row["close"]:
                    row["mcap_kabutan_oku"] = round(row["close"] * shk / 1e8)

    sd = date.fromisoformat(session_iso)
    return {
        "session_date": session_iso,
        "next_date": (sd + datetime.timedelta(days=1)).isoformat(),
        "session_window": f"{session_iso} 17:00 → {(sd + datetime.timedelta(days=1)).isoformat()} 06:00 JST",
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M JST"),
        "criteria": {"min_pct": min_pct, "min_turnover_yen": min_turnover, "min_mcap_oku": min_mcap},
        "counts": {"qualifying": len(qualifying), "dropped_turnover": len(dropped_turnover),
                   "dropped_mcap": len(dropped_mcap)},
        "rows": qualifying,
        "dropped_turnover": sorted(dropped_turnover, key=lambda x: -x["pct"]),
        "dropped_mcap": sorted(dropped_mcap, key=lambda x: -x["pct"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="セッション日 YYYY-MM-DD（省略時は直近営業日）")
    ap.add_argument("--min-pct", type=float, default=3.0)
    ap.add_argument("--min-turnover", type=float, default=5_000_000)
    ap.add_argument("--min-mcap", type=float, default=100)
    ap.add_argument("--out", help="JSON 出力先パス（省略時は stdout）")
    ap.add_argument("--no-kabutan-shares", action="store_true")
    ap.add_argument("--files", nargs="*", help="保存済み株探HTML（--date 必須）")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    session_iso = args.date or business_day.prev_business_day(date.today()).isoformat()
    data = build(session_iso, min_pct=args.min_pct, min_turnover=args.min_turnover,
                 min_mcap=args.min_mcap, from_files=args.files,
                 do_kabutan_shares=not args.no_kabutan_shares)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.out:
        d = os.path.dirname(os.path.abspath(args.out))
        os.makedirs(d, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"# wrote {args.out} ({data['counts']['qualifying']} qualifying)", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
