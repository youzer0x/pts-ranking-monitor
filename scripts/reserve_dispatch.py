"""Stage2 の委譲1回分を manifest の予算に対して予約する。

manifest.json が「このセッションで何回サブエージェントを起動してよいか」の単一の真実源。
`reserve` はプロセス間ミューテックスの下で予約台帳を加算するので、並行委譲でも
per_batch / total の上限を超えられない。**親は各委譲の直前に必ずこれを実行し、
exit 0 以外なら委譲せずに停止する。** これによりモデルの判断と無関係に総起動数が頭打ちになる。

exit code:
  0 予約成功 / 1 IO・パースエラー / 3 予算枯渇（書き込みなし） / 4 誤用（未知 batch・pending 以外）

usage:
  python scripts/reserve_dispatch.py --research-dir .work/<SESSION>/research --batch batch-001
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_research_plan import PER_BATCH_DISPATCH_LIMIT, TOTAL_DISPATCH_LIMIT

LOCK_TIMEOUT_S = 5.0
LOCK_STALE_S = 30.0


def _acquire_lock(lock):
    """mkdir ベースのプロセス間ミューテックスを取る。"""
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            os.mkdir(lock)
            return
        except (FileExistsError, PermissionError):
            # Windows は create/remove の競合を ACCESS_DENIED で返すことがある。
            try:
                if time.time() - os.stat(lock).st_mtime >= LOCK_STALE_S:
                    os.rmdir(lock)  # 異常終了で取り残されたロックを壊す
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError(f"reserve lock timed out: {lock}")
            time.sleep(0.005)


def _release_lock(lock):
    try:
        os.rmdir(lock)
    except FileNotFoundError:
        pass


def _count(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def reserve(research_dir, batch_id):
    """batch_id の委譲1回分を原子的に予約し、exit code を返す。"""
    manifest_path = os.path.join(research_dir, "manifest.json")
    lock = manifest_path + ".reserve-lock"
    _acquire_lock(lock)
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        if not isinstance(manifest, dict):
            raise ValueError("manifest root must be an object")

        budget = manifest.get("dispatch_budget")
        if not isinstance(budget, dict):
            budget = {}
        per_batch_limit = _count(budget.get("per_batch_limit", PER_BATCH_DISPATCH_LIMIT),
                                 "dispatch_budget.per_batch_limit")
        total_limit = _count(budget.get("total_limit", TOTAL_DISPATCH_LIMIT),
                             "dispatch_budget.total_limit")

        entry = next((item for item in manifest.get("batches") or []
                      if isinstance(item, dict) and item.get("batch_id") == batch_id), None)
        if entry is None or entry.get("status") != "pending":
            reason = "unknown batch" if entry is None else f"status={entry.get('status')}"
            print(f"[reserve_dispatch] REFUSED {batch_id}: {reason}", file=sys.stderr)
            return 4

        ledger = manifest.get("ledger")
        if not isinstance(ledger, dict):
            ledger = {}
        reservations = ledger.get("reservations")
        if not isinstance(reservations, dict):
            reservations = {}
        attempts = _count(reservations.get(batch_id, 0), f"ledger.reservations.{batch_id}")
        total = _count(ledger.get("total_reserved", 0), "ledger.total_reserved")

        if attempts + 1 > per_batch_limit or total + 1 > total_limit:
            print(f"[reserve_dispatch] EXHAUSTED {batch_id}: "
                  f"attempts={attempts}/{per_batch_limit} total={total}/{total_limit}",
                  file=sys.stderr)
            return 3

        reservations[batch_id] = attempts + 1
        ledger["reservations"] = reservations
        ledger["total_reserved"] = total + 1
        manifest["ledger"] = ledger

        tmp = manifest_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(manifest, ensure_ascii=False, indent=2))
        os.replace(tmp, manifest_path)

        print(f"[reserve_dispatch] OK {batch_id} attempt={attempts + 1} "
              f"total={total + 1}/{total_limit}")
        return 0
    finally:
        _release_lock(lock)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Stage2 の委譲1回分を予算に対して予約する")
    ap.add_argument("--research-dir", required=True, help="manifest.json のあるディレクトリ")
    ap.add_argument("--batch", required=True, help="バッチ ID（例 batch-003）")
    args = ap.parse_args(argv)
    try:
        return reserve(args.research_dir, args.batch)
    except (OSError, ValueError, TimeoutError) as exc:
        print(f"[reserve_dispatch] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
