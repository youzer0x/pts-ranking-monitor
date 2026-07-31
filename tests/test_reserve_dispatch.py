"""reserve_dispatch の予算強制のテスト。

これが「利用上限に到達するまでサブエージェントを起動し続ける」状態を構造的に止める部品。
枯渇時に exit 3 を返すことと、**そのとき台帳を書き換えないこと**の両方が要件。
書き換えてしまうと、拒否した試行まで予算を食って再試行の余地が消える。
"""
import json

from build_research_plan import write_research_plan
from reserve_dispatch import reserve

SESSION = "2026-07-09"
NEXT = "2026-07-10"


def _row(code):
    return {"code": code, "name": f"銘柄{code}", "rank": 1, "pct": 5.0,
            "turnover_m": 100.0, "disclosures": [], "kabutan_news": []}


def _plan(tmp_path, n_rows=9):
    """deep ルートの行だけの計画（3銘柄バッチ）を作り、research_dir を返す。"""
    ranking = {"session_date": SESSION, "next_date": NEXT,
               "rows": [_row(f"10{i:02d}") for i in range(n_rows)]}
    research_dir = tmp_path / "research"
    manifest = write_research_plan(ranking, str(research_dir))
    return str(research_dir), manifest


def _load(research_dir):
    with open(f"{research_dir}/manifest.json", encoding="utf-8") as handle:
        return json.load(handle)


def _patch_budget(research_dir, **changes):
    manifest = _load(research_dir)
    manifest["dispatch_budget"].update(changes)
    with open(f"{research_dir}/manifest.json", "w", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2))


def test_reserve_increments_ledger(tmp_path):
    research_dir, _ = _plan(tmp_path)
    assert reserve(research_dir, "batch-001") == 0
    ledger = _load(research_dir)["ledger"]
    assert ledger["reservations"]["batch-001"] == 1
    assert ledger["total_reserved"] == 1


def test_reserve_counts_each_batch_separately(tmp_path):
    research_dir, _ = _plan(tmp_path)
    assert reserve(research_dir, "batch-001") == 0
    assert reserve(research_dir, "batch-002") == 0
    ledger = _load(research_dir)["ledger"]
    assert ledger["reservations"] == {"batch-001": 1, "batch-002": 1}
    assert ledger["total_reserved"] == 2


def test_per_batch_limit_exhausts_with_exit_3_and_no_write(tmp_path):
    research_dir, _ = _plan(tmp_path)
    _patch_budget(research_dir, per_batch_limit=3)
    for expected_attempt in (1, 2, 3):
        assert reserve(research_dir, "batch-001") == 0
        assert _load(research_dir)["ledger"]["reservations"]["batch-001"] == expected_attempt

    before = _load(research_dir)["ledger"]
    assert reserve(research_dir, "batch-001") == 3
    assert _load(research_dir)["ledger"] == before  # 拒否した試行は予算を食わない


def test_total_limit_exhausts_with_exit_3_and_no_write(tmp_path):
    research_dir, _ = _plan(tmp_path)
    _patch_budget(research_dir, total_limit=2)
    assert reserve(research_dir, "batch-001") == 0
    assert reserve(research_dir, "batch-002") == 0

    before = _load(research_dir)["ledger"]
    assert reserve(research_dir, "batch-003") == 3
    assert _load(research_dir)["ledger"] == before


def test_unknown_batch_is_refused(tmp_path):
    research_dir, _ = _plan(tmp_path)
    before = _load(research_dir)["ledger"]
    assert reserve(research_dir, "batch-999") == 4
    assert _load(research_dir)["ledger"] == before


def test_non_pending_batch_is_refused(tmp_path):
    """compile 済みのバッチを再委譲して二重に予算を使わない。"""
    research_dir, _ = _plan(tmp_path)
    manifest = _load(research_dir)
    manifest["batches"][0]["status"] = "complete"
    with open(f"{research_dir}/manifest.json", "w", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2))

    assert reserve(research_dir, "batch-001") == 4
    assert _load(research_dir)["ledger"]["total_reserved"] == 0


def test_replan_carries_over_the_ledger(tmp_path):
    """再計画で予算がリセットされると上限が意味を失う。"""
    research_dir, _ = _plan(tmp_path)
    assert reserve(research_dir, "batch-001") == 0

    ranking = {"session_date": SESSION, "next_date": NEXT,
               "rows": [_row(f"10{i:02d}") for i in range(9)]}
    write_research_plan(ranking, research_dir)

    ledger = _load(research_dir)["ledger"]
    assert ledger["total_reserved"] == 1
    assert ledger["reservations"]["batch-001"] == 1
