"""Stage2 の返却 JSON を検証して docs/tmp/factors.json へ機械的に平坦化する。

親エージェントが返却 JSON を自分のコンテキストで組み立て直す作業をなくすためのスクリプト。
サブエージェントの結果（results/batch-00N.json）と、親が開示だけで起こしたインライン分
（--inline）を突き合わせ、merge_factors.py が食える JSON 配列を書く。

検証に通ったバッチは manifest の status を complete にする。以降 reserve_dispatch.py は
そのバッチの再委譲を拒否する（pending 以外は exit 4）ので、二重調査で予算を使わない。

exit code:
  0 全コード充足 / 1 IO・構造エラー / 3 未充足（該当バッチの再委譲が必要）

usage:
  python scripts/compile_research_results.py --research-dir .work/<SESSION>/research \
      --out docs/tmp/factors.json [--inline docs/tmp/inline_factors.json]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_research_plan import CHECK_NAMES, RESULT_SCHEMA_VERSION

VALID_FACTOR_KINDS = {"開示", "報道", "テーマ"}
VALID_STATUSES = {"complete", "unresolved"}


def _clean_entry(item, label, errors):
    """返却 item を {code,factor,factor_kind,sources} に正規化する。不正なら None。"""
    if not isinstance(item, dict):
        errors.append(f"{label}: item must be an object")
        return None
    code = str(item.get("code") or "").strip()
    if not code:
        errors.append(f"{label}: code is required")
        return None
    factor = item.get("factor")
    if not isinstance(factor, str) or not factor.strip():
        errors.append(f"{label}[{code}]: factor must be a non-empty string")
        return None
    kind = str(item.get("factor_kind") or "").strip()
    if kind not in VALID_FACTOR_KINDS:
        errors.append(f"{label}[{code}]: factor_kind must be one of {sorted(VALID_FACTOR_KINDS)}")
        return None
    sources = item.get("sources")
    if sources is not None and not isinstance(sources, list):
        errors.append(f"{label}[{code}]: sources must be a list")
        return None
    entry = {"code": code, "factor": factor.strip(), "factor_kind": kind}
    if sources:
        entry["sources"] = sources
    return entry


def _validate_result(result, batch_entry, errors):
    """バッチ返却 JSON 全体を検証し、正規化済み entry のリストを返す。不正なら None。"""
    batch_id = batch_entry["batch_id"]
    if not isinstance(result, dict):
        errors.append(f"{batch_id}: result root must be an object")
        return None
    if result.get("schema_version") != RESULT_SCHEMA_VERSION:
        errors.append(f"{batch_id}: schema_version must be {RESULT_SCHEMA_VERSION}")
        return None
    if str(result.get("batch_id") or "").strip() != batch_id:
        errors.append(f"{batch_id}: batch_id mismatch")
        return None
    if str(result.get("input_digest") or "").strip() != batch_entry["input_digest"]:
        # 入力が変わったのに古い結果が残っている＝内容の対応が取れない。
        errors.append(f"{batch_id}: input_digest mismatch (stale result)")
        return None
    items = result.get("items")
    if not isinstance(items, list):
        errors.append(f"{batch_id}: items must be a list")
        return None

    entries, seen, unresolved = [], [], []
    for item in items:
        entry = _clean_entry(item, batch_id, errors)
        if entry is None:
            return None
        status = str(item.get("status") or "").strip()
        if status not in VALID_STATUSES:
            errors.append(f"{batch_id}[{entry['code']}]: status must be one of "
                          f"{sorted(VALID_STATUSES)}")
            return None
        checks = item.get("checks")
        if not isinstance(checks, dict) or set(checks) != set(CHECK_NAMES):
            errors.append(f"{batch_id}[{entry['code']}]: checks must have exactly "
                          f"{list(CHECK_NAMES)}")
            return None
        if status == "unresolved":
            unresolved.append(entry["code"])
        seen.append(entry["code"])
        entries.append(entry)

    expected = list(batch_entry.get("codes") or [])
    if len(seen) != len(set(seen)) or set(seen) != set(expected):
        errors.append(f"{batch_id}: codes must match the batch exactly "
                      f"(expected {sorted(expected)}, got {sorted(set(seen))})")
        return None
    return entries, unresolved


def compile_results(research_dir, inline_path=None):
    """(entries, missing_codes, unresolved_codes, errors, manifest) を返す。"""
    manifest_path = os.path.join(research_dir, "manifest.json")
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ValueError("manifest root must be an object")

    errors, by_code, unresolved = [], {}, []

    for batch_entry in manifest.get("batches") or []:
        result_path = os.path.join(research_dir, batch_entry["result_path"])
        try:
            with open(result_path, encoding="utf-8") as handle:
                result = json.load(handle)
        except FileNotFoundError:
            continue  # 未委譲・未返却。下の未充足判定で拾う。
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{batch_entry['batch_id']}: {exc}")
            batch_entry["status"] = "invalid"
            continue
        validated = _validate_result(result, batch_entry, errors)
        if validated is None:
            batch_entry["status"] = "invalid"
            continue
        entries, batch_unresolved = validated
        for entry in entries:
            by_code[entry["code"]] = entry
        unresolved.extend(batch_unresolved)
        batch_entry["status"] = "complete"

    if inline_path and os.path.exists(inline_path):
        with open(inline_path, encoding="utf-8") as handle:
            inline = json.load(handle)
        if not isinstance(inline, list):
            raise ValueError("inline factors must be a JSON array")
        for item in inline:
            entry = _clean_entry(item, "inline", errors)
            if entry is not None:
                by_code[entry["code"]] = entry

    ranking_codes = [str(c).strip() for c in manifest.get("ranking_codes") or []]
    missing = [code for code in ranking_codes if code not in by_code]
    entries = [by_code[code] for code in ranking_codes if code in by_code]
    # ranking に無い code が混ざっていても merge_factors 側で REJECTED になるが、
    # ここで落としておけば無駄な差分を出さない。
    return entries, missing, unresolved, errors, manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description="Stage2 の返却を factors.json へ集約する")
    ap.add_argument("--research-dir", required=True, help="manifest.json のあるディレクトリ")
    ap.add_argument("--out", required=True, help="出力する factors.json のパス")
    ap.add_argument("--inline", help="親がインラインで起こした factor の JSON 配列")
    args = ap.parse_args(argv)

    try:
        entries, missing, unresolved, errors, manifest = compile_results(
            args.research_dir, args.inline)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[compile_research_results] ERROR: {exc}", file=sys.stderr)
        return 1

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(entries, ensure_ascii=False, indent=2))
    os.replace(tmp, args.out)

    # 検証結果を manifest へ書き戻す（complete なバッチは再委譲されなくなる）。
    manifest_path = os.path.join(args.research_dir, "manifest.json")
    tmp_manifest = manifest_path + ".tmp"
    with open(tmp_manifest, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2))
    os.replace(tmp_manifest, manifest_path)

    for message in errors:
        print(f"[compile_research_results] INVALID {message}", file=sys.stderr)
    for code in unresolved:
        print(f"[compile_research_results] UNRESOLVED {code}", file=sys.stderr)
    print(f"[compile_research_results] COMPILED {len(entries)}/"
          f"{len(manifest.get('ranking_codes') or [])} -> {args.out}", file=sys.stderr)
    if missing:
        print(f"[compile_research_results] MISSING {' '.join(missing)}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
