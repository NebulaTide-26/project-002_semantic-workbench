"""所有「碰操作系统」的调用集中在这里。

core 层不直接调用这些函数：由入口（main.py / UI）注入，测试时替换成假实现。
"""

from __future__ import annotations

import os
import struct
import subprocess
from pathlib import Path

from app.core.models import Resource, ResourceKind

_CONSOLE_SUBSYSTEM = 3
_SW_SHOWMAXIMIZED = 3


def open_resource(
    resource: Resource, cwd: str | None = None, maximize: bool = False
) -> None:
    """按资源类型调用对应的系统能力。失败时抛异常，由 launcher 记录原因。"""
    if resource.kind is ResourceKind.URL:
        _open_url(resource.target, maximize)
    elif resource.kind in (ResourceKind.FILE, ResourceKind.FOLDER):
        os.startfile(  # type: ignore[attr-defined]  # 仅 Windows
            resource.target, show_cmd=_show_cmd(maximize)
        )
    elif resource.kind is ResourceKind.APP:
        _launch_app(resource.target, resource.args, cwd, maximize)
    else:
        raise ValueError(f"未知资源类型：{resource.kind}")


def open_folder(path: str | Path) -> None:
    """用资源管理器打开文件夹。"""
    os.startfile(str(path))  # type: ignore[attr-defined]


def _show_cmd(maximize: bool) -> int:
    return _SW_SHOWMAXIMIZED if maximize else 1  # 1 = SW_SHOWNORMAL


def _open_url(url: str, maximize: bool) -> None:
    os.startfile(url, show_cmd=_show_cmd(maximize))  # type: ignore[attr-defined]


def pe_subsystem(path: str | Path) -> int | None:
    """读取 PE 头的 Subsystem 字段：2=GUI，3=控制台；非 PE 文件返回 None。"""
    try:
        with open(path, "rb") as handle:
            data = handle.read(65536)
    except OSError:
        return None

    if len(data) < 64 or data[:2] != b"MZ":
        return None

    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    # PE 签名 4 字节 + 可选头里的 Subsystem 偏移 68
    subsystem_offset = pe_offset + 24 + 68
    if subsystem_offset + 2 > len(data):
        return None
    if data[pe_offset : pe_offset + 4] != b"PE\0\0":
        return None

    return struct.unpack_from("<H", data, subsystem_offset)[0]


def _launch_app(
    target: str, args: list[str], cwd: str | None, maximize: bool
) -> None:
    work_dir = cwd if cwd and Path(cwd).is_dir() else None

    # 控制台程序默认会继承 Workbench 自己的控制台，导致不弹新窗口；
    # 给它单独开一个控制台。GUI 程序保持默认。
    creationflags = 0
    if pe_subsystem(target) == _CONSOLE_SUBSYSTEM:
        creationflags = subprocess.CREATE_NEW_CONSOLE

    startupinfo = None
    if maximize:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = _SW_SHOWMAXIMIZED

    subprocess.Popen(
        [target, *args],
        cwd=work_dir,
        creationflags=creationflags,
        startupinfo=startupinfo,
    )
