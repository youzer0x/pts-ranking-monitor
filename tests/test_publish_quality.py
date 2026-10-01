import json
import sys

import pytest

import publish


def test_publish_rejects_bad_factor_before_writing_or_sending(tmp_path, monkeypatch):
    path = tmp_path / "ranking.json"
    path.write_text(json.dumps({"session_date": "2026-10-01", "rows": [
        {"code": "1234", "name": "テスト", "factor": "あ" * 251, "factor_kind": "報道"}
    ]}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["publish.py", str(path)])
    monkeypatch.setattr(publish, "normalize_names", lambda data: None)
    for name in ("save_data", "cleanup_old", "update_manifest", "write_index"):
        monkeypatch.setattr(publish, name, lambda *a: pytest.fail("品質検査の失敗後に公開物を変更した"))
    with pytest.raises(SystemExit, match="quality check failed"):
        publish.main()


def test_valid_publish_writes_generated_files_without_email(tmp_path, monkeypatch):
    path = tmp_path / "ranking.json"
    data = {"session_date": "2026-10-01", "rows": [
        {"code": "1234", "name": "テスト", "factor": "当日固有の材料は確認できず", "factor_kind": "テーマ"}
    ]}
    path.write_text(json.dumps(data), encoding="utf-8")
    docs = tmp_path / "docs"
    monkeypatch.setattr(publish, "DOCS", str(docs))
    monkeypatch.setattr(publish, "DATA", str(docs / "data"))
    monkeypatch.setattr(publish, "normalize_names", lambda data: None)
    monkeypatch.setattr(publish, "cleanup_old", lambda: None)
    monkeypatch.setattr(sys, "argv", ["publish.py", str(path), "--no-email"])
    publish.main()
    assert json.loads((docs / "data/2026-10-01.json").read_text(encoding="utf-8")) == data
    assert json.loads((docs / "data/manifest.json").read_text())["dates"] == ["2026-10-01"]
    assert (docs / "index.html").read_text(encoding="utf-8") == publish.html_generator.generate_pages_html()
