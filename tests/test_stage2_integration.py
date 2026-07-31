"""Stage2 の全経路をオフラインで通す結合テスト。

plan → reserve → (返却の代役) → compile → merge_factors まで実際に走らせる。
compile の出力がベンダリング済み `merge_factors.py` の入力契約に適合していることは
単体テストでは確かめられないので、ここで実物を subprocess で叩いて検証する。

fixture は合成データで作る（`docs/data/` は publish.py の KEEP_DAYS=90 で消えるため、
実データに依存させるとテストがいずれ壊れる）。
"""
import json
import subprocess
import sys
from pathlib import Path

from build_research_plan import RESULT_SCHEMA_VERSION, write_research_plan
from reserve_dispatch import reserve

import compile_research_results as crr

SESSION = "2026-07-09"
NEXT = "2026-07-10"
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
CHECKS = {"disclosures": "done", "kabutan_news": "done", "web_search": "done", "edinet": "na"}


def _ranking(n_disclosure=3, n_news=17):
    rows = []
    for i in range(n_disclosure):
        code = f"90{i:02d}"
        rows.append({
            "code": code, "name": f"開示銘柄{code}", "market": "プライム", "mcap_oku": 500,
            "pct": 9.0 - i * 0.1, "pts": 1000, "close": 950, "volume": 10_000,
            "turnover_yen": 50_000_000, "turnover_m": 50.0,
            "disclosures": [{"time": "16:00", "code": code, "name": f"開示銘柄{code}",
                             "title": "2026年3月期 決算短信",
                             "pdf_url": f"https://tdnet.example/{code}.pdf"}],
            "kabutan_news": [], "factor": "", "factor_kind": "",
        })
    for i in range(n_news):
        code = f"80{i:02d}"
        rows.append({
            "code": code, "name": f"報道銘柄{code}", "market": "グロース", "mcap_oku": 300,
            "pct": 8.0 - i * 0.1, "pts": 800, "close": 750, "volume": 20_000,
            "turnover_yen": 40_000_000, "turnover_m": 40.0,
            "disclosures": [],
            "kabutan_news": [{"datetime": f"{SESSION}T17:30", "category": "材料",
                              "title": f"{code} に関する材料",
                              "url": f"https://example.com/{code}"}],
            "factor": "", "factor_kind": "",
        })
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return {"session_date": SESSION, "next_date": NEXT,
            "session_window": f"{SESSION} 17:00 → {NEXT} 06:00 JST",
            "criteria": {"min_pct": 3.0, "max_rows": 20},
            "counts": {"qualifying": len(rows), "published": len(rows), "capped": 0},
            "rows": rows,
            "dropped_turnover": [{"code": "9999", "name": "薄商い"}],
            "dropped_mcap": [{"code": "8888", "name": "小型"}]}


def test_stage2_end_to_end_fills_every_factor(tmp_path):
    ranking_path = tmp_path / "ranking.json"
    original = _ranking()
    ranking_path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    research_dir = str(tmp_path / "research")

    # 1) 計画
    manifest = write_research_plan(original, research_dir)
    assert manifest["stats"]["rows"] == 20
    # 開示だけで説明できる行は委譲しない
    assert len(manifest["inline_codes"]) == 3
    # 窓内ニュースのある行は5銘柄バッチにまとまる（17件 → 4バッチ）
    assert len(manifest["batches"]) == 4
    assert manifest["dispatch_budget"]["initial_pending"] <= \
        manifest["dispatch_budget"]["initial_limit"]

    # 2) 予約 → 委譲（サブエージェント返却の代役）
    for entry in manifest["batches"]:
        assert reserve(research_dir, entry["batch_id"]) == 0
        payload = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "batch_id": entry["batch_id"],
            "input_digest": entry["input_digest"],
            "items": [{
                "code": code, "status": "complete",
                "factor": f"{code} は材料視した買いが入ったとみられる。"
                          f"[出典](https://example.com/{code})",
                "factor_kind": "報道",
                "sources": [{"label": "出典", "url": f"https://example.com/{code}"}],
                "checks": dict(CHECKS),
            } for code in entry["codes"]],
        }
        Path(research_dir, entry["result_path"]).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    # 3) 親のインライン分
    inline_path = tmp_path / "inline_factors.json"
    inline_path.write_text(json.dumps(
        [{"code": code, "factor": f"{code} は決算を好感した買いである。", "factor_kind": "開示"}
         for code in manifest["inline_codes"]], ensure_ascii=False), encoding="utf-8")

    # 4) 集約
    factors_path = tmp_path / "factors.json"
    assert crr.main(["--research-dir", research_dir, "--out", str(factors_path),
                     "--inline", str(inline_path)]) == 0

    # 5) マージ（ベンダリング済みの実物を叩く）
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "merge_factors.py"),
         "--ranking", str(ranking_path), "--factors", str(factors_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stderr
    assert "MISSING" not in (proc.stdout + proc.stderr)
    assert "REJECTED" not in (proc.stdout + proc.stderr)

    # 6) 品質ゲート: 空 factor を残さない／他フィールドと順序が保たれる
    merged = json.loads(ranking_path.read_text(encoding="utf-8"))
    assert [r["code"] for r in merged["rows"]] == [r["code"] for r in original["rows"]]
    assert all(r["factor"].strip() for r in merged["rows"])
    assert {r["factor_kind"] for r in merged["rows"]} == {"開示", "報道"}
    for before, after in zip(original["rows"], merged["rows"]):
        assert after["name"] == before["name"]      # 略称で上書きされない
        assert after["rank"] == before["rank"]
        assert after["mcap_oku"] == before["mcap_oku"]


def test_budget_stops_runaway_dispatch(tmp_path):
    """予算が尽きたら委譲できない＝上限に当たるまで起動し続ける状態が起きない。"""
    research_dir = str(tmp_path / "research")
    manifest = write_research_plan(_ranking(), research_dir)
    total_limit = manifest["dispatch_budget"]["total_limit"]

    reserved = 0
    while reserve(research_dir, "batch-001") == 0:
        reserved += 1
        assert reserved <= total_limit, "per_batch_limit が効いていない"
    # 同一バッチは per_batch_limit までしか予約できない
    assert reserved == manifest["dispatch_budget"]["per_batch_limit"]
