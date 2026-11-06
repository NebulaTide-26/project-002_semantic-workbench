from __future__ import annotations

import ctypes

from app.core.desktop_items import collect_desktop_items, kind_for_path
from app.core.models import ResourceKind


def _touch(path):
    path.write_text("", encoding="utf-8")


def test_kind_for_path(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    assert kind_for_path(folder) is ResourceKind.FOLDER

    for name, expected in [
        ("a.lnk", ResourceKind.FILE),
        ("a.exe", ResourceKind.APP),
        ("a.com", ResourceKind.APP),
        ("a.txt", ResourceKind.FILE),
    ]:
        path = tmp_path / name
        _touch(path)
        assert kind_for_path(path) is expected


def test_collect_desktop_items(tmp_path):
    user = tmp_path / "user"
    public = tmp_path / "public"
    user.mkdir()
    public.mkdir()

    _touch(user / "Astrbot.lnk")
    (user / "folder").mkdir()
    _touch(user / "note.txt")
    _touch(user / "desktop.ini")

    hidden = user / "hidden.txt"
    _touch(hidden)
    assert ctypes.windll.kernel32.SetFileAttributesW(str(hidden), 0x2)

    _touch(public / "ISE.lnk")
    _touch(public / "tool.exe")

    items = collect_desktop_items(
        [(user, "用户桌面"), (public, "公共桌面")]
    )

    assert [item.path.name for item in items] == [
        "Astrbot.lnk",
        "folder",
        "note.txt",
        "ISE.lnk",
        "tool.exe",
    ]
    assert [item.kind_label for item in items] == [
        "快捷方式",
        "文件夹",
        "文件",
        "快捷方式",
        "程序",
    ]
    assert [item.location for item in items] == [
        "用户桌面",
        "用户桌面",
        "用户桌面",
        "公共桌面",
        "公共桌面",
    ]
    assert "desktop.ini" not in [item.path.name for item in items]
    assert "hidden.txt" not in [item.path.name for item in items]


def test_collect_desktop_items_skips_missing_dirs(tmp_path):
    items = collect_desktop_items([(tmp_path / "missing", "用户桌面")])
    assert items == []
