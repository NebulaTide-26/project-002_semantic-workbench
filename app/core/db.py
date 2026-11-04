"""SQLite 基础设施：连接、建表、迁移、备份。

这里只做「盖房子」，不写任何业务查询（那属于 repo.py）。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL DEFAULT '',
    work_dir        TEXT NOT NULL DEFAULT '',
    maximize        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    last_entered_at TEXT,
    last_left_at    TEXT
);

CREATE TABLE IF NOT EXISTS resources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('url', 'file', 'folder', 'app')),
    target      TEXT NOT NULL,
    args        TEXT NOT NULL DEFAULT '[]',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_resources_project ON resources(project_id);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER,
    type        TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    ts          TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """打开数据库连接。路径必须已经由调用方确保可用。"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # 单用户桌面程序；DELETE 日志对云同步盘更友好（见 v0.1 范围说明）
    conn.execute("PRAGMA journal_mode = DELETE")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """按 user_version 逐级升级表结构。"""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"数据库版本 {version} 高于程序支持的版本 {SCHEMA_VERSION}，"
            "请使用更新版本的 Workbench 打开。"
        )

    # 全新数据库：直接按最新结构创建
    if version == 0:
        conn.executescript(_SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        return

    # v1 → v2：资源增加「启动时最大化」
    if version == 1:
        conn.execute(
            "ALTER TABLE resources ADD COLUMN maximize INTEGER NOT NULL DEFAULT 0"
        )
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
        version = 2

    # v2 → v3：最大化从「资源」提升到「项目」
    if version == 2:
        conn.execute(
            "ALTER TABLE projects ADD COLUMN maximize INTEGER NOT NULL DEFAULT 0"
        )
        # 只要有任一资源勾过最大化，就把项目标记为开启，尽量保住用户意图
        conn.execute(
            "UPDATE projects SET maximize = 1 WHERE id IN "
            "(SELECT DISTINCT project_id FROM resources WHERE maximize = 1)"
        )
        conn.execute("ALTER TABLE resources DROP COLUMN maximize")
        conn.execute("PRAGMA user_version = 3")
        conn.commit()


def open_database(db_path: Path) -> sqlite3.Connection:
    """连接 + 迁移。失败时关闭连接并把异常抛给调用方。"""
    conn = connect(db_path)
    try:
        migrate(conn)
    except Exception:
        conn.close()
        raise
    return conn


def backup(conn: sqlite3.Connection, backups_dir: Path, keep: int = 5) -> Path:
    """用 SQLite 自带备份接口复制一份数据库，保留最近 keep 份。"""
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backups_dir / f"workbench-{stamp}.db"
    n = 1
    while target.exists():
        n += 1
        target = backups_dir / f"workbench-{stamp}-{n}.db"

    dest = sqlite3.connect(str(target))
    try:
        conn.backup(dest)
    finally:
        dest.close()

    _prune(backups_dir, keep)
    return target


def _prune(backups_dir: Path, keep: int) -> None:
    if keep < 1:
        keep = 1
    files = sorted(
        backups_dir.glob("workbench-*.db"),
        key=lambda p: p.stat().st_mtime,
    )
    for old in files[:-keep]:
        try:
            old.unlink()
        except OSError:
            pass
