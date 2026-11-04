from __future__ import annotations

import sqlite3

import pytest

from app.core import db

_V1_SCHEMA = """
CREATE TABLE projects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL DEFAULT '',
    work_dir        TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    last_entered_at TEXT,
    last_left_at    TEXT
);

CREATE TABLE resources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('url', 'file', 'folder', 'app')),
    target      TEXT NOT NULL,
    args        TEXT NOT NULL DEFAULT '[]',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER,
    type        TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    ts          TEXT NOT NULL
);
"""


def test_open_database_creates_schema(tmp_path):
    conn = db.open_database(tmp_path / "workbench.db")
    try:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"projects", "resources", "events"} <= tables
        assert (
            conn.execute("PRAGMA user_version").fetchone()[0]
            == db.SCHEMA_VERSION
        )
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        project_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(projects)")
        }
        resource_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(resources)")
        }
        assert "maximize" in project_columns
        assert "maximize" not in resource_columns
    finally:
        conn.close()


def test_open_database_is_idempotent(tmp_path):
    path = tmp_path / "workbench.db"
    db.open_database(path).close()

    conn = db.open_database(path)
    try:
        assert (
            conn.execute("PRAGMA user_version").fetchone()[0]
            == db.SCHEMA_VERSION
        )
    finally:
        conn.close()


def test_migrate_v1_to_v3_preserves_resources(tmp_path):
    path = tmp_path / "workbench.db"
    raw = sqlite3.connect(path)
    raw.executescript(_V1_SCHEMA)
    raw.execute(
        "INSERT INTO projects (name, created_at) VALUES ('P', '2026-01-01')"
    )
    raw.execute(
        "INSERT INTO resources (project_id, kind, target) "
        "VALUES (1, 'url', 'https://example.com')"
    )
    raw.execute("PRAGMA user_version = 1")
    raw.commit()
    raw.close()

    conn = db.open_database(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        project = conn.execute("SELECT * FROM projects").fetchone()
        assert project is not None and project["maximize"] == 0
        row = conn.execute("SELECT * FROM resources").fetchone()
        assert row is not None
        assert row["target"] == "https://example.com"
        columns = {
            item["name"]
            for item in conn.execute("PRAGMA table_info(resources)")
        }
        assert "maximize" not in columns
    finally:
        conn.close()


def test_migrate_v2_to_v3_moves_maximize_to_project(tmp_path):
    path = tmp_path / "workbench.db"
    raw = sqlite3.connect(path)
    raw.executescript(_V1_SCHEMA)
    raw.execute(
        "INSERT INTO projects (name, created_at) VALUES ('P', '2026-01-01')"
    )
    raw.execute(
        "INSERT INTO resources (project_id, kind, target) "
        "VALUES (1, 'url', 'https://a.example')"
    )
    raw.execute(
        "INSERT INTO resources (project_id, kind, target) "
        "VALUES (1, 'file', 'D:/b.txt')"
    )
    raw.execute(
        "ALTER TABLE resources ADD COLUMN maximize INTEGER NOT NULL DEFAULT 0"
    )
    raw.execute("UPDATE resources SET maximize = 1 WHERE id = 1")
    raw.execute("PRAGMA user_version = 2")
    raw.commit()
    raw.close()

    conn = db.open_database(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        project = conn.execute("SELECT * FROM projects WHERE id = 1").fetchone()
        assert project is not None and project["maximize"] == 1
        assert conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0] == 2
        columns = {
            item["name"]
            for item in conn.execute("PRAGMA table_info(resources)")
        }
        assert "maximize" not in columns
    finally:
        conn.close()


def test_open_database_rejects_newer_version(tmp_path):
    path = tmp_path / "workbench.db"
    raw = sqlite3.connect(path)
    raw.execute("PRAGMA user_version = 99")
    raw.commit()
    raw.close()

    with pytest.raises(RuntimeError):
        db.open_database(path)


def test_backup_creates_and_prunes(tmp_path):
    conn = db.open_database(tmp_path / "workbench.db")
    backups = tmp_path / "backups"
    try:
        for _ in range(7):
            db.backup(conn, backups, keep=5)
    finally:
        conn.close()

    files = list(backups.glob("workbench-*.db"))
    assert len(files) == 5


def test_backup_file_is_readable_sqlite(tmp_path):
    conn = db.open_database(tmp_path / "workbench.db")
    try:
        target = db.backup(conn, tmp_path / "backups", keep=5)
    finally:
        conn.close()

    check = sqlite3.connect(target)
    try:
        assert (
            check.execute("PRAGMA user_version").fetchone()[0]
            == db.SCHEMA_VERSION
        )
    finally:
        check.close()
