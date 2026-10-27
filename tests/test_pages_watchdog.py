import json
from datetime import datetime, timezone

import pytest

import pages_watchdog
from pages_watchdog import BUILT_STALE_AFTER, STUCK_AFTER, decide


def test_live_matches_or_newer_is_ok_regardless_of_build():
    assert decide("2026-10-27", "2026-10-27", "errored", 99999) == "ok"
    assert decide("2026-10-27", "2026-10-28", None, 0) == "ok"


def test_stuck_building_triggers_rebuild_only_after_threshold():
    # 2026-10-27 分の事故：building のまま 1 時間以上止まっていた
    assert decide("2026-10-27", "2026-10-26", "building", STUCK_AFTER - 1) == "wait"
    assert decide("2026-10-27", "2026-10-26", "building", STUCK_AFTER) == "rebuild"
    assert decide("2026-10-27", "2026-10-26", "queued", STUCK_AFTER) == "rebuild"


def test_errored_build_triggers_rebuild_immediately():
    assert decide("2026-10-27", "2026-10-26", "errored", 0) == "rebuild"


def test_built_but_stale_waits_for_cdn_cache_then_rebuilds():
    assert decide("2026-10-27", "2026-10-26", "built", BUILT_STALE_AFTER - 1) == "wait"
    assert decide("2026-10-27", "2026-10-26", "built", BUILT_STALE_AFTER) == "rebuild"


def test_unknown_live_or_build_status_waits():
    assert decide("2026-10-27", None, None, 0) == "wait"
    assert decide("2026-10-27", None, "building", 10) == "wait"


def test_build_age_parses_github_timestamp():
    now = datetime(2026, 10, 27, 22, 46, 1, tzinfo=timezone.utc)
    assert pages_watchdog.build_age("2026-10-27T21:33:01Z", now) == 4380


def test_expected_newest_reads_manifest_head(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"dates": ["2026-10-27", "2026-10-26"]}))
    assert pages_watchdog.expected_newest(str(tmp_path)) == "2026-10-27"


def test_expected_newest_rejects_empty_manifest(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"dates": []}))
    with pytest.raises(SystemExit):
        pages_watchdog.expected_newest(str(tmp_path))


def _run_main(monkeypatch, tmp_path, lives, builds, argv=("--interval", "0", "--max-wait", "0")):
    monkeypatch.setattr(pages_watchdog, "expected_newest", lambda: "2026-10-27")
    monkeypatch.setattr(pages_watchdog, "pages_url", lambda: "https://example.github.io/x/")
    lives, builds, posts = iter(lives), iter(builds), []
    monkeypatch.setattr(pages_watchdog, "live_newest", lambda base: next(lives))
    monkeypatch.setattr(pages_watchdog, "latest_build", lambda: next(builds))
    monkeypatch.setattr(pages_watchdog, "github_api", lambda method, path: posts.append((method, path)))
    clock = iter(range(0, 10_000, 20))  # 1回の確認ごとに 20 秒進む擬似時計
    monkeypatch.setattr(pages_watchdog.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(pages_watchdog.time, "sleep", lambda s: None)
    monkeypatch.setattr("sys.argv", ["pages_watchdog.py", *argv])
    return pages_watchdog.main(), posts


def test_main_returns_0_without_rebuild_when_live(monkeypatch, tmp_path):
    rc, posts = _run_main(monkeypatch, tmp_path, ["2026-10-27"], [("built", 30)])
    assert rc == 0 and posts == []


def test_main_requests_rebuild_for_stuck_build_and_fails_if_still_stale(monkeypatch, tmp_path):
    rc, posts = _run_main(monkeypatch, tmp_path, ["2026-10-26"], [("building", 4380)])
    assert rc == 1
    assert posts == [("POST", "/pages/builds")]


def test_main_recovers_after_rebuild(monkeypatch, tmp_path):
    rc, posts = _run_main(monkeypatch, tmp_path, ["2026-10-26", "2026-10-26", "2026-10-27"],
                          [("building", 4380), ("building", 20), ("built", 60)],
                          argv=("--interval", "0", "--max-wait", "60"))
    assert rc == 0
    assert posts == [("POST", "/pages/builds")]


def test_main_caps_rebuild_requests(monkeypatch, tmp_path):
    rc, posts = _run_main(monkeypatch, tmp_path, ["2026-10-26"] * 3, [("errored", 0)] * 3,
                          argv=("--interval", "0", "--max-wait", "60", "--max-rebuilds", "2"))
    assert rc == 1
    assert len(posts) == 2
