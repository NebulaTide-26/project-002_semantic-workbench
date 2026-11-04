from __future__ import annotations

import pytest

from app.core import db, repo
from app.core.models import ResourceKind


@pytest.fixture
def conn(tmp_path):
    connection = db.open_database(tmp_path / "workbench.db")
    try:
        yield connection
    finally:
        connection.close()


def test_create_and_list_project(conn):
    project = repo.create_project(conn, "  计组实验  ", "LAB2", "D:\\lab")

    assert project.id is not None
    assert project.name == "计组实验"
    assert project.description == "LAB2"
    assert project.created_at is not None

    projects = repo.list_projects(conn)
    assert [p.name for p in projects] == ["计组实验"]


def test_create_empty_name_rejected(conn):
    with pytest.raises(ValueError):
        repo.create_project(conn, "   ")


def test_duplicate_name_rejected(conn):
    repo.create_project(conn, "OOPre")
    with pytest.raises(repo.DuplicateNameError):
        repo.create_project(conn, "OOPre")


def test_update_project(conn):
    project = repo.create_project(conn, "旧名字")
    project.name = "新名字"
    project.description = "说明"
    project.work_dir = "D:\\新目录"
    project.maximize = True

    repo.update_project(conn, project)

    loaded = repo.get_project(conn, project.id)
    assert loaded is not None
    assert (loaded.name, loaded.description, loaded.work_dir) == (
        "新名字",
        "说明",
        "D:\\新目录",
    )
    assert loaded.maximize is True


def test_update_missing_project_rejected(conn):
    project = repo.create_project(conn, "临时")
    project.id = 999
    with pytest.raises(repo.NotFoundError):
        repo.update_project(conn, project)


def test_delete_project_cascades_resources(conn):
    project = repo.create_project(conn, "带资源")
    conn.execute(
        "INSERT INTO resources (project_id, kind, target) "
        "VALUES (?, 'url', 'https://example.com')",
        (project.id,),
    )
    conn.commit()

    repo.delete_project(conn, project.id)

    assert repo.get_project(conn, project.id) is None
    assert conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0] == 0


def test_delete_missing_project_rejected(conn):
    with pytest.raises(repo.NotFoundError):
        repo.delete_project(conn, 999)


# ------------------------------------------------------------------ 资源


def test_create_and_list_resources_ordered(conn):
    project = repo.create_project(conn, "资源项目")
    first = repo.create_resource(
        conn, project.id, ResourceKind.URL, "  https://a.example  "
    )
    second = repo.create_resource(
        conn, project.id, ResourceKind.FOLDER, "D:\\数据"
    )

    resources = repo.list_resources(conn, project.id)
    assert [r.id for r in resources] == [first.id, second.id]
    assert resources[0].target == "https://a.example"
    assert [r.sort_order for r in resources] == [0, 1]


def test_find_resource(conn):
    project = repo.create_project(conn, "P")
    repo.create_resource(conn, project.id, ResourceKind.URL, "https://a.example")

    assert (
        repo.find_resource(
            conn, project.id, ResourceKind.URL, "https://a.example"
        )
        is not None
    )
    assert (
        repo.find_resource(conn, project.id, ResourceKind.FILE, "https://a.example")
        is None
    )


def test_create_resource_for_missing_project_rejected(conn):
    with pytest.raises(repo.NotFoundError):
        repo.create_resource(conn, 999, ResourceKind.URL, "https://a.example")


def test_update_resource(conn):
    project = repo.create_project(conn, "P")
    resource = repo.create_resource(
        conn, project.id, ResourceKind.FILE, "D:\\a.txt"
    )
    resource.kind = ResourceKind.FOLDER
    resource.target = "D:\\a"

    repo.update_resource(conn, resource)

    loaded = repo.get_resource(conn, resource.id)
    assert loaded is not None
    assert loaded.kind is ResourceKind.FOLDER
    assert loaded.target == "D:\\a"


def test_delete_resource(conn):
    project = repo.create_project(conn, "P")
    resource = repo.create_resource(
        conn, project.id, ResourceKind.URL, "https://a.example"
    )

    repo.delete_resource(conn, resource.id)

    assert repo.get_resource(conn, resource.id) is None
    with pytest.raises(repo.NotFoundError):
        repo.delete_resource(conn, resource.id)


def test_set_resource_enabled(conn):
    project = repo.create_project(conn, "P")
    resource = repo.create_resource(
        conn, project.id, ResourceKind.URL, "https://a.example"
    )

    repo.set_resource_enabled(conn, resource.id, False)

    loaded = repo.get_resource(conn, resource.id)
    assert loaded is not None and loaded.enabled is False


def test_create_project_with_maximize(conn):
    project = repo.create_project(conn, "P", maximize=True)

    loaded = repo.get_project(conn, project.id)
    assert loaded is not None
    assert loaded.maximize is True


def test_set_project_maximize(conn):
    project = repo.create_project(conn, "P")

    repo.set_project_maximize(conn, project.id, True)

    loaded = repo.get_project(conn, project.id)
    assert loaded is not None and loaded.maximize is True


def test_move_resource(conn):
    project = repo.create_project(conn, "P")
    first = repo.create_resource(conn, project.id, ResourceKind.URL, "https://a")
    second = repo.create_resource(conn, project.id, ResourceKind.URL, "https://b")
    third = repo.create_resource(conn, project.id, ResourceKind.URL, "https://c")

    assert repo.move_resource(conn, third.id, -1) is True
    ordered = repo.list_resources(conn, project.id)
    assert [r.id for r in ordered] == [first.id, third.id, second.id]
    assert [r.sort_order for r in ordered] == [0, 1, 2]

    # 边界：已经在最上面 / 最下面时不动
    assert repo.move_resource(conn, first.id, -1) is False
    assert repo.move_resource(conn, second.id, 1) is False


def test_move_missing_resource_rejected(conn):
    with pytest.raises(repo.NotFoundError):
        repo.move_resource(conn, 999, -1)


# ------------------------------------------------------------------ 事件


def test_mark_project_entered(conn):
    project = repo.create_project(conn, "P")
    assert repo.get_project(conn, project.id).last_entered_at is None

    repo.mark_project_entered(conn, project.id)

    assert repo.get_project(conn, project.id).last_entered_at is not None


def test_mark_missing_project_entered_rejected(conn):
    with pytest.raises(repo.NotFoundError):
        repo.mark_project_entered(conn, 999)


def test_add_event(conn):
    project = repo.create_project(conn, "P")

    repo.add_event(conn, project.id, "enter", "成功 1 个")

    row = conn.execute(
        "SELECT * FROM events WHERE project_id = ?", (project.id,)
    ).fetchone()
    assert row is not None
    assert row["type"] == "enter"
    assert row["detail"] == "成功 1 个"
    assert row["ts"]
