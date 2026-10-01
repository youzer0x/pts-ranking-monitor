import copy
import json

import pytest

import validate_ranking_quality as quality


def document(factor="9/30引け後の上方修正を好感した買いである。", kind="開示", name="テスト銘柄"):
    return {"rows": [{"code": "1234", "name": name, "factor": factor, "factor_kind": kind}]}


def rules(data):
    return {item["rule_id"] for item in quality.audit_ranking(data)}


def test_length_limit_and_link_labels():
    assert quality.audit_ranking(document("あ" * 250)) == []
    assert rules(document("あ" * 251)) == {"RANK_FACTOR_TOO_LONG"}
    factor = "あ" * 248 + "[日経](https://example.com/" + "a" * 400 + ")"
    assert len(quality.factor_display_text(factor)) == 250
    assert quality.audit_ranking(document(factor)) == []


@pytest.mark.parametrize("factor,rule", [
    ("材料窓内のニュースを好感した。", "RANK_FACTOR_JARGON"),
    ("窓外の決算が背景である。", "RANK_FACTOR_JARGON"),
    ("電気機器(s33:3650)に買いが入った。", "RANK_FACTOR_INTERNAL_CODE"),
    ("上昇率pct5を評価した買いである。", "RANK_FACTOR_INTERNAL_CODE"),
    ("kabutan_newsの報道を好感した。", "RANK_FACTOR_INTERNAL_CODE"),
    ("適時開示なし。半導体株に連れ高したとみられる。", "RANK_FACTOR_ABSENCE"),
    ("当日15:30以降の開示はない。", "RANK_FACTOR_ABSENCE"),
    ("個別材料は確認できず。", "RANK_FACTOR_ABSENCE"),
    ("テスト銘柄は上方修正を発表した。", "RANK_FACTOR_SELF_NAME_OPENER"),
    ("「テスト銘柄」が上方修正を発表した。", "RANK_FACTOR_SELF_NAME_OPENER"),
])
def test_editorial_rules(factor, rule):
    assert rule in rules(document(factor))


@pytest.mark.parametrize("factor", [
    "9/30引け後の上方修正を好感した買いである。",
    "窓を開けて上昇した。",
    "同業の企業[3350]の大口受注が材料視された。",
    "受注拡大を受けてテスト銘柄に買いが入った。",
])
def test_valid_wording_is_not_flagged(factor):
    assert quality.audit_ranking(document(factor)) == []


def test_self_name_normalizes_full_width():
    assert "RANK_FACTOR_SELF_NAME_OPENER" in rules(document("AGCは受注を発表した。", name="ＡＧＣ"))


def test_unresolved_exception_is_limited_to_theme_first_sentence():
    text = quality.UNRESOLVED_TEXT
    assert quality.audit_ranking(document(text, "テーマ")) == []
    assert quality.audit_ranking(document(text + "。9/29の決算以来の上昇が続いている。", "テーマ")) == []
    for factor, kind in [(text, "報道"), (text, "開示"),
                         ("買いが入った。" + text, "テーマ"),
                         (text + "。適時開示なし。", "テーマ")]:
        assert "RANK_FACTOR_ABSENCE" in rules(document(factor, kind))


@pytest.mark.parametrize("data,rule", [
    ({}, "RANK_STRUCTURE"), ({"rows": {}}, "RANK_STRUCTURE"),
    ({"rows": [None]}, "RANK_STRUCTURE"),
    (document(""), "RANK_FACTOR_REQUIRED"),
    (document(None), "RANK_FACTOR_REQUIRED"),
    (document("[ ](https://example.com/article)"), "RANK_FACTOR_REQUIRED"),
    (document(kind="確認不可"), "RANK_FACTOR_KIND"),
    (document(kind=[]), "RANK_FACTOR_KIND"),
])
def test_invalid_input(data, rule):
    assert rule in rules(data)


def test_validation_does_not_mutate_and_empty_ranking_is_valid():
    data = document()
    original = copy.deepcopy(data)
    assert quality.audit_ranking(data) == []
    assert data == original
    assert quality.audit_ranking({"rows": []}) == []


def test_cli_reports_codes_and_fails_without_rewriting(tmp_path, capsys):
    path = tmp_path / "ranking.json"
    original = json.dumps(document("あ" * 251), ensure_ascii=False)
    path.write_text(original, encoding="utf-8")
    assert quality.main([str(path)]) == 1
    assert "1234 RANK_FACTOR_TOO_LONG" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == original
    path.write_text(json.dumps(document()), encoding="utf-8")
    assert quality.main([str(path)]) == 0
    path.write_text("{", encoding="utf-8")
    assert quality.main([str(path)]) == 1
    assert quality.main([str(tmp_path / "missing")]) == 1
