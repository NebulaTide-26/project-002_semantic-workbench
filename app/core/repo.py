"""业务数据仓储层：所有针对 projects / resources 表的 SQL 都在这里。

负责两件事：
1. 执行增删改查；
2. 把 sqlite3.Row 转成 models 里的类型对象。

数据库错误统一翻译成这里的异常，UI 只处理有意义的业务错误。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from app.core.models import Project, Resource, ResourceKind


class RepoError(Exception):
    """仓储层错误的基类。"""


class DuplicateNameError(RepoError):
    """项目名已存在。"""


class NotFoundError(RepoError):
    """记录不存在。"""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _project_from_row(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        work_dir=row["work_dir"],
        maximize=bool(row["maximize"]),
        created_at=_parse_dt(row["created_at"]),
        last_entered_at=_parse_dt(row["last_entered_at"]),
        last_left_at=_parse_dt(row["last_left_at"]),
    )


def create_project(
    conn: sqlite3.Connection,
    name: str,
    description: str = "",
    work_dir: str = "",
    maximize: bool = False,
) -> Project:
    name = name.strip()
    if not name:
        raise ValueError("项目名不能为空")
    try:
        cur = conn.execute(
            "INSERT INTO projects "
            "(name, description, work_dir, maximize, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                name,
                description.strip(),
                work_dir.strip(),
                1 if maximize else 0,
                _now(),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise DuplicateNameError(f"项目「{name}」已存在") from exc
    conn.commit()

    project = get_project(conn, cur.lastrowid)
    assert project is not None
    return project


def list_projects(conn: sqlite3.Connection) -> list[Project]:
    rows = conn.execute(
        "SELECT * FROM projects ORDER BY name COLLATE NOCASE ASC"
    ).fetchall()
    return [_project_from_row(row) for row in rows]


def get_project(conn: sqlite3.Connection, project_id: int) -> Project | None:
    row = conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    return _project_from_row(row) if row else None


def update_project(conn: sqlite3.Connection, project: Project) -> None:
    if project.id is None:
        raise ValueError("更新项目时缺少 id")
    name = project.name.strip()
    if not name:
        raise ValueError("项目名不能为空")
    try:
        cur = conn.execute(
            "UPDATE projects SET name = ?, description = ?, work_dir = ?, "
            "maximize = ? WHERE id = ?",
            (
                name,
                project.description.strip(),
                project.work_dir.strip(),
                1 if project.maximize else 0,
                project.id,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise DuplicateNameError(f"项目「{name}」已存在") from exc
    if cur.rowcount == 0:
        raise NotFoundError(f"项目不存在：id={project.id}")
    conn.commit()


def set_project_maximize(
    conn: sqlite3.Connection, project_id: int, maximize: bool
) -> None:
    cur = conn.execute(
        "UPDATE projects SET maximize = ? WHERE id = ?",
        (1 if maximize else 0, project_id),
    )
    if cur.rowcount == 0:
        raise NotFoundError(f"项目不存在：id={project_id}")
    conn.commit()


def delete_project(conn: sqlite3.Connection, project_id: int) -> None:
    cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    if cur.rowcount == 0:
        raise NotFoundError(f"项目不存在：id={project_id}")
    conn.commit()


# --------------------------------------------------------------------- 资源


def _resource_from_row(row: sqlite3.Row) -> Resource:
    try:
        raw_args = json.loads(row["args"] or "[]")
    except json.JSONDecodeError:
        raw_args = []
    if not isinstance(raw_args, list):
        raw_args = []
    return Resource(
        id=row["id"],
        project_id=row["project_id"],
        kind=ResourceKind(row["kind"]),
        target=row["target"],
        args=[str(arg) for arg in raw_args],
        sort_order=row["sort_order"],
        enabled=bool(row["enabled"]),
    )


def list_resources(
    conn: sqlite3.Connection, project_id: int
) -> list[Resource]:
    rows = conn.execute(
        "SELECT * FROM resources WHERE project_id = ? "
        "ORDER BY sort_order ASC, id ASC",
        (project_id,),
    ).fetchall()
    return [_resource_from_row(row) for row in rows]


def get_resource(
    conn: sqlite3.Connection, resource_id: int
) -> Resource | None:
    row = conn.execute(
        "SELECT * FROM resources WHERE id = ?", (resource_id,)
    ).fetchone()
    return _resource_from_row(row) if row else None


def find_resource(
    conn: sqlite3.Connection,
    project_id: int,
    kind: ResourceKind,
    target: str,
) -> Resource | None:
    """查找同一项目里完全相同的资源（用于拦截重复添加）。"""
    row = conn.execute(
        "SELECT * FROM resources "
        "WHERE project_id = ? AND kind = ? AND target = ?",
        (project_id, kind.value, target.strip()),
    ).fetchone()
    return _resource_from_row(row) if row else None


def create_resource(
    conn: sqlite3.Connection,
    project_id: int,
    kind: ResourceKind,
    target: str,
) -> Resource:
    target = target.strip()
    if not target:
        raise ValueError("资源目标不能为空")

    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order "
        "FROM resources WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    next_order = row["next_order"]

    try:
        cur = conn.execute(
            "INSERT INTO resources "
            "(project_id, kind, target, args, sort_order, enabled) "
            "VALUES (?, ?, ?, '[]', ?, 1)",
            (project_id, kind.value, target, next_order),
        )
    except sqlite3.IntegrityError as exc:
        raise NotFoundError(f"项目不存在：id={project_id}") from exc
    conn.commit()

    resource = get_resource(conn, cur.lastrowid)
    assert resource is not None
    return resource


def update_resource(conn: sqlite3.Connection, resource: Resource) -> None:
    if resource.id is None:
        raise ValueError("更新资源时缺少 id")
    target = resource.target.strip()
    if not target:
        raise ValueError("资源目标不能为空")

    args_json = json.dumps(resource.args, ensure_ascii=False)
    cur = conn.execute(
        "UPDATE resources SET kind = ?, target = ?, args = ? WHERE id = ?",
        (resource.kind.value, target, args_json, resource.id),
    )
    if cur.rowcount == 0:
        raise NotFoundError(f"资源不存在：id={resource.id}")
    conn.commit()


def delete_resource(conn: sqlite3.Connection, resource_id: int) -> None:
    cur = conn.execute("DELETE FROM resources WHERE id = ?", (resource_id,))
    if cur.rowcount == 0:
        raise NotFoundError(f"资源不存在：id={resource_id}")
    conn.commit()


def set_resource_enabled(
    conn: sqlite3.Connection, resource_id: int, enabled: bool
) -> None:
    cur = conn.execute(
        "UPDATE resources SET enabled = ? WHERE id = ?",
        (1 if enabled else 0, resource_id),
    )
    if cur.rowcount == 0:
        raise NotFoundError(f"资源不存在：id={resource_id}")
    conn.commit()


def mark_project_entered(
    conn: sqlite3.Connection, project_id: int
) -> None:
    cur = conn.execute(
        "UPDATE projects SET last_entered_at = ? WHERE id = ?",
        (_now(), project_id),
    )
    if cur.rowcount == 0:
        raise NotFoundError(f"项目不存在：id={project_id}")
    conn.commit()


def add_event(
    conn: sqlite3.Connection,
    project_id: int | None,
    event_type: str,
    detail: str = "",
) -> None:
    conn.execute(
        "INSERT INTO events (project_id, type, detail, ts) VALUES (?, ?, ?, ?)",
        (project_id, event_type, detail, _now()),
    )
    conn.commit()


def move_resource(
    conn: sqlite3.Connection, resource_id: int, delta: int
) -> bool:
    """把资源上移/下移一格。返回是否真的移动了（到边界返回 False）。"""
    resource = get_resource(conn, resource_id)
    if resource is None:
        raise NotFoundError(f"资源不存在：id={resource_id}")

    items = list_resources(conn, resource.project_id)
    index = next(
        (i for i, item in enumerate(items) if item.id == resource_id), None
    )
    if index is None:
        raise NotFoundError(f"资源不存在：id={resource_id}")

    new_index = index + delta
    if new_index < 0 or new_index >= len(items):
        return False

    items[index], items[new_index] = items[new_index], items[index]
    for order, item in enumerate(items):
        conn.execute(
            "UPDATE resources SET sort_order = ? WHERE id = ?",
            (order, item.id),
        )
    conn.commit()
    return True
