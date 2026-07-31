"""compile_research_results の検証と集約のテスト。

親が返却 JSON を自分のコンテキストで組み立て直さないためのスクリプトなので、
「壊れた返却を黙って通さない」ことが要件。特に input_digest 不一致（＝古い結果の
使い回し）とコード集合の不一致は、別銘柄の factor が混入する事故に直結する。
"""
import json

import compile_research_results as crr
from build_research_plan import RESULT_SCHEMA_VERSION, write_research_plan

SESSION = "2026-07-09"
NEXT = "2026-07-10"
CHECKS = {"disclosures": "done", "kabutan_news": "done", "web_search": "done", "edinet": "na"}


def _row(code, disclosures=None):
    return {"code": code, "name": f"銘柄{code}", "rank": 1, "pct": 5.0, "turnover_m": 100.0,
            "disclosures": disclosures or [], "kabutan_news": []}


def _plan(tmp_path, rows=None):
    ranking = {"session_date": SESSION, "next_date": NEXT,
               "rows": rows or [_row(f"10{i:02d}") for i in range(6)]}
    research_dir = tmp_path / "research"
    manifest = write_research_plan(ranking, str(research_dir))
    return str(research_dir), manifest


def _result_for(entry, status="complete", **overrides):
    payload = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "batch_id": entry["batch_id"],
        "input_digest": entry["input_digest"],
        "items": [{
            "code": code,
            "status": status,
            "factor": f"{code} は材料を好感した買いが入ったとみられる。",
            "factor_kind": "報道",
            "sources": [{"label": "出典", "url": "https://example.com/a"}],
            "checks": dict(CHECKS),
        } for code in entry["codes"]],
    }
    payload.update(overrides)
    return payload


def _write_result(research_dir, entry, payload):
    path = f"{research_dir}/{entry['result_path']}"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))


def _write_all(research_dir, manifest, **kwargs):
    for entry in manifest["batches"]:
        _write_result(research_dir, entry, _result_for(entry, **kwargs))


def test_compiles_all_batches_in_ranking_order(tmp_path):
    research_dir, manifest = _plan(tmp_path)
    _write_all(research_dir, manifest)

    entries, missing, unresolved, errors, compiled = crr.compile_results(research_dir)
    assert errors == [] and missing == [] and unresolved == []
    assert [e["code"] for e in entries] == compiled["ranking_codes"]
    assert all(set(e) >= {"code", "factor", "factor_kind"} for e in entries)
    assert all(b["status"] == "complete" for b in compiled["batches"])


def test_missing_result_is_reported_and_exits_3(tmp_path):
    research_dir, manifest = _plan(tmp_path)
    for entry in manifest["batches"][1:]:
        _write_result(research_dir, entry, _result_for(entry))

    out = tmp_path / "factors.json"
    assert crr.main(["--research-dir", research_dir, "--out", str(out)]) == 3

    _, missing, _, _, _ = crr.compile_results(research_dir)
    assert set(missing) == set(manifest["batches"][0]["codes"])


def test_stale_result_is_rejected(tmp_path):
    """input_digest が違う＝入力が変わったのに古い結果が残っている。採用しない。"""
    research_dir, manifest = _plan(tmp_path)
    entry = manifest["batches"][0]
    _write_result(research_dir, entry, _result_for(entry, input_digest="ちがう値"))

    _, missing, _, errors, compiled = crr.compile_results(research_dir)
    assert any("input_digest mismatch" in message for message in errors)
    assert set(entry["codes"]) <= set(missing)
    assert compiled["batches"][0]["status"] == "invalid"


def test_code_set_mismatch_is_rejected(tmp_path):
    """1銘柄でも欠けた/増えた返却は、別銘柄への取り違えを招くので丸ごと落とす。"""
    research_dir, manifest = _plan(tmp_path)
    entry = manifest["batches"][0]
    payload = _result_for(entry)
    payload["items"] = payload["items"][:-1]
    _write_result(research_dir, entry, payload)

    _, missing, _, errors, _ = crr.compile_results(research_dir)
    assert any("codes must match" in message for message in errors)
    assert set(entry["codes"]) <= set(missing)


def test_invalid_factor_kind_is_rejected(tmp_path):
    research_dir, manifest = _plan(tmp_path)
    entry = manifest["batches"][0]
    payload = _result_for(entry)
    payload["items"][0]["factor_kind"] = "推測"
    _write_result(research_dir, entry, payload)

    _, _, _, errors, _ = crr.compile_results(research_dir)
    assert any("factor_kind" in message for message in errors)


def test_empty_factor_is_rejected(tmp_path):
    research_dir, manifest = _plan(tmp_path)
    entry = manifest["batches"][0]
    payload = _result_for(entry)
    payload["items"][0]["factor"] = "   "
    _write_result(research_dir, entry, payload)

    _, _, _, errors, _ = crr.compile_results(research_dir)
    assert any("factor must be a non-empty string" in message for message in errors)


def test_incomplete_checks_are_rejected(tmp_path):
    research_dir, manifest = _plan(tmp_path)
    entry = manifest["batches"][0]
    payload = _result_for(entry)
    payload["items"][0]["checks"] = {"disclosures": "done"}
    _write_result(research_dir, entry, payload)

    _, _, _, errors, _ = crr.compile_results(research_dir)
    assert any("checks must have exactly" in message for message in errors)


def test_unresolved_items_are_accepted_but_reported(tmp_path):
    """材料未確認は許容する（factor は埋まっている）。空欄で配信しないことが要件。"""
    research_dir, manifest = _plan(tmp_path)
    _write_all(research_dir, manifest, status="unresolved")

    entries, missing, unresolved, errors, _ = crr.compile_results(research_dir)
    assert errors == [] and missing == []
    assert set(unresolved) == {e["code"] for e in entries}

    out = tmp_path / "factors.json"
    assert crr.main(["--research-dir", research_dir, "--out", str(out)]) == 0


def test_inline_factors_are_merged(tmp_path):
    rows = [_row("1234", disclosures=[{"time": "16:00", "title": "決算短信",
                                       "pdf_url": "https://tdnet.example/1.pdf"}]),
            _row("5678")]
    research_dir, manifest = _plan(tmp_path, rows)
    assert manifest["inline_codes"] == ["1234"]
    _write_all(research_dir, manifest)

    inline_path = tmp_path / "inline_factors.json"
    inline_path.write_text(json.dumps([{
        "code": "1234", "factor": "決算が市場予想を上回ったことを好感した買いである。",
        "factor_kind": "開示",
    }], ensure_ascii=False), encoding="utf-8")

    out = tmp_path / "factors.json"
    assert crr.main(["--research-dir", research_dir, "--out", str(out),
                     "--inline", str(inline_path)]) == 0
    entries = json.loads(out.read_text(encoding="utf-8"))
    assert [e["code"] for e in entries] == ["1234", "5678"]
    assert entries[0]["factor_kind"] == "開示"


def test_output_is_a_list_merge_factors_can_consume(tmp_path):
    research_dir, manifest = _plan(tmp_path)
    _write_all(research_dir, manifest)
    out = tmp_path / "factors.json"
    assert crr.main(["--research-dir", research_dir, "--out", str(out)]) == 0

    entries = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(entries, list)
    for entry in entries:
        assert entry["factor_kind"] in {"開示", "報道", "テーマ"}
        assert entry["factor"].strip()
