"""Stage2 前処理（決定的）: ranking.json から調査バッチと manifest を組み立てる。

日次ルーチンの利用上限到達を構造的に防ぐための中核スクリプト。従来は「1銘柄=1サブエージェント・
row の JSON 全体をタスクプロンプトへ貼付」だったものを、次の3点に置き換える。

  1. **圧縮**：材料窓の外のニュース・TDnet と重複する株探見出し・古い継続テーマ見出しを
     LLM に渡す前に機械的に落とす（`prior` は最大 PRIOR_NEWS_LIMIT 件）。
     `dropped_turnover` / `dropped_mcap` はバッチに含めない（調査に使わない死荷重）。
  2. **バッチ化**：残った行を最大 NORMAL_BATCH_SIZE 銘柄（高リスク・深掘りは3銘柄）の
     自己完結したバッチファイルにまとめる。親はタスクへ batch_id と batch_path だけを渡す。
  3. **予算**：manifest に dispatch_budget と ledger を刻み、`reserve_dispatch.py` が
     委譲のたびに機械的に消費する。LLM の判断に関係なく総起動数が上限で止まる。

ルーティング（materials 窓＝SESSION 15:30 〜 翌 06:00）:
  - 高リスク（M&A 用語・大幅高・大商い）は開示があっても委譲する。EDINET 確認義務が付く。
  - 高リスク以外で TDnet 開示がある行は委譲せず inline.json に載せ、親が開示タイトルから起こす。
  - それ以外（窓内の株探見出しがある / 何も無い）は委譲する。

usage:
  python scripts/build_research_plan.py --ranking docs/tmp/ranking.json \
      --research-dir .work/<SESSION>/research

exit code: 0 正常 / 1 入力エラー / 2 初回 pending が initial_limit を超過（調査を開始しない）
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, time, timedelta, timezone

PLAN_SCHEMA_VERSION = "research_plan.v1"
BATCH_SCHEMA_VERSION = "research_batch.v1"
RESULT_SCHEMA_VERSION = "research_batch_result.v1"

JST = timezone(timedelta(hours=9))

# サブエージェントが埋める確認項目。東証版の sector_cluster は PTS では扱わない。
CHECK_NAMES = ("disclosures", "kabutan_news", "web_search", "edinet")
ROUTE_ORDER = {"disclosure": 0, "news": 1, "deep": 2}
M_AND_A_TERMS = ("TOB", "MBO", "公開買付", "買収", "非公開化", "完全子会社")

# 継続テーマの文脈は2件あれば足りる。Stage1 の株探見出しは十数件付くため、
# ここを絞らないとバッチ入力の大半が古い見出しで占められる。
PRIOR_NEWS_LIMIT = 2

# 材料窓の外に落ちる株探見出しを判定するための窓（SESSION 15:30 → 翌 06:00）。
WINDOW_START_TIME = time(15, 30)
WINDOW_END_TIME = time(6, 0)

HIGH_RISK_BATCH_SIZE = 3
NORMAL_BATCH_SIZE = 5
DEEP_BATCH_SIZE = 3

LARGE_MOVE_PCT = 15.0
HIGH_TURNOVER_M = 10_000.0

# ディスパッチ予算。掲載上限20行・委譲対象が約7割・1バッチ3〜5銘柄という前提から、
# 東証版（30行→initial 12・total/initial=1.5）を20行にスケールした値。
# 初回 pending がこれを超えるなら planner か ranking が壊れているとみなして停止する。
INITIAL_DISPATCH_LIMIT = 8
TOTAL_DISPATCH_LIMIT = 12
PER_BATCH_DISPATCH_LIMIT = 3


def _canonical_digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _compact_json_size(value):
    """バッチとして実際に書き出す UTF-8 バイト数を返す（削減量の計測用）。"""
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _dump_compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _atomic_write(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)


def _iso_date(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD") from exc


def _news_datetime(value):
    """株探見出しの datetime 属性を JST の datetime にする。解釈できなければ None。

    kabutan_news は best-effort（レイアウト変更時に degrade する）なので、
    解釈できない値で パイプライン全体を止めない。件数は stats に残す。
    """
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def window_for(ranking):
    """材料窓 (start, end_exclusive) を返す。SESSION 15:30 〜 翌 06:00 JST。"""
    session = _iso_date(ranking.get("session_date"), "session_date")
    next_day = ranking.get("next_date")
    next_date = _iso_date(next_day, "next_date") if next_day else session + timedelta(days=1)
    start = datetime.combine(session, WINDOW_START_TIME, JST)
    end = datetime.combine(next_date, WINDOW_END_TIME, JST)
    if start >= end:
        raise ValueError("next_date must follow session_date")
    return start, end


def compact_disclosures(row):
    """TDnet 開示を {time,title,pdf_url} に圧縮し重複を落とす。(items, omitted) を返す。

    code / name は item 側に既にあるので開示ごとに繰り返さない。
    `disclosures_by_code(..., since_hhmm="15:30")` が窓内だけを返す契約なので、
    ここでの時刻フィルタは行わない（重複除去のみ）。
    """
    raw = row.get("disclosures") or []
    items, seen, omitted = [], set(), 0
    for entry in raw:
        if not isinstance(entry, dict):
            omitted += 1
            continue
        title = str(entry.get("title") or "").strip()
        pdf_url = str(entry.get("pdf_url") or "").strip()
        identity = (title, pdf_url)
        if not title or identity in seen:
            omitted += 1
            continue
        seen.add(identity)
        items.append({
            "time": str(entry.get("time") or "").strip(),
            "title": title,
            "pdf_url": pdf_url,
        })
    return items, omitted


def compact_news(row, start, end):
    """株探見出しを材料窓で仕分けし、継続テーマを PRIOR_NEWS_LIMIT 件に絞る。

    落とすもの:
      - category=="開示" / URL が /disclosures/ … TDnet 開示の焼き直しで row.disclosures と重複
      - 配信時刻が窓の終わり（翌06:00）以降 … このセッションの材料ではない
      - 同一 (url, 時刻, 見出し) の重複
    """
    raw = row.get("kabutan_news") or []
    counts = {
        "material_window": 0,
        "prior": 0,
        "post_window_omitted": 0,
        "tdnet_duplicates_omitted": 0,
        "duplicates_omitted": 0,
        "undated": 0,
    }
    classified = {"material_window": [], "prior": []}
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            counts["duplicates_omitted"] += 1
            continue
        category = str(entry.get("category") or "").strip()
        title = str(entry.get("title") or "").strip()
        url = str(entry.get("url") or "").strip()
        stamp = str(entry.get("datetime") or "").strip()
        identity = (url, stamp, title)
        if identity in seen:
            counts["duplicates_omitted"] += 1
            continue
        seen.add(identity)
        if category == "開示" or "/disclosures/" in url:
            counts["tdnet_duplicates_omitted"] += 1
            continue
        published = _news_datetime(stamp)
        compact = {"published_at": stamp, "category": category, "title": title, "url": url}
        if published is None:
            # 時刻を確認できない見出しは窓内と断定できないため継続テーマ側に置く。
            counts["undated"] += 1
            classified["prior"].append((datetime.min.replace(tzinfo=JST), compact))
            continue
        if published >= end:
            counts["post_window_omitted"] += 1
            continue
        compact["published_at"] = published.isoformat(timespec="minutes")
        bucket = "material_window" if published >= start else "prior"
        classified[bucket].append((published, compact))
        counts[bucket] += 1

    for bucket in classified:
        classified[bucket].sort(key=lambda pair: pair[0], reverse=True)
    prior = [item for _, item in classified["prior"][:PRIOR_NEWS_LIMIT]]
    counts["prior_retained"] = len(prior)
    counts["prior_omitted_by_cap"] = max(0, len(classified["prior"]) - len(prior))
    return {
        "material_window": [item for _, item in classified["material_window"]],
        "prior": prior,
    }, counts


def risk_reasons(row, context_text):
    """高リスク（＝バッチを小さくし EDINET 確認を課す）理由を返す。"""
    reasons = []
    haystack = context_text.casefold()
    if any(term.casefold() in haystack for term in M_AND_A_TERMS):
        reasons.append("m_and_a")
    pct = row.get("pct")
    if isinstance(pct, (int, float)) and not isinstance(pct, bool) and pct >= LARGE_MOVE_PCT:
        reasons.append("large_move")
    turnover = row.get("turnover_m")
    if (isinstance(turnover, (int, float)) and not isinstance(turnover, bool)
            and turnover >= HIGH_TURNOVER_M):
        reasons.append("high_turnover")
    return reasons


def build_research_plan(ranking):
    """(manifest, batches, inline_items) を返す純関数。ファイルには触れない。"""
    if not isinstance(ranking, dict):
        raise ValueError("ranking root must be an object")
    rows = ranking.get("rows")
    if not isinstance(rows, list):
        raise ValueError("ranking.rows must be a list")
    start, end = window_for(ranking)
    session_date = ranking["session_date"]
    next_date = ranking.get("next_date") or (
        _iso_date(session_date, "session_date") + timedelta(days=1)).isoformat()

    news_totals = {}
    disclosure_omitted = 0
    codes = []
    delegated, inline_items = [], []

    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("ranking.rows[] must be objects")
        code = str(row.get("code") or "").strip()
        if not code:
            raise ValueError("ranking.rows[].code is required")
        codes.append(code)

        disclosures, omitted = compact_disclosures(row)
        disclosure_omitted += omitted
        news, news_counts = compact_news(row, start, end)
        for key, value in news_counts.items():
            news_totals[key] = news_totals.get(key, 0) + value

        context_text = " ".join(
            [item["title"] for item in disclosures]
            + [item["title"] for item in news["material_window"]]
        )
        reasons = risk_reasons(row, context_text)
        risk = "high" if reasons else "normal"
        if disclosures:
            route = "disclosure"
        elif news["material_window"]:
            route = "news"
        else:
            route = "deep"

        item = {
            "code": code,
            "name": str(row.get("name") or "").strip(),
            "rank": row.get("rank"),
            "pct": row.get("pct"),
            "pts": row.get("pts"),
            "close": row.get("close"),
            "turnover_m": row.get("turnover_m"),
            "mcap_oku": row.get("mcap_oku"),
            "route": route,
            "risk": risk,
            "risk_reasons": reasons,
            "disclosures": disclosures,
            "news": news,
        }
        if "m_and_a" in reasons:
            item["requires_edinet"] = True

        # 高リスクは開示があっても委譲する（EDINET での裏取りが要るため）。
        # それ以外で開示がある行は親がインラインで起こす＝サブエージェントを使わない。
        if risk == "normal" and disclosures:
            inline_items.append(item)
        else:
            delegated.append(item)

    batches = []

    def context_key(item):
        material = item["news"]["material_window"]
        shared_url = material[0]["url"] if material else ""
        return (ROUTE_ORDER[item["route"]], shared_url,
                item.get("rank") if item.get("rank") is not None else 10 ** 9, item["code"])

    def append_batch(chunk):
        if not chunk:
            return
        risk = "high" if any(item["risk"] == "high" for item in chunk) else "normal"
        routes = {item["route"] for item in chunk}
        route = next(iter(routes)) if len(routes) == 1 else "mixed"
        payload = {
            "schema_version": BATCH_SCHEMA_VERSION,
            "batch_id": f"batch-{len(batches) + 1:03d}",
            "session_date": session_date,
            "next_date": next_date,
            "window": {
                "start": start.isoformat(timespec="minutes"),
                "end_exclusive": end.isoformat(timespec="minutes"),
            },
            "route": route,
            "risk": risk,
            "checks_required": list(CHECK_NAMES),
            "items": chunk,
        }
        payload["input_digest"] = _canonical_digest(payload)
        batches.append(payload)

    high = sorted([i for i in delegated if i["risk"] == "high"], key=context_key)
    normal_deep = sorted(
        [i for i in delegated if i["risk"] == "normal" and i["route"] == "deep"], key=context_key)
    normal_direct = sorted(
        [i for i in delegated if i["risk"] == "normal" and i["route"] != "deep"], key=context_key)
    for items, limit in ((high, HIGH_RISK_BATCH_SIZE),
                         (normal_direct, NORMAL_BATCH_SIZE),
                         (normal_deep, DEEP_BATCH_SIZE)):
        for offset in range(0, len(items), limit):
            append_batch(items[offset:offset + limit])

    manifest_batches = [{
        "batch_id": batch["batch_id"],
        "path": f"batches/{batch['batch_id']}.json",
        "result_path": f"results/{batch['batch_id']}.json",
        "input_digest": batch["input_digest"],
        "input_bytes": _compact_json_size(batch),
        "status": "pending",
        "codes": [item["code"] for item in batch["items"]],
        "route": batch["route"],
        "risk": batch["risk"],
    } for batch in batches]
    sizes = [entry["input_bytes"] for entry in manifest_batches]

    manifest = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "session_date": session_date,
        "next_date": next_date,
        "window": {
            "start": start.isoformat(timespec="minutes"),
            "end_exclusive": end.isoformat(timespec="minutes"),
        },
        "input_digest": _canonical_digest({
            "session_date": session_date,
            "codes": codes,
            "batches": [batch["input_digest"] for batch in batches],
        }),
        "ranking_codes": codes,
        "inline_path": "inline.json",
        "inline_codes": [item["code"] for item in inline_items],
        "batches": manifest_batches,
        "dispatch_budget": {
            "initial_pending": len(manifest_batches),
            "initial_limit": INITIAL_DISPATCH_LIMIT,
            "total_limit": TOTAL_DISPATCH_LIMIT,
            "per_batch_limit": PER_BATCH_DISPATCH_LIMIT,
        },
        "ledger": {"reservations": {}, "total_reserved": 0},
        "stats": {
            "rows": len(rows),
            "inline": len(inline_items),
            "delegated": len(delegated),
            "batches": len(batches),
            "batch_input_bytes_total": sum(sizes),
            "batch_input_bytes_max": max(sizes) if sizes else 0,
            "news": dict(sorted(news_totals.items())),
            "disclosures_omitted_duplicate": disclosure_omitted,
        },
    }
    return manifest, batches, inline_items


def _carry_over_ledger(manifest_path):
    """既存 manifest の台帳を引き継ぐ。再計画で予算がリセットされると上限が意味を失う。"""
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            previous = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"reservations": {}, "total_reserved": 0}
    if isinstance(previous, dict) and isinstance(previous.get("ledger"), dict):
        return previous["ledger"]
    return {"reservations": {}, "total_reserved": 0}


def write_research_plan(ranking, research_dir):
    """バッチ・inline・manifest を research_dir 配下へ書き出し、manifest を返す。"""
    manifest, batches, inline_items = build_research_plan(ranking)
    manifest_path = os.path.join(research_dir, "manifest.json")
    manifest["ledger"] = _carry_over_ledger(manifest_path)

    os.makedirs(os.path.join(research_dir, "batches"), exist_ok=True)
    os.makedirs(os.path.join(research_dir, "results"), exist_ok=True)
    for batch in batches:
        _atomic_write(os.path.join(research_dir, "batches", f"{batch['batch_id']}.json"),
                      _dump_compact(batch))
    _atomic_write(os.path.join(research_dir, "inline.json"), _dump_compact({
        "schema_version": BATCH_SCHEMA_VERSION,
        "session_date": manifest["session_date"],
        "next_date": manifest["next_date"],
        "window": manifest["window"],
        "note": "開示タイトルだけで説明できる行。親がインラインで factor を起こす（委譲しない）。",
        "items": inline_items,
    }))
    _atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description="Stage2 の調査バッチと manifest を生成する")
    ap.add_argument("--ranking", required=True, help="build_ranking.py の出力 JSON")
    ap.add_argument("--research-dir", required=True, help="出力先 .work/<SESSION>/research")
    args = ap.parse_args(argv)

    try:
        with open(args.ranking, encoding="utf-8") as handle:
            ranking = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[build_research_plan] ERROR: {exc}", file=sys.stderr)
        return 1
    try:
        manifest = write_research_plan(ranking, args.research_dir)
    except ValueError as exc:
        print(f"[build_research_plan] ERROR: {exc}", file=sys.stderr)
        return 1

    stats = manifest["stats"]
    pending = manifest["dispatch_budget"]["initial_pending"]
    print(f"[build_research_plan] rows={stats['rows']} inline={stats['inline']} "
          f"delegated={stats['delegated']} batches={stats['batches']} "
          f"bytes_total={stats['batch_input_bytes_total']} "
          f"bytes_max={stats['batch_input_bytes_max']}", file=sys.stderr)
    print(f"[build_research_plan] news={stats['news']}", file=sys.stderr)
    if pending > INITIAL_DISPATCH_LIMIT:
        print(f"[build_research_plan] REFUSED: initial pending {pending} > "
              f"{INITIAL_DISPATCH_LIMIT}. 調査を開始しない。", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
