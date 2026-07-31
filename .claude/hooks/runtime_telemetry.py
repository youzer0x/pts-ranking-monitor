#!/usr/bin/env python3
"""日次ルーチンの消費を計測する Claude フック（＋集計 CLI）。

構造削減（バッチ化・圧縮・予算台帳）の効果を数値で確認するためのもの。
サブエージェント起動数と WebSearch/WebFetch 回数が主な観測対象で、
これが `specs/PIPELINE_ARCHITECTURE.md` の受入基準の検証材料になる。

引数なしで実行すると stdin の hook payload を読んで1行追記する。
**stdout には何も書かない**（モデルのコンテキストへ注入しないため。診断は stderr）。

  python .claude/hooks/runtime_telemetry.py            # フック本体
  python .claude/hooks/runtime_telemetry.py summary    # 直近セッションの集計

記録先は `.work/telemetry/<YYYY-MM-DD>.jsonl`（.gitignore 済み）。
観測がパイプラインを止めてはならないので、例外は握りつぶす。
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TELEMETRY_DIR = os.path.join(ROOT, ".work", "telemetry")

# 実トークン値が payload にあれば使い、無ければ文字数を proxy にする。
_TOKEN_KEYS = ("input_tokens", "output_tokens", "total_tokens")


def _size_of(value):
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    try:
        return len(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        return 0


def event_from_hook(payload, env=None):
    """hook payload を1行分のイベントに落とす。"""
    env = env or {}
    if not isinstance(payload, dict):
        payload = {}
    event = {
        "ts": datetime.now(JST).isoformat(timespec="seconds"),
        "event": payload.get("hook_event_name") or "unknown",
        "session_id": payload.get("session_id"),
    }
    for key in ("tool_name", "agent_type", "subagent_type", "agent_name"):
        if payload.get(key):
            event[key] = payload[key]
    usage = payload.get("usage")
    if isinstance(usage, dict):
        for key in _TOKEN_KEYS:
            if isinstance(usage.get(key), int):
                event[key] = usage[key]
    if not any(key in event for key in _TOKEN_KEYS):
        # proxy: 入出力の文字数。実トークンが取れない環境でも相対比較はできる。
        event["input_chars"] = _size_of(payload.get("tool_input"))
        event["output_chars"] = _size_of(payload.get("tool_response"))
    session = env.get("PTS_SESSION")
    if session:
        event["session_date"] = session
    return event


def append(event):
    os.makedirs(TELEMETRY_DIR, exist_ok=True)
    path = os.path.join(TELEMETRY_DIR, f"{datetime.now(JST):%Y-%m-%d}.jsonl")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return path


def _hook_main():
    try:
        payload = json.load(sys.stdin)
        event = event_from_hook(payload, os.environ)
        append(event)
        print(f"[pts-metrics] {event['event']} {event.get('tool_name') or ''}".rstrip(),
              file=sys.stderr)
    except Exception as exc:  # 観測がパイプラインを止めない
        print(f"[pts-metrics] logger_error={str(exc)[:200]}", file=sys.stderr)
    return 0


def summarize(path):
    counts, tokens = {}, 0
    subagents, web_calls = 0, 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = event.get("event", "unknown")
            counts[name] = counts.get(name, 0) + 1
            if name == "SubagentStart":
                subagents += 1
            if event.get("tool_name") in ("WebSearch", "WebFetch"):
                web_calls += 1
            for key in _TOKEN_KEYS:
                if isinstance(event.get(key), int):
                    tokens += event[key]
    return {"events": counts, "subagent_starts": subagents,
            "web_calls": web_calls, "tokens": tokens}


def _summary_main(argv):
    if argv:
        path = argv[0]
    else:
        try:
            files = sorted(f for f in os.listdir(TELEMETRY_DIR) if f.endswith(".jsonl"))
        except OSError:
            files = []
        if not files:
            print("no telemetry recorded", file=sys.stderr)
            return 1
        path = os.path.join(TELEMETRY_DIR, files[-1])
    print(json.dumps(summarize(path), ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "summary":
        return _summary_main(argv[1:])
    if argv:
        print(f"unknown command: {argv[0]}", file=sys.stderr)
        return 2
    return _hook_main()


if __name__ == "__main__":
    raise SystemExit(main())
