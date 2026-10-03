"""PTS変動要因の表示品質を公開前に検査する（ネット接続・データ変更なし）。

python scripts/validate_ranking_quality.py docs/tmp/ranking.json
exit 0: 全行合格 / exit 1: 構造・執筆規律違反または入力エラー。
出典の事実確認は親・調査エージェントが行い、本検査はその代替にしない。
"""
import argparse
import json
import re
import sys
import unicodedata

from html_generator import _MD_LINK_RE

FACTOR_MAX_CHARS = 250
VALID_KINDS = {"開示", "報道", "テーマ"}
UNRESOLVED_TEXT = "当日固有の材料は確認できず"
JARGON_TERMS = ("材料窓", "窓内", "窓外")
_INTERNAL_CODE_RE = re.compile(
    r"\bs33\s*[:：]\s*\d+|業種コード"
    r"|(?<![A-Za-z0-9_])(?:sec17|sec33|pct5|turnover_m|turnover_yen|mcap_oku"
    r"|mcap_source|mcap_method|factor_kind|shoutfy_jq|cur_end|leader_code|leader_basis"
    r"|cluster_id|material_window|end_exclusive|kabutan_news)(?![A-Za-z0-9_])")
_ABSENCE_RE = re.compile(
    r"(?:適時開示|新規開示|個別開示|開示|新規材料|個別材料|固有の材料)"
    r"[^。]{0,20}(?:なし|無し|ない|無い|確認できず|確認できない|確認されず|見当たらない)"
    r"|材料未確認|材料(?:は|を)?確認でき(?:ず|ない)")
# 海外企業名の非標準カタカナ表記と、日経など主要メディアの定着表記。英語の一次情報だけを読んで
# 社名を自前で音訳すると生じる（2026-10-02 Micron→ミクロン、07-21 SK Hynix→ハイニクス）。
# ミクロンは単位の外来語と同じ綴りなので、国内上場社名（ミクロン精密・ホソカワミクロン、
# 株探略称ホソミクロン）と単位の用例は除外する。
NONSTANDARD_NAMES = (
    (re.compile(r"(?<!ホソカワ)(?<!ホソ)(?<![0-9.数十百千サブ])ミクロン(?!精密|単位|メートル|オーダー)"),
     "米マイクロン（Micron Technology）"),
    (re.compile(r"ハイニクス"), "SKハイニックス"),
    (re.compile(r"エヌヴィディア|エヌヴィデア|エヌビデア"), "エヌビディア"),
    (re.compile(r"サムソン電子"), "サムスン電子"),
)


def factor_display_text(factor):
    """実際にリンク化されるURLだけを除き、表示ラベルを字数に含める。"""
    return _MD_LINK_RE.sub(lambda match: match.group(1), factor).strip()


def audit_ranking(data):
    """銘柄コード・rule_id・messageを持つfinding配列を返す純粋関数。"""
    findings = []

    def add(code, rule_id, message):
        findings.append({"code": str(code), "rule_id": rule_id, "message": message})

    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        add("—", "RANK_STRUCTURE", "rows 配列が必要")
        return findings
    for row in data["rows"]:
        if not isinstance(row, dict):
            add("—", "RANK_STRUCTURE", "各 row はオブジェクトであること")
            continue
        code = row.get("code") or "—"
        kind = row.get("factor_kind")
        if not isinstance(kind, str) or kind not in VALID_KINDS:
            add(code, "RANK_FACTOR_KIND", "factor_kind は 開示/報道/テーマ のいずれか")
        factor = row.get("factor")
        if not isinstance(factor, str) or not factor.strip():
            add(code, "RANK_FACTOR_REQUIRED", "factor が空または文字列でない")
            continue
        displayed = factor_display_text(factor)
        if not displayed:
            add(code, "RANK_FACTOR_REQUIRED", "factor の表示本文が空")
            continue
        if len(displayed) > FACTOR_MAX_CHARS:
            add(code, "RANK_FACTOR_TOO_LONG", f"表示{len(displayed)}字（上限{FACTOR_MAX_CHARS}字）")
        text = unicodedata.normalize("NFKC", displayed)
        if any(term in text for term in JARGON_TERMS):
            add(code, "RANK_FACTOR_JARGON", "材料窓・窓内・窓外は日付・時刻に置き換える")
        if _INTERNAL_CODE_RE.search(text):
            add(code, "RANK_FACTOR_INTERNAL_CODE", "業種コード・内部フィールド名を表示しない")
        name = unicodedata.normalize("NFKC", str(row.get("name") or "")).strip()
        if name and re.match(r"^[「『]?" + re.escape(name) + r"[」』]?(?:は|が|の|[、,])", text):
            add(code, "RANK_FACTOR_SELF_NAME_OPENER", "書き出しの自社名を省き、要因から記す")
        for pattern, standard in NONSTANDARD_NAMES:
            found = pattern.search(text)
            if found:
                add(code, "RANK_FACTOR_NOTATION",
                    f"「{found.group(0)}」は一般的でない表記。{standard}と書く（英語社名を自前で音訳しない）")
        # PTS方法論の誠実な未確認表記は、テーマの冒頭1文に限り例外とする。
        absence_text = text
        if kind == "テーマ" and (text == UNRESOLVED_TEXT or text.startswith(UNRESOLVED_TEXT + "。")):
            absence_text = text[len(UNRESOLVED_TEXT):]
        if _ABSENCE_RE.search(absence_text):
            add(code, "RANK_FACTOR_ABSENCE", "開示不在の定型注記を省く。未確認はテーマで所定の一文を使う")
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ranking_json")
    args = parser.parse_args(argv)
    try:
        with open(args.ranking_json, encoding="utf-8") as handle:
            findings = audit_ranking(json.load(handle))
    except (OSError, ValueError) as exc:
        print(f"[quality] ERROR: {exc}", file=sys.stderr)
        return 1
    for item in findings:
        print(f"[quality] {item['code']} {item['rule_id']}: {item['message']}", file=sys.stderr)
    if findings:
        return 1
    print("[quality] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
