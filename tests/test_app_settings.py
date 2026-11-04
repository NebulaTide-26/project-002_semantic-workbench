from __future__ import annotations

from pathlib import Path

import pytest

from app.core import app_settings


def _point_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "settings.json"
    monkeypatch.setattr(app_settings, "settings_path", lambda: path)
    return path


def test_load_missing_returns_empty(monkeypatch, tmp_path):
    _point_settings(monkeypatch, tmp_path)
    assert app_settings.load().data_dir is None


def test_save_and_load_roundtrip(monkeypatch, tmp_path):
    _point_settings(monkeypatch, tmp_path)
    target = str(tmp_path / "数据目录")
    app_settings.save(app_settings.AppSettings(data_dir=target))
    assert app_settings.load().data_dir == target


def test_save_leaves_no_tmp_file(monkeypatch, tmp_path):
    _point_settings(monkeypatch, tmp_path)
    app_settings.save(app_settings.AppSettings(data_dir=str(tmp_path)))
    assert not (tmp_path / "settings.json.tmp").exists()


def test_corrupt_settings_raises(monkeypatch, tmp_path):
    path = _point_settings(monkeypatch, tmp_path)
    path.write_text("{ 这不是 JSON", encoding="utf-8")
    with pytest.raises(app_settings.SettingsError):
        app_settings.load()


def test_inspect_missing(tmp_path):
    assert (
        app_settings.inspect_data_dir(tmp_path / "nope")
        is app_settings.DataDirState.MISSING
    )


def test_inspect_not_a_dir(tmp_path):
    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    assert (
        app_settings.inspect_data_dir(file_path)
        is app_settings.DataDirState.NOT_A_DIR
    )


def test_inspect_empty(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    assert (
        app_settings.inspect_data_dir(data) is app_settings.DataDirState.EMPTY
    )


def test_inspect_known_entries_without_db_is_missing_db(tmp_path):
    """删除 workbench.db 后，不能把剩下的 logs/backups/README 当成空目录。"""
    data = tmp_path / "data"
    data.mkdir()
    (data / "logs").mkdir()
    (data / "backups").mkdir()
    (data / "README.txt").write_text("x", encoding="utf-8")
    assert (
        app_settings.inspect_data_dir(data)
        is app_settings.DataDirState.MISSING_DB
    )


def test_inspect_ok_when_db_exists(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "workbench.db").write_bytes(b"")
    assert app_settings.inspect_data_dir(data) is app_settings.DataDirState.OK


def test_inspect_non_empty(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "photo.jpg").write_bytes(b"")
    assert (
        app_settings.inspect_data_dir(data)
        is app_settings.DataDirState.NON_EMPTY
    )


def test_ensure_initialized_is_idempotent(tmp_path):
    data = tmp_path / "data"
    app_settings.ensure_initialized(data)
    app_settings.ensure_initialized(data)

    assert (data / "logs").is_dir()
    assert (data / "backups").is_dir()
    assert (data / "README.txt").is_file()
    # 只建目录结构，不创建数据库
    assert not (data / "workbench.db").exists()
